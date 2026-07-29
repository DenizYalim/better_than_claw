import logging
import os

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]

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
