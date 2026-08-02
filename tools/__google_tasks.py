from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

# Full read/write scope. If you change this later, delete token.json and auth
# again.
SCOPES = ["https://www.googleapis.com/auth/tasks"]
DEFAULT_TASKLIST = "@default"

# Building a service performs an API discovery fetch, and every public function
# here starts by connecting. Without this cache a "find task then complete it"
# flow pays for auth and discovery twice.
_SERVICE_CACHE: dict[tuple[str, str], Any] = {}


class GoogleTasksNotConnected(RuntimeError):
    """Raised when there is no usable token and we refuse to prompt for one."""


def connect_google_tasks(
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
    allow_interactive: bool = False,
) -> Any:
    """
    Authenticate with Google Tasks and return a Tasks API service object.

    Put your OAuth desktop-client file at ./credentials.json, or set
    GOOGLE_TASKS_CREDENTIALS_FILE. Reusable auth is stored in ./token.json, or
    GOOGLE_TASKS_TOKEN_FILE.

    allow_interactive must stay False anywhere the bot might call this.
    The consent flow spins up a local web server and blocks until a browser
    completes the redirect, which in the single-threaded polling loop would
    freeze the bot for every chat, with no timeout and no log line. Run
    setup_google.py once instead; only it passes allow_interactive=True.
    """
    Request, Credentials, InstalledAppFlow, build = _google_client_imports()
    credentials_file = _path_from_value_or_env(credentials_path, "GOOGLE_TASKS_CREDENTIALS_FILE", "credentials.json")
    token_file = _path_from_value_or_env(token_path, "GOOGLE_TASKS_TOKEN_FILE", "token.json")

    cache_key = (str(credentials_file), str(token_file))

    if not allow_interactive and cache_key in _SERVICE_CACHE:
        return _SERVICE_CACHE[cache_key]

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                # Refresh tokens for an OAuth app still in "Testing" publishing
                # status expire after 7 days, so this fires weekly until the
                # app is published. Say what to do instead of surfacing a raw
                # RefreshError from deep in google.auth.
                raise GoogleTasksNotConnected(
                    "Google Tasks authorisation expired. Run 'python setup_google.py' "
                    "again to renew it. To stop this recurring, set the OAuth app's "
                    f"publishing status to 'In production' in Google Cloud. ({exc})"
                ) from exc
        else:
            if not allow_interactive:
                raise GoogleTasksNotConnected(
                    "Google Tasks is not connected yet. Run 'python setup_google.py' "
                    "once to authorise it, then try again."
                )

            if not credentials_file.exists():
                raise FileNotFoundError(
                    f"Google OAuth credentials not found at {credentials_file}. "
                    "Download a Desktop app OAuth client JSON from Google Cloud and save it there."
                )

            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
            creds = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    service = build("tasks", "v1", credentials=creds)
    _SERVICE_CACHE[cache_key] = service

    return service


def list_task_lists(
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return the authenticated user's task lists."""
    service = connect_google_tasks(credentials_path, token_path)
    return _list_task_lists(service)


def _list_task_lists(service: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = None

    while True:
        list_args: dict[str, Any] = {"maxResults": 100}
        if page_token:
            list_args["pageToken"] = page_token

        response = service.tasklists().list(**list_args).execute()
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "updated": item.get("updated"),
            "self_link": item.get("selfLink"),
        }
        for item in items
    ]


