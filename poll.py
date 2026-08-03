"""Run the bot with long polling.

    python poll.py

Your machine calls out to api.telegram.org and holds the request open until a
message arrives, so nothing needs to reach in: no public URL, no HTTPS cert,
no tunnel, no Telegram-side setup beyond the bot token.

Press Ctrl+C to stop.
"""

import logging
import os
import sys
import threading
import time
from contextlib import contextmanager

import dotenv

import mainHandler
import telegram

dotenv.load_dotenv()

# A Turkish console is cp1254, which cannot encode emoji. Messages are full of
# them, and every one would dump a UnicodeEncodeError traceback into the
# terminal - logging swallows it, so the bot survives, but the log becomes
# unreadable exactly when something is going wrong.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

COMMANDS = {
    "/start": "Bot is running.\nSend me a message.",
    "/help": (
        "Available commands:\n"
        "/start\n"
        "/help\n"
        "/health\n"
        "/agent - show or switch which agent you are talking to\n"
        "/reset - forget this chat's history and start over"
    ),
    "/health": "healthy",
}

# Telegram rejects sendMessage above 4096 UTF-16 code units. Leave headroom.
MAX_MESSAGE_UNITS = 4000


def _parse_allowed_users() -> set[int]:
    """Telegram user ids allowed to talk to the bot, from TELEGRAM_ALLOWED_USERS.

    Empty means anyone can use it, which also means anyone who finds the bot
    spends your OpenAI credits. check_config warns loudly in that case.
    """

    allowed: set[int] = set()

    for part in os.getenv("TELEGRAM_ALLOWED_USERS", "").replace(";", ",").split(","):
        part = part.strip()

        if not part:
            continue

        try:
            allowed.add(int(part))
        except ValueError:
            logger.warning("Ignoring non-numeric id in TELEGRAM_ALLOWED_USERS: %r", part)

    return allowed


ALLOWED_USER_IDS = _parse_allowed_users()


def is_allowed(user_id: int | None) -> bool:
    if not ALLOWED_USER_IDS:
        return True

    return user_id in ALLOWED_USER_IDS


def split_for_telegram(text: str, limit: int = MAX_MESSAGE_UNITS) -> list[str]:
    """Split text into pieces Telegram will accept.

    The limit is in UTF-16 code units, not characters: emoji and other
    non-BMP characters cost two units each, so counting Python characters
    would let an all-emoji reply through at roughly twice the real size.
    """

    chunks: list[str] = []
    current: list[str] = []
    size = 0

    for char in text:
        char_size = 2 if ord(char) > 0xFFFF else 1

        if size + char_size > limit:
            chunks.append("".join(current))
            current, size = [], 0

        current.append(char)
        size += char_size

    if current:
        chunks.append("".join(current))

    return chunks


def send_reply(chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
    """Send text, splitting anything Telegram would reject for length."""

    if not text or not text.strip():
        # send_message raises on empty text, so a blank model reply would
        # otherwise look like a crash to the user.
        text = "(the agent returned an empty response)"

    chunks = split_for_telegram(text)

    for index, chunk in enumerate(chunks):
        telegram.send_message(
            chat_id,
            chunk,
            # Only the first chunk quotes the incoming message.
            reply_to_message_id=reply_to_message_id if index == 0 else None,
        )


# Telegram drops the indicator after ~5s, so it has to be refreshed while the
# agent thinks. A tool-using turn can take the best part of a minute.
TYPING_REFRESH_SECONDS = 4.0


@contextmanager
def typing(chat_id: int):
    """Keep "typing..." visible for as long as the block runs.

    Purely cosmetic, so it must never affect the reply: the refresh runs on a
    daemon thread and swallows its own errors. A failed chat action is not a
    reason to lose a message the user is waiting for.
    """

    stop = threading.Event()

    def refresh() -> None:
        while not stop.is_set():
            try:
                telegram.send_chat_action(chat_id, "typing")
            except Exception:
                logger.debug("typing indicator failed for %s", chat_id, exc_info=True)
                return

            stop.wait(TYPING_REFRESH_SECONDS)

    worker = threading.Thread(target=refresh, daemon=True)
    worker.start()

    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=1)


THINKING_TEXT = "💭 Thinking..."

