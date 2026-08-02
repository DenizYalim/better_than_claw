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
        "sitting. Pass tasklist_id to file it on the right list - list_tasks "
        "returns the available lists and their ids."
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
            "tasklist_id": {
                "type": "string",
                "description": (
                    "Which list to put it on, from task_lists in list_tasks. "
                    "Omit only if the user has expressed no preference."
                ),
            },
        },
        "required": ["title"],
    }

    def call(
        self,
        title: str,
        notes: str | None = None,
        due: str | None = None,
        tasklist_id: str | None = None,
    ) -> Any:
        return _guard(api.add_task, title=title, notes=notes, due=due, tasklist=tasklist_id)


class UpdateTask(Tool):
    name = "update_task"
    description = (
        "Change an existing task: rename it, set or clear its due date, edit "
        "its notes, or reopen a completed one. Get task_id and tasklist_id "
        "from list_tasks. Pass only the fields you are changing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task id from list_tasks."},
            "tasklist_id": {
                "type": "string",
                "description": "The task's tasklist_id from list_tasks. Needed unless it is on the default list.",
            },
            "title": {"type": "string", "description": "New title."},
            "notes": {"type": "string", "description": "New notes, replacing any existing ones."},
            "due": {
                "type": "string",
                "description": "New due date: YYYY-MM-DD, 'today' or 'tomorrow'.",
            },
            "clear_due": {
                "type": "boolean",
                "description": "Remove the due date entirely. Do not combine with due.",
            },
            "reopen": {
                "type": "boolean",
                "description": "Mark a completed task as needing action again.",
            },
        },
        "required": ["task_id"],
    }

    def call(
        self,
        task_id: str,
        tasklist_id: str | None = None,
        title: str | None = None,
        notes: str | None = None,
        due: str | None = None,
        clear_due: bool = False,
        reopen: bool = False,
    ) -> Any:
        return _guard(
            api.edit_task,
            task_id=task_id,
            title=title,
            notes=notes,
            due=due,
            clear_due=clear_due,
            status="needsAction" if reopen else None,
            tasklist=tasklist_id,
        )


class MoveTask(Tool):
    name = "move_task"
    description = (
        "Move a task to a different list, e.g. pushing something from 'Yarın' "
        "to 'Backlog'. The task keeps its id, notes and due date. Get both ids "
        "from list_tasks."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task id from list_tasks."},
            "destination_tasklist_id": {
                "type": "string",
                "description": "Id of the list to move it to, from task_lists in list_tasks.",
            },
            "tasklist_id": {
                "type": "string",
                "description": "The list it is currently on. Needed unless it is the default list.",
            },
        },
        "required": ["task_id", "destination_tasklist_id"],
    }

    def call(
        self,
        task_id: str,
        destination_tasklist_id: str,
        tasklist_id: str | None = None,
    ) -> Any:
        return _guard(
            api.move_task,
            task_id=task_id,
            destination_tasklist=destination_tasklist_id,
            tasklist=tasklist_id,
        )


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
    return [ListTasks(), CreateTask(), CompleteTask(), UpdateTask(), MoveTask()]
