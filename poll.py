"""Run the bot with long polling.

    python poll.py

Your machine calls out to api.telegram.org and holds the request open until a
message arrives, so nothing needs to reach in: no public URL, no HTTPS cert,
no tunnel, no Telegram-side setup beyond the bot token.

Press Ctrl+C to stop.
"""

import logging
import os
import time

import dotenv

import mainHandler
import telegram

dotenv.load_dotenv()

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


def answer(chat_id: int, text: str) -> str:
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

    return handle.sendMessageAgent("telegram", text)


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

    try:
        if not isinstance(text, str) or not text.strip():
            telegram.send_message(chat_id, "I currently support text messages only.")
            return

        text = text.strip()
        logger.info("[%s] %s", chat_id, text)

        reply = answer(chat_id, text)

        send_reply(chat_id, reply, reply_to_message_id=message_id)

    except Exception:
        logger.exception("Failed to answer chat %s", chat_id)

        try:
            telegram.send_message(
                chat_id, "Something went wrong on my side. Check the logs."
            )
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