# What each tool is doing, in the user's terms. A name like "list_tasks" means
# nothing to the person waiting.
TOOL_ACTIVITY = {
    "list_tasks": "reading your tasks",
    "create_task": "adding a task",
    "complete_task": "ticking a task off",
    "update_task": "updating a task",
    "move_task": "moving a task",
    "list_goals": "checking your goals",
    "add_goal": "saving a goal",
    "update_goal": "updating a goal",
    "log_checkin": "writing up the day",
    "remember": "making a note",
    "read_context_file": "reading its notes",
    "update_context_file": "rewriting its notes",
}


class ThinkingBox:
    """A placeholder message that narrates the wait, then becomes the answer.

    Editing one message rather than sending several keeps the chat clean: the
    user ends up with a single reply, not a trail of status updates.
    """

    def __init__(self, chat_id: int, reply_to_message_id: int | None = None) -> None:
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.message_id: int | None = None
        self.steps: list[str] = []

    def open(self) -> None:
        try:
            sent = telegram.send_message(
                self.chat_id, THINKING_TEXT, reply_to_message_id=self.reply_to_message_id
            )
            self.message_id = (sent or {}).get("message_id")
        except Exception:
            # The box is decoration; losing it must not cost the reply. Without
            # a message_id everything below turns into a plain send.
            logger.debug("could not open thinking box", exc_info=True)

    def on_progress(self, tool_names: list[str]) -> None:
        for name in tool_names:
            activity = TOOL_ACTIVITY.get(name, name)
            if activity not in self.steps:
                self.steps.append(activity)

        self._edit(THINKING_TEXT + "\n" + "\n".join(f"· {s}" for s in self.steps))

    def close(self, text: str) -> None:
        """Replace the box with the finished reply."""

        chunks = split_for_telegram(text)

        if self.message_id is None or not self._edit(chunks[0]):
            # No box, or it could not be edited: send the first chunk instead.
            # If that fails too there is nowhere left to put the reply.
            if not self._send(chunks[0]):
                return

        # Either way chunk 0 has now been delivered exactly once.
        for chunk in chunks[1:]:
            self._send(chunk)

    def _edit(self, text: str) -> bool:
        if self.message_id is None:
            return False

        try:
            telegram.edit_message_text(self.chat_id, self.message_id, text)
            return True
        except Exception:
            logger.debug("could not edit thinking box", exc_info=True)
            return False

    def _send(self, text: str) -> bool:
        try:
            telegram.send_message(self.chat_id, text)
            return True
        except Exception:
            logger.exception("could not deliver reply to %s", self.chat_id)
            return False


def switch_agent(chat_id: int, argument: str) -> str:
    """Show or change which agent this chat talks to."""

    active = mainHandler.activeHandleFor(chat_id)
    names = mainHandler.handleNames()

    if not argument:
        listing = "\n".join(
            f"{'* ' if name == active else '  '}{name}" for name in names
        )
        return f"Talking to: {active}\n\n{listing}\n\nSwitch with: /agent <name>"

    # Match case-insensitively so "/agent life coach" works from a phone.
    for name in names:
        if name.casefold() == argument.casefold():
            mainHandler.setActiveHandle(chat_id, name)
            return f"Now talking to {name}. Each agent keeps its own memory."

    return f"No agent called '{argument}'. Options: {', '.join(names)}"


def answer(chat_id: int, text: str, on_progress=None) -> str:
    """Turn an incoming message into reply text."""

    if text == "/agent" or text.startswith("/agent "):
        return switch_agent(chat_id, text[len("/agent") :].strip())

    handle_name = mainHandler.activeHandleFor(chat_id)

    if text == "/reset":
        # Needs the chat_id, so it cannot live in the static COMMANDS table.
        previous = mainHandler.resetConversation(handle_name, chat_id)

        if previous is None:
            return f"Nothing to forget yet - no history with {handle_name}."

        return f"Memory cleared for {handle_name}. The next message starts fresh."

    if text in COMMANDS:
        return COMMANDS[text]

    conversation_id = mainHandler.conversationIdFor(handle_name, chat_id)
    handle = mainHandler.loadHandle(
        handle_name, conversation_id=conversation_id, chat_id=chat_id
    )

    return handle.sendMessageAgent("telegram", text, on_progress=on_progress)


