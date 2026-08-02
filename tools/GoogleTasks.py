"""Google Tasks exposed to the model as three plain functions.

The module underneath (__google_tasks.py) has eight public functions, but the
coach only needs to see the day, add work, and close work. Every extra tool is
another thing for a small model to pick wrongly.

Nothing here opens a browser: if there is no token these return a readable
"not connected" result instead, so a missing setup step degrades into an
answer the model can relay rather than a frozen bot.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import __google_tasks as api
from .tool import Tool

NOT_CONNECTED = {
    "connected": False,
    "message": (
        "Google Tasks is not connected yet. Tell the user to run "
        "'python setup_google.py' once in the project folder."
    ),
}


def _guard(fn, *args, **kwargs) -> Any:
    """Turn setup problems into results the model can explain, not exceptions."""

    try:
        return fn(*args, **kwargs)
    except api.GoogleTasksNotConnected:
        return NOT_CONNECTED
    except FileNotFoundError as exc:
        return {"connected": False, "message": str(exc)}
    except RuntimeError as exc:
        # Missing google client libraries land here.
        return {"connected": False, "message": str(exc)}


class ListTasks(Tool):
    name = "list_tasks"
    description = (
        "Get the user's Google Tasks for a day: what they completed that day, "
        "and everything still open, including what is overdue. This is the "
        "first thing to call for a check-in. Defaults to today."
    )
    parameters = {
        "type": "object",
        "properties": {
            "day": {
                "type": "string",
                "description": "YYYY-MM-DD, 'today', or 'yesterday'. Defaults to today.",
            }
        },
    }

    def call(self, day: str | None = None) -> Any:
        if day == "yesterday":
            day = (date.today() - timedelta(days=1)).isoformat()

        return _guard(api.get_day_review, day=day, tasklist="all")


class CreateTask(Tool):
    name = "create_task"
    description = (
        "Add a task to the user's Google Tasks. Use this when they agree to do "
        "something concrete, or when you propose a next step and they accept "
        "it. Prefer small, unambiguous titles that can be ticked off in one "
        "sitting."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short actionable title."},
            "notes": {"type": "string", "description": "Optional detail or context."},
            "due": {
                "type": "string",
                "description": "YYYY-MM-DD, 'today', or 'tomorrow'. Google stores the date only.",
            },
        },
        "required": ["title"],
    }

    def call(self, title: str, notes: str | None = None, due: str | None = None) -> Any:
        return _guard(api.add_task, title=title, notes=notes, due=due)


class CompleteTask(Tool):
    name = "complete_task"
    description = (
        "Mark a Google Task as done. Get task_id from list_tasks. Only call "
        "this when the user says they finished it - never assume."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task id from list_tasks."},
            "tasklist_id": {
                "type": "string",
                "description": (
                    "The task's tasklist_id from list_tasks. Needed when it is "
                    "not on the default list."
                ),
            },
        },
        "required": ["task_id"],
    }

    def call(self, task_id: str, tasklist_id: str | None = None) -> Any:
        return _guard(api.complete_task, task_id=task_id, tasklist=tasklist_id)


def google_task_tools() -> list[Tool]:
    return [ListTasks(), CreateTask(), CompleteTask()]
