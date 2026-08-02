"""Register, inspect or remove the Telegram webhook.

Usage:
    python setup_webhook.py set https://your-public-host/telegram/webhook
    python setup_webhook.py info
    python setup_webhook.py delete

Telegram only accepts HTTPS URLs, so for local development put a tunnel in
front of server.py first, for example:

    cloudflared tunnel --url http://localhost:8000
    ngrok http 8000

then pass the https URL the tunnel prints, with /telegram/webhook appended.
"""

import json
import os
import sys

import dotenv

import telegram

dotenv.load_dotenv()


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "info"

    if command == "info":
        print(json.dumps(telegram.get_webhook_info(), indent=4))
        return 0

    if command == "delete":
        telegram.delete_webhook(drop_pending_updates=True)
        print("Webhook deleted. Long polling works again.")
        return 0

    if command == "set":
        if len(sys.argv) < 3:
            print("Usage: python setup_webhook.py set https://host/telegram/webhook")
            return 1

        url = sys.argv[2]
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")

        if not secret:
            print(
                "TELEGRAM_WEBHOOK_SECRET is not set in .env.\n"
                "Anyone who finds the URL could post fake updates. Add one, e.g.\n"
                '  TELEGRAM_WEBHOOK_SECRET=<random string, A-Z a-z 0-9 _ ->'
            )
            return 1

        telegram.set_webhook(
            url=url,
            secret_token=secret,
            allowed_updates=["message"],
            drop_pending_updates=True,
        )

        print(f"Webhook set to {url}")
        print(json.dumps(telegram.get_webhook_info(), indent=4))
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
