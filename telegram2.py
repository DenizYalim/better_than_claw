import hmac
import logging
import os
from typing import Any

import dotenv
import requests
from flask import abort, request

dotenv.load_dotenv()

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def call_telegram_api(
    method: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Call a Telegram Bot API method."""

    response = requests.post(
        f"{TELEGRAM_API_URL}/{method}",
        json=payload,
        timeout=15,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    return result


def send_message(
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_to_message_id is not None:
        payload["reply_parameters"] = {
            "message_id": reply_to_message_id,
        }

    call_telegram_api("sendMessage", payload)


def verify_telegram_secret() -> None:
    """Reject webhook calls that do not carry our shared secret.

    Telegram echoes back the secret_token passed to setWebhook in the
    X-Telegram-Bot-Api-Secret-Token header. Without it the endpoint is open
    to anyone who guesses the URL.
    """

    if not WEBHOOK_SECRET:
        logger.warning(
            "TELEGRAM_WEBHOOK_SECRET is not set - webhook is unauthenticated."
        )
        return

    received_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        "",
    )

    if not hmac.compare_digest(
        received_secret,
        WEBHOOK_SECRET,
    ):
        logger.warning("Rejected webhook request with invalid secret.")
        abort(403)
