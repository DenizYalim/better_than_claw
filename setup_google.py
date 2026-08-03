"""One-time Google Tasks authorisation.

    python setup_google.py

Opens a browser, asks you to grant access, and writes token.json. Run it once
before starting the bot, and again only if you revoke access or change SCOPES.

This is the only place the consent flow may run. It blocks until you finish in
the browser, which is fine here and would be fatal inside the bot: poll.py is
single-threaded, so a consent prompt mid-conversation would freeze every chat
with no timeout.

Before running, you need an OAuth client:
  1. console.cloud.google.com -> create/pick a project
  2. Enable the "Google Tasks API"
  3. APIs & Services -> Credentials -> Create credentials
     -> OAuth client ID -> Desktop app
  4. Download the JSON, save it next to this file as credentials.json
"""

from pathlib import Path

import dotenv

from tools import __google_tasks as google_tasks

dotenv.load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    credentials = BASE_DIR / "credentials.json"

    if not credentials.exists():
        print(f"No credentials.json at {credentials}\n")
        print(__doc__)
        return 1

    print("Opening your browser for Google consent...")

    try:
        google_tasks.connect_google_tasks(
            credentials_path=credentials,
            token_path=BASE_DIR / "token.json",
            allow_interactive=True,
        )
    except Exception as exc:
        print(f"Authorisation failed: {type(exc).__name__}: {exc}")
        return 1

    print("Authorised. token.json written.\n")

    try:
        lists = google_tasks.list_task_lists(
            credentials_path=credentials,
            token_path=BASE_DIR / "token.json",
        )
        print(f"Found {len(lists)} task list(s):")
        for task_list in lists:
            print(f"  - {task_list['title']}  (id: {task_list['id']})")
    except Exception as exc:
        print(f"Connected, but listing task lists failed: {exc}")
        return 1

    print("\nGoogle Tasks is ready. The bot can use it now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
