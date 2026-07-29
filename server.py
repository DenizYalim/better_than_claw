import hmac
import logging
import os
from typing import Any

import requests
from flask import Flask, abort, request
import telegram2
import mainHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = Flask(__name__)


def handle_message(
    text: str,
    user_id: int,
    chat_id: int,
) -> str:

    if text == "/health":
        return "healthy"

    if text == "/start":
        return "Bot is running.\n" "Send me a message."

    if text == "/help":
        return "Available commands:\n" "/start\n" "/help"

    handle = mainHandler.loadHandle("default")  # TODO

    return handle.sendMessageAgent("telegram", text)


@app.get("/")
def index() -> dict[str, str]:
    return {
        "service": "telegram-webhook",
        "status": "running",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/telegram/webhook")
def telegram_webhook() -> tuple[dict[str, bool], int]:
    verify_telegram_secret()

    update = request.get_json(silent=True)

    if not isinstance(update, dict):
        return {"ok": False}, 400

    logger.info(
        "Received Telegram update: %s",
        update.get("update_id"),
    )

    # This example processes normal incoming messages.
    message = update.get("message")

    if not isinstance(message, dict):
        # Ignore callback queries, edited messages and other updates.
        return {"ok": True}, 200

    chat = message.get("chat", {})
    sender = message.get("from", {})

    chat_id = chat.get("id")
    user_id = sender.get("id")
    message_id = message.get("message_id")
    text = message.get("text")

    if not isinstance(chat_id, int):
        return {"ok": True}, 200

    if not isinstance(user_id, int):
        return {"ok": True}, 200

    if not isinstance(text, str):
        telegram2.send_message(
            chat_id=chat_id,
            text="I currently support text messages only.",
            reply_to_message_id=message_id,
        )

        return {"ok": True}, 200

    try:
        response_text = handle_message(
            text=text.strip(),
            user_id=user_id,
            chat_id=chat_id,
        )

        telegram2.send_message(
            chat_id=chat_id,
            text=response_text,
            reply_to_message_id=message_id,
        )

    except Exception:
        logger.exception(
            "Failed to process update %s",
            update.get("update_id"),
        )

        # Return 200 so Telegram does not repeatedly deliver
        # a message that failed inside the application.
        return {"ok": True}, 200

    return {"ok": True}, 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
        debug=False,
    )
