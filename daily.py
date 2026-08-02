"""Daily check-in: the coach messages you first.

    python daily.py                 # send today's check-in if not sent yet
    python daily.py --force         # send even if today's already went out
    python daily.py --handle "Life Coach"

Run it from Windows Task Scheduler once a day. It does not need poll.py to be
running - it only sends. Nothing here calls getUpdates, so it cannot collide
with the poller the way a second bot instance would.

Scheduling it (Task Scheduler, once, daily at 20:00):

    schtasks /create /tn "LifeCoachDaily" /tr ^
      "\"C:\\Users\\deniz\\AppData\\Local\\Programs\\Python\\Python310\\python.exe\" ^
       \"D:\\projects\\better_than_claws\\daily.py\"" /sc daily /st 20:00

The once-a-day guard lives in daily_runs.json, so running it twice by hand or
catching up after the machine was asleep will not double-message you.
"""

import argparse
import logging
import sys
from datetime import date

import dotenv

import mainHandler
import telegram
from poll import send_reply
from tools._store import read_json, update_json

dotenv.load_dotenv()

# Same cp1254 problem as poll.py: task titles are Turkish and often have emoji.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

DEFAULT_HANDLE = "Life Coach"
RUNS_PATH = mainHandler.BASE_DIR / "daily_runs.json"

# The coach sees this instead of a user message. It is written as an
# instruction to the agent, not as text to relay, so the agent still speaks in
# its own voice rather than echoing a template.
CHECKIN_PROMPT = """It is time for your daily check-in with the user. They have not
written to you - you are opening the conversation.

Do this now, using your tools:
1. Call list_tasks to see what they completed today and what is still open.
2. Call list_goals to see their goals and recent check-ins.
3. Write them a short message that:
   - names specifically what they finished today and credits it honestly
   - flags anything overdue or drifting, without nagging
   - connects today back to their goals, referring to real progress history
   - asks exactly one concrete question about what they did or will do next
4. Call log_checkin with a factual summary of the day.

If they have no tasks at all, tell them plainly that nothing is tracked and ask
them to add two or three concrete things, or offer to create them.
If they have no goals yet, ask what they want to work towards and steer them
to something measurable.

Keep it under 150 words. Be warm but specific - no generic motivation."""


def already_ran_today(handle_name: str) -> bool:
    return read_json(RUNS_PATH).get(handle_name) == date.today().isoformat()


def mark_ran_today(handle_name: str) -> None:
    update_json(RUNS_PATH, lambda runs: runs.__setitem__(handle_name, date.today().isoformat()))


def run(handle_name: str, force: bool = False) -> int:
    if already_ran_today(handle_name) and not force:
        logger.info("Check-in for %s already sent today. Use --force to resend.", handle_name)
        return 0

    handle = mainHandler.loadHandle(handle_name)
    chat_id = handle.telegram_chat_id

    if not isinstance(chat_id, int):
        logger.error(
            "handles.json has no numeric telegramChatId for %s, so there is "
            "nowhere to send the check-in. Message the bot once and use the "
            "chat id from the poll.py log.",
            handle_name,
        )
        return 1

    conversation_id = mainHandler.conversationIdFor(handle_name, chat_id)
    handle = mainHandler.loadHandle(
        handle_name, conversation_id=conversation_id, chat_id=chat_id
    )

    logger.info("Running daily check-in for %s -> chat %s", handle_name, chat_id)

    reply = handle.sendMessageAgent("telegram", CHECKIN_PROMPT)

    send_reply(chat_id, reply)
    mark_ran_today(handle_name)

    logger.info("Check-in sent.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the daily coach check-in.")
    parser.add_argument("--handle", default=DEFAULT_HANDLE)
    parser.add_argument("--force", action="store_true", help="Send even if today's already went out.")
    args = parser.parse_args()

    try:
        return run(args.handle, force=args.force)
    except telegram.TelegramAPIError:
        logger.exception("Could not deliver the check-in")
        return 1
    except Exception:
        logger.exception("Daily check-in failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