def on_update(update: dict) -> None:
    """Handle one Telegram update. Must not raise: an exception here would
    kill the polling loop and drop every later message."""

    message = telegram.message_from_update(update)

    if not message:
        return

    chat_id = (message.get("chat") or {}).get("id")
    user_id = (message.get("from") or {}).get("id")
    message_id = message.get("message_id")
    text = message.get("text")

    if chat_id is None:
        return

    # Checked on the sender, not the chat, so adding the bot to a group does
    # not hand strangers your OpenAI budget. Done before anything reaches the
    # agent, so a rejected message costs nothing but one Telegram call.
    if not is_allowed(user_id):
        logger.warning("Ignored message from unauthorised user %s in chat %s", user_id, chat_id)

        try:
            telegram.send_message(chat_id, "Sorry, this is a private bot.")
        except Exception:
            logger.exception("Could not reply to unauthorised user %s", user_id)

        return

    box: ThinkingBox | None = None

    try:
        if not isinstance(text, str) or not text.strip():
            telegram.send_message(chat_id, "I currently support text messages only.")
            return

        text = text.strip()
        logger.info("[%s] %s", chat_id, text)

        if text.startswith("/"):
            # Commands answer instantly; a thinking box would just flicker.
            send_reply(chat_id, answer(chat_id, text), reply_to_message_id=message_id)
            return

        box = ThinkingBox(chat_id, reply_to_message_id=message_id)
        box.open()

        with typing(chat_id):
            reply = answer(chat_id, text, on_progress=box.on_progress)

        box.close(reply)

    except Exception:
        logger.exception("Failed to answer chat %s", chat_id)

        notice = "Something went wrong on my side. Check the logs."

        try:
            if box is not None:
                # Otherwise the box sits on "Thinking..." forever and the user
                # has no idea the turn already failed.
                box.close(notice)
            else:
                telegram.send_message(chat_id, notice)
        except Exception:
            logger.exception("Could not deliver the error notice to %s", chat_id)


def check_config() -> None:
    """Fail at startup on a bad handles.json, not on every message.

    A typo in a handle's tools list otherwise surfaces as a generic "something
    went wrong" for each message forever, with the real reason buried in a
    traceback.
    """

    from tools import build_registry

    for config in mainHandler.loadHandleConfigs():
        name = config.get("handleName")
        registry = build_registry(
            config.get("tools") or [], 0, context_path=config.get("contextPath")
        )
        logger.info(
            "handle %-14s tools: %s", name, ", ".join(registry.names()) or "none"
        )

    if ALLOWED_USER_IDS:
        logger.info("allowlist: %s", ", ".join(str(i) for i in sorted(ALLOWED_USER_IDS)))
    else:
        logger.warning(
            "TELEGRAM_ALLOWED_USERS is empty - anyone who finds this bot can use "
            "it and spend your OpenAI credits."
        )


def main() -> None:
    check_config()

    bot = telegram.get_me()
    logger.info("Connected as @%s", bot.get("username"))

    # getUpdates and a registered webhook are mutually exclusive.
    telegram.delete_webhook()

    # Skip whatever piled up while the bot was offline, so a restart does not
    # replay an old backlog through the agent.
    offset = None
    backlog = telegram.get_updates(timeout=0)

    if backlog:
        offset = backlog[-1]["update_id"] + 1
        logger.info("Skipped %d queued update(s)", len(backlog))

    logger.info("Listening. Message the bot on Telegram. Ctrl+C to stop.")

    # The loop lives here rather than in telegram.listen() so that offset
    # survives a retry. Resuming from a stale offset would make Telegram
    # redeliver messages the agent has already answered.
    while True:
        try:
            updates = telegram.get_updates(
                offset=offset,
                allowed_updates=["message"],
            )
        except (telegram.TelegramAPIError, OSError) as exc:
            if getattr(exc, "status_code", None) == 409:
                # Not a network blip: a second process is polling the same bot
                # token and each one tears down the other's request. A stack
                # trace every 5s just buries the one thing worth saying.
                logger.error(
                    "Another process is polling this bot token, so updates are "
                    "being fought over. Telegram allows only one. Stop the other "
                    "instance (or openclaw, if it uses this bot). Retrying in 5s."
                )
            else:
                # Transient network/API trouble: log it and resume rather than
                # dying overnight. OSError covers a dropped connection
                # surfacing below the telegram module.
                logger.exception("Telegram API error, retrying in 5s")

            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            on_update(update)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Stopped.")
