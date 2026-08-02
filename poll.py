"""Run the bot with long polling - no public URL, no HTTPS, no tunnel.

    python poll.py

This is the development path. It reuses the same handle/agent code as the
webhook in server.py, so behaviour matches. Telegram refuses getUpdates while
a webhook is registered, so this deletes the webhook on startup.

Press Ctrl+C to stop.
"""

import logging

import dotenv

import mainHandler
import telegram

dotenv.load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

HANDLE_NAME = "default"


def reply_to(update: dict) -> None:
    message = telegram.message_from_update(update)

    if not message:
        return

    chat_id = (message.get("chat") or {}).get("id")
    text = message.get("text")

    if chat_id is None:
        return

    if not isinstance(text, str):
        telegram.send_message(chat_id, "I currently support text messages only.")
        return

    text = text.strip()
    logger.info("[%s] %s", chat_id, text)

    if text == "/start":
        telegram.send_message(chat_id, "Bot is running.\nSend me a message.")
        return

    if text == "/help":
        telegram.send_message(chat_id, "Available commands:\n/start\n/help")
        return

    try:
        conversation_id = mainHandler.conversationIdFor(HANDLE_NAME, chat_id)
        handle = mainHandler.loadHandle(HANDLE_NAME, conversation_id=conversation_id)
        reply = handle.sendMessageAgent("telegram", text)
    except Exception:
        logger.exception("Failed to answer chat %s", chat_id)
        telegram.send_message(chat_id, "Something went wrong on my side.")
        return

    telegram.send_message(chat_id, reply, reply_to_message_id=message.get("message_id"))


def main() -> None:
    bot = telegram.get_me()
    logger.info("Connected as @%s", bot.get("username"))

    # getUpdates and a registered webhook are mutually exclusive.
    telegram.delete_webhook()

    # Skip whatever piled up while the bot was offline.
    offset = None
    backlog = telegram.get_updates(timeout=0)
    if backlog:
        offset = backlog[-1]["update_id"] + 1
        logger.info("Skipped %d queued update(s)", len(backlog))

    logger.info("Listening. Message the bot on Telegram.")

    telegram.listen(
        handler=reply_to,
        offset=offset,
        allowed_updates=["message"],
        once=False,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Stopped.")
