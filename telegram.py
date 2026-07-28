from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any


API_BASE_URL = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS = 30


class TelegramAPIError(RuntimeError):
    """Raised when Telegram returns an API error."""


def send_message(
    chat_id: int | str,
    text: str,
    bot_token: str | None = None,
    parse_mode: str | None = None,
    disable_notification: bool = False,
    protect_content: bool = False,
    message_thread_id: int | None = None,
    reply_to_message_id: int | None = None,
    link_preview_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Send a text message through a Telegram bot.

    Args:
        chat_id: Numeric chat ID, or @username for public channels/groups.
        text: Message text.
        bot_token: Bot token from BotFather. Defaults to TELEGRAM_BOT_TOKEN.
        parse_mode: Optional "HTML", "Markdown", or "MarkdownV2".
    """
    if chat_id is None or str(chat_id).strip() == "":
        raise ValueError("chat_id is required")
    if not text or not text.strip():
        raise ValueError("text is required")

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_notification": disable_notification,
        "protect_content": protect_content,
        "message_thread_id": message_thread_id,
        "reply_to_message_id": reply_to_message_id,
        "link_preview_options": link_preview_options,
    }
    return telegram_request("sendMessage", payload, bot_token)


def get_me(bot_token: str | None = None) -> dict[str, Any]:
    """Return basic information about the bot and validate the token."""
    return telegram_request("getMe", bot_token=bot_token)


def get_updates(
    bot_token: str | None = None,
    offset: int | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    limit: int = 100,
    allowed_updates: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Receive incoming updates using long polling.

    This is useful during local development. It will not work while a webhook is
    set for the same bot.
    """
    payload = {
        "offset": offset,
        "timeout": timeout,
        "limit": limit,
        "allowed_updates": allowed_updates,
    }
    return telegram_request("getUpdates", payload, bot_token)


def listen(
    bot_token: str | None = None,
    handler: Callable[[dict[str, Any]], None] | None = None,
    offset: int | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    limit: int = 100,
    allowed_updates: list[str] | None = None,
    once: bool = True,
    sleep_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    """
    Poll Telegram updates and optionally call handler(update) for each one.

    Keep once=True for a single fetch. Set once=False to run a simple polling
    loop during development.
    """
    seen_updates: list[dict[str, Any]] = []

    while True:
        updates = get_updates(
            bot_token=bot_token,
            offset=offset,
            timeout=timeout,
            limit=limit,
            allowed_updates=allowed_updates,
        )
        seen_updates.extend(updates)

        for update in updates:
            offset = update["update_id"] + 1
            if handler is not None:
                handler(update)

        if once:
            return seen_updates

        time.sleep(sleep_seconds)


def set_webhook(
    url: str,
    bot_token: str | None = None,
    secret_token: str | None = None,
    allowed_updates: list[str] | None = None,
    drop_pending_updates: bool = False,
    max_connections: int | None = None,
    ip_address: str | None = None,
) -> bool:
    """
    Configure Telegram to POST updates to your HTTPS webhook URL.

    secret_token is sent back by Telegram in the
    X-Telegram-Bot-Api-Secret-Token header.
    """
    if not url or not url.strip():
        raise ValueError("url is required")
    if not url.startswith("https://"):
        raise ValueError("Telegram webhooks require an HTTPS URL")
    if secret_token is not None:
        _validate_secret_token(secret_token)

    payload = {
        "url": url,
        "secret_token": secret_token,
        "allowed_updates": allowed_updates,
        "drop_pending_updates": drop_pending_updates,
        "max_connections": max_connections,
        "ip_address": ip_address,
    }
    return bool(telegram_request("setWebhook", payload, bot_token))


def delete_webhook(
    bot_token: str | None = None,
    drop_pending_updates: bool = False,
) -> bool:
    """Remove the webhook so you can use get_updates/listen again."""
    payload = {"drop_pending_updates": drop_pending_updates}
    return bool(telegram_request("deleteWebhook", payload, bot_token))


def get_webhook_info(bot_token: str | None = None) -> dict[str, Any]:
    """Return Telegram's current webhook status for this bot."""
    return telegram_request("getWebhookInfo", bot_token=bot_token)


def message_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the message-like object from a Telegram update, if present."""
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        if key in update:
            return update[key]
    return None


def chat_id_from_update(update: dict[str, Any]) -> int | str | None:
    """Extract chat.id from a Telegram update, if present."""
    message = message_from_update(update)
    if not message:
        return None
    chat = message.get("chat") or {}
    return chat.get("id")


def telegram_request(
    method: str,
    payload: dict[str, Any] | None = None,
    bot_token: str | None = None,
) -> Any:
    """Call a Telegram Bot API method and return its result field."""
    token = _resolve_bot_token(bot_token)
    url = f"{API_BASE_URL}/bot{token}/{method}"
    request_body = json.dumps(_without_none(payload or {})).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
            response = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _error_from_http(method, exc) from exc
    except urllib.error.URLError as exc:
        raise TelegramAPIError(f"Telegram API {method} request failed: {exc}") from exc

    if not response.get("ok"):
        description = response.get("description", "unknown Telegram API error")
        error_code = response.get("error_code", "unknown")
        raise TelegramAPIError(
            f"Telegram API {method} failed with {error_code}: {description}"
        )

    return response.get("result")


def _resolve_bot_token(bot_token: str | None) -> str:
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or _read_dotenv_value(
        "TELEGRAM_BOT_TOKEN"
    )
    if not token or not token.strip():
        raise ValueError(
            "bot_token is required, or set TELEGRAM_BOT_TOKEN in your environment/.env"
        )
    return token.strip()


def _read_dotenv_value(key: str) -> str | None:
    seen: set[Path] = set()
    candidates = [Path.cwd() / ".env"]
    candidates.extend(parent / ".env" for parent in Path(__file__).resolve().parents)

    for candidate in candidates:
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() == key:
                return value.strip().strip('"').strip("'")

    return None


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _validate_secret_token(secret_token: str) -> None:
    if not 1 <= len(secret_token) <= 256:
        raise ValueError("secret_token must be 1-256 characters")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
    if any(char not in allowed for char in secret_token):
        raise ValueError("secret_token may only contain A-Z, a-z, 0-9, _ and -")


def _error_from_http(method: str, exc: urllib.error.HTTPError) -> TelegramAPIError:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        response = json.loads(body)
        description = response.get("description", body)
    except json.JSONDecodeError:
        description = body
    return TelegramAPIError(
        f"Telegram API {method} failed with HTTP {exc.code}: {description}"
    )