def add_task(
    title: str,
    notes: str | None = None,
    due: str | date | datetime | None = None,
    tasklist: str | None = None,
    parent: str | None = None,
    previous: str | None = None,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Create a Google Task and return the created task.

    Args:
        title: Task title.
        notes: Optional task notes.
        due: Optional due day as YYYY-MM-DD, date, or datetime. Google Tasks
            stores only the date portion, not a due time.
        tasklist: Task list ID. Defaults to @default.
        parent: Optional parent task ID for a subtask.
        previous: Optional previous sibling task ID for ordering.
    """
    if not title or not title.strip():
        raise ValueError("title is required")

    service = connect_google_tasks(credentials_path, token_path)
    body: dict[str, Any] = {"title": title.strip()}

    if notes is not None:
        body["notes"] = notes
    if due is not None:
        body["due"] = _due_rfc3339(due)

    tasklist_id = _tasklist_id(tasklist)
    insert_args: dict[str, Any] = {"tasklist": tasklist_id, "body": body}
    if parent is not None:
        insert_args["parent"] = parent
    if previous is not None:
        insert_args["previous"] = previous

    created_task = service.tasks().insert(**insert_args).execute()
    return _simplify_task(created_task, tasklist_id)


def edit_task(
    task_id: str,
    title: str | None = None,
    notes: str | None = None,
    due: str | date | datetime | None = None,
    status: str | None = None,
    tasklist: str | None = None,
    clear_due: bool = False,
    clear_notes: bool = False,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Patch an existing task by ID and return the updated task.

    Use find_tasks() or get_tasks_for_day() first if your agent only knows the
    title and needs the task ID. Status must be "needsAction" or "completed".
    """
    if not task_id or not task_id.strip():
        raise ValueError("task_id is required")
    if clear_due and due is not None:
        raise ValueError("Use either due or clear_due, not both")
    if clear_notes and notes is not None:
        raise ValueError("Use either notes or clear_notes, not both")
    if status is not None and status not in {"needsAction", "completed"}:
        raise ValueError('status must be "needsAction" or "completed"')

    body: dict[str, Any] = {}
    if title is not None:
        if not title.strip():
            raise ValueError("title cannot be blank")
        body["title"] = title.strip()
    if notes is not None:
        body["notes"] = notes
    if clear_notes:
        body["notes"] = ""
    if due is not None:
        body["due"] = _due_rfc3339(due)
    if clear_due:
        body["due"] = None
    if status is not None:
        body["status"] = status

    if not body:
        raise ValueError("No edits were provided")

    service = connect_google_tasks(credentials_path, token_path)
    tasklist_id = _tasklist_id(tasklist)
    result = service.tasks().patch(tasklist=tasklist_id, task=task_id.strip(), body=body).execute()
    return _simplify_task(result, tasklist_id)


def complete_task(
    task_id: str,
    tasklist: str | None = None,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> dict[str, Any]:
    """Mark a task completed."""
    return edit_task(
        task_id=task_id,
        status="completed",
        tasklist=tasklist,
        credentials_path=credentials_path,
        token_path=token_path,
    )


def reopen_task(
    task_id: str,
    tasklist: str | None = None,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> dict[str, Any]:
    """Mark a completed task as needing action again."""
    return edit_task(
        task_id=task_id,
        status="needsAction",
        tasklist=tasklist,
        credentials_path=credentials_path,
        token_path=token_path,
    )


def move_task(
    task_id: str,
    destination_tasklist: str,
    tasklist: str | None = None,
    parent: str | None = None,
    previous: str | None = None,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Move a task to a different task list.

    Uses the move endpoint's destinationTasklist, so the task keeps its id and
    history. Recreating it elsewhere and deleting the original would lose both.
    """
    if not task_id or not task_id.strip():
        raise ValueError("task_id is required")
    if not destination_tasklist or not destination_tasklist.strip():
        raise ValueError("destination_tasklist is required")

    service = connect_google_tasks(credentials_path, token_path)
    source = _tasklist_id(tasklist)

    move_args: dict[str, Any] = {
        "tasklist": source,
        "task": task_id.strip(),
        "destinationTasklist": destination_tasklist.strip(),
    }
    if parent is not None:
        move_args["parent"] = parent
    if previous is not None:
        move_args["previous"] = previous

    result = service.tasks().move(**move_args).execute()

    return _simplify_task(result, destination_tasklist.strip())


def get_tasks_for_day(
    day: str | date | datetime | None = None,
    tasklist: str | None = None,
    include_completed: bool = False,
    include_assigned: bool = True,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Return tasks due on a specific day. Defaults to today's local date.

    Pass tasklist="all" to search every task list. Google Tasks stores due dates
    as dates only, so due times are not available through the API.
    """
    service = connect_google_tasks(credentials_path, token_path)
    due_min, due_max = _day_bounds_rfc3339(day)

    if tasklist == "all":
        results: list[dict[str, Any]] = []
        for task_list in _list_task_lists(service):
            tasklist_id = task_list["id"]
            tasklist_title = task_list["title"]
            tasks = _list_tasks(
                service=service,
                tasklist=tasklist_id,
                due_min=due_min,
                due_max=due_max,
                include_completed=include_completed,
                include_assigned=include_assigned,
            )
            results.extend(_simplify_task(task, tasklist_id, tasklist_title) for task in tasks)
        return results

    tasklist_id = _tasklist_id(tasklist)
    return [
        _simplify_task(task, tasklist_id)
        for task in _list_tasks(
            service=service,
            tasklist=tasklist_id,
            due_min=due_min,
            due_max=due_max,
            include_completed=include_completed,
            include_assigned=include_assigned,
        )
    ]


def get_day_review(
    day: str | date | datetime | None = None,
    tasklist: str | None = "all",
    max_open: int = 20,
    max_completed: int = 20,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Return what was completed on a day plus everything still outstanding.

    This is the shape a coach needs for a check-in: what got done, and what is
    still hanging over you. Completed tasks are matched on completion time,
    not due date, so finishing something early or late still counts for the
    day you actually did it.

    Both lists are capped, because either can run away: a neglected backlog
    swells the open list, and a day spent clearing one swells the completed
    list. The counts reported are always the true totals, so the model can say
    "you finished 30 things" while only reading the most recent 20.

    Note the caps trim what is *returned*, not what is fetched - every task is
    still paged through, because open_count and overdue_count have to be right.
    """
    service = connect_google_tasks(credentials_path, token_path)
    selected_day = _date_from_value(day)
    start, end = _day_bounds_rfc3339(selected_day)

    if tasklist == "all":
        task_lists = _list_task_lists(service)
    else:
        task_lists = [{"id": _tasklist_id(tasklist), "title": None}]

    completed: list[dict[str, Any]] = []
    still_open: list[dict[str, Any]] = []

    for task_list in task_lists:
        tasklist_id = task_list["id"]
        tasklist_title = task_list.get("title")

        for task in _list_tasks(
            service=service,
            tasklist=tasklist_id,
            completed_min=start,
            completed_max=end,
            include_completed=True,
        ):
            if task.get("status") == "completed":
                # Keep the raw completion timestamp for sorting; _compact_task
                # drops it, and without it "most recent" would be arbitrary.
                completed.append(
                    (task.get("completed") or "", _compact_task(task, tasklist_id, tasklist_title))
                )

        for task in _list_tasks(
            service=service,
            tasklist=tasklist_id,
            include_completed=False,
        ):
            if task.get("status") != "completed":
                still_open.append(_compact_task(task, tasklist_id, tasklist_title))

    overdue = [
        task
        for task in still_open
        if task.get("due") and _date_from_value(task["due"]) < selected_day
    ]

    # Overdue work is the part worth talking about, so it goes to the front of
    # the truncated list rather than being cut off at the bottom of it.
    overdue_ids = {task["id"] for task in overdue}
    still_open.sort(key=lambda task: task["id"] not in overdue_ids)

    # Most recently finished first: if the list is trimmed, what survives is
    # what they just did, which is what a check-in is actually about.
    completed.sort(key=lambda pair: pair[0], reverse=True)
    completed_tasks = [task for _, task in completed]

    return {
        "day": selected_day.isoformat(),
        "completed_count": len(completed_tasks),
        "open_count": len(still_open),
        "overdue_count": len(overdue),
        "completed": completed_tasks[:max_completed],
        "completed_truncated": len(completed_tasks) > max_completed,
        "open": still_open[:max_open],
        "open_truncated": len(still_open) > max_open,
        "has_no_tasks_at_all": not completed_tasks and not still_open,
        # Returned here rather than behind a separate tool: the model needs
        # list ids to file or move anything, and it always calls this first.
        "task_lists": [
            {"id": task_list["id"], "title": task_list.get("title")}
            for task_list in task_lists
        ],
    }


def find_tasks(
    text: str,
    tasklist: str | None = "all",
    include_completed: bool = True,
    include_assigned: bool = True,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Search task titles and notes locally.

    Google Tasks has no full-text search endpoint, so this lists tasks and
    filters them in Python. Use the returned IDs with edit_task().
    """
    if not text or not text.strip():
        raise ValueError("text is required")

    service = connect_google_tasks(credentials_path, token_path)
    needle = text.casefold().strip()
    results: list[dict[str, Any]] = []

    if tasklist == "all":
        task_lists = _list_task_lists(service)
    else:
        task_lists = [{"id": _tasklist_id(tasklist), "title": None}]

    for task_list in task_lists:
        tasklist_id = task_list["id"]
        tasklist_title = task_list.get("title")
        for task in _list_tasks(
            service=service,
            tasklist=tasklist_id,
            include_completed=include_completed,
            include_assigned=include_assigned,
        ):
            haystack = f"{task.get('title', '')}\n{task.get('notes', '')}".casefold()
            if needle in haystack:
                results.append(_simplify_task(task, tasklist_id, tasklist_title))

    return results


def _list_tasks(
    service: Any,
    tasklist: str,
    due_min: str | None = None,
    due_max: str | None = None,
    completed_min: str | None = None,
    completed_max: str | None = None,
    include_completed: bool = True,
    include_assigned: bool = True,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = None

    while True:
        list_args: dict[str, Any] = {
            "tasklist": tasklist,
            "maxResults": 100,
            "showCompleted": include_completed,
            "showDeleted": False,
            # Google flags completed tasks as hidden, so asking for completed
            # tasks while leaving showHidden False silently returns none of
            # them. The two flags have to move together.
            "showHidden": include_completed,
            "showAssigned": include_assigned,
        }
        if due_min is not None:
            list_args["dueMin"] = due_min
        if due_max is not None:
            list_args["dueMax"] = due_max
        if completed_min is not None:
            list_args["completedMin"] = completed_min
        if completed_max is not None:
            list_args["completedMax"] = completed_max
        if page_token:
            list_args["pageToken"] = page_token

        response = service.tasks().list(**list_args).execute()
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return items


def _google_client_imports() -> tuple[Any, Any, Any, Any]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Install Google Tasks dependencies first: " "python -m pip install --upgrade " "google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc

    return Request, Credentials, InstalledAppFlow, build


def _path_from_value_or_env(
    value: str | Path | None,
    env_name: str,
    default: str,
) -> Path:
    return Path(value or os.getenv(env_name, default)).expanduser()


def _tasklist_id(tasklist: str | None) -> str:
    return tasklist or os.getenv("GOOGLE_TASKS_DEFAULT_LIST", DEFAULT_TASKLIST)


def _date_from_value(value: str | date | datetime | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = value.strip()
    if text.lower() == "today":
        return date.today()
    if text.lower() == "tomorrow":
        return date.today() + timedelta(days=1)

    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("day/due must be YYYY-MM-DD, date, or datetime") from exc


def _due_rfc3339(value: str | date | datetime) -> str:
    due_day = _date_from_value(value)
    return f"{due_day.isoformat()}T00:00:00.000Z"


def _day_bounds_rfc3339(value: str | date | datetime | None) -> tuple[str, str]:
    selected_day = _date_from_value(value)
    start = datetime.combine(selected_day, time.min, timezone.utc)
    end = datetime.combine(selected_day, time.max, timezone.utc)
    return _rfc3339(start), _rfc3339(end)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _compact_task(
    task: dict[str, Any],
    tasklist_id: str | None = None,
    tasklist_title: str | None = None,
) -> dict[str, Any]:
    """A task trimmed to what the model can act on.

    Used for list output, where the full shape is the difference between a
    workable prompt and a slow one: web links, positions and timestamps are
    dead weight repeated once per task, and a busy day has dozens.
    """
    notes = task.get("notes") or None

    if notes and len(notes) > 200:
        notes = notes[:200] + "..."

    compact = {
        "id": task.get("id"),
        "title": task.get("title"),
        # Google stores dates as midnight UTC; the time half is never useful.
        "due": (task.get("due") or "")[:10] or None,
        "tasklist_id": tasklist_id,
        "tasklist_title": tasklist_title,
    }

    if notes:
        compact["notes"] = notes

    return compact


def _simplify_task(
    task: dict[str, Any],
    tasklist_id: str | None = None,
    tasklist_title: str | None = None,
) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "notes": task.get("notes"),
        "status": task.get("status"),
        "due": task.get("due"),
        "completed": task.get("completed"),
        "updated": task.get("updated"),
        "parent": task.get("parent"),
        "position": task.get("position"),
        "web_view_link": task.get("webViewLink"),
        "tasklist_id": tasklist_id,
        "tasklist_title": tasklist_title,
    }
