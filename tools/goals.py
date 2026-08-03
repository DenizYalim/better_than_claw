"""Goal and check-in store, plus the tools the coach uses to work with it.

Goals live in goals.json keyed by Telegram chat id, so two chats never see
each other's goals. Structure is deliberate: a goal without success criteria
cannot be assessed, and a coach that cannot assess cannot coach. add_goal
therefore refuses vague entries rather than storing wishes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ._store import read_json, update_json
from .tool import Tool

BASE_DIR = Path(__file__).resolve().parent.parent
GOALS_PATH = BASE_DIR / "goals.json"

KINDS = ("daily", "longterm")
STATUSES = ("active", "done", "dropped", "paused")

# Enough history for the coach to spot a streak or a slump without pulling the
# user's whole life into every prompt.
RECENT_CHECKINS = 14


def _chat(data: dict[str, Any], chat_id: int | str) -> dict[str, Any]:
    key = str(chat_id)
    entry = data.setdefault(key, {"goals": [], "checkins": []})
    entry.setdefault("goals", [])
    entry.setdefault("checkins", [])
    return entry


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_date(value: str) -> str:
    """Accept the same date words the task tools accept.

    list_tasks and create_task take 'today'/'tomorrow', so the model reasonably
    passes them here too. Bare date.fromisoformat rejects those, and the model
    just retries the same word and fails again.
    """

    text = (value or "").strip().casefold()

    if text == "today":
        return date.today().isoformat()
    if text == "tomorrow":
        return (date.today() + timedelta(days=1)).isoformat()

    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(
            f"target_date must be YYYY-MM-DD, 'today' or 'tomorrow', got '{value}'"
        ) from None


def _next_goal_id(goals: list[dict[str, Any]]) -> str:
    used = {goal.get("id") for goal in goals}
    index = 1
    while f"g{index}" in used:
        index += 1
    return f"g{index}"


class ChatScopedTool(Tool):
    """Base for tools that act on one chat's data.

    The chat id is bound when the registry is built rather than passed as a
    tool argument: the model has no business choosing whose goals it edits,
    and leaving it in the schema would let a prompt injection retarget it.
    """

    def __init__(self, chat_id: int | str) -> None:
        self.chat_id = chat_id


class ListGoals(ChatScopedTool):
    name = "list_goals"
    description = (
        "List the user's goals with their progress notes, plus recent daily "
        "check-ins. Call this before giving advice so your suggestions are "
        "grounded in what they are actually working towards."
    )
    parameters = {
        "type": "object",
        "properties": {
            "include_finished": {
                "type": "boolean",
                "description": "Include goals that are done or dropped. Default false.",
            }
        },
    }

    def call(self, include_finished: bool = False) -> dict[str, Any]:
        entry = _chat(read_json(GOALS_PATH), self.chat_id)

        goals = entry["goals"]
        if not include_finished:
            goals = [g for g in goals if g.get("status") in ("active", "paused")]

        return {
            "goals": goals,
            "goal_count": len(goals),
            "recent_checkins": entry["checkins"][-RECENT_CHECKINS:],
            "has_no_goals": not goals,
        }


class AddGoal(ChatScopedTool):
    name = "add_goal"
    description = (
        "Record a new goal. Only call this once the goal is concrete: it needs "
        "a measurable success criterion and, for long-term goals, a target "
        "date. If the user's goal is vague ('get fit', 'read more'), ask them "
        "the questions that would make it measurable first, then save it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short, specific goal. 'Run 5k under 30min', not 'get fit'.",
            },
            "kind": {
                "type": "string",
                "enum": list(KINDS),
                "description": "'daily' for a recurring habit, 'longterm' for an outcome.",
            },
            "success_criteria": {
                "type": "string",
                "description": "How we will know it is achieved. Must be checkable.",
            },
            "target_date": {
                "type": "string",
                "description": "YYYY-MM-DD. Required for longterm goals.",
            },
            "why": {
                "type": "string",
                "description": "The user's reason for it, in their words. Useful when motivation dips.",
            },
        },
        "required": ["title", "kind", "success_criteria"],
    }

    def call(
        self,
        title: str,
        kind: str,
        success_criteria: str,
        target_date: str | None = None,
        why: str | None = None,
    ) -> dict[str, Any]:
        if not title.strip():
            raise ValueError("title is required")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if not success_criteria.strip():
            raise ValueError("success_criteria is required - a goal you cannot check is not a goal")
        if kind == "longterm" and not target_date:
            raise ValueError("longterm goals need a target_date (YYYY-MM-DD)")
        if target_date:
            target_date = _parse_date(target_date)

        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            entry = _chat(data, self.chat_id)

            # The id is allocated inside the lock: two processes adding a goal
            # at once would otherwise both read the same list and both pick g2.
            goal = {
                "id": _next_goal_id(entry["goals"]),
                "title": title.strip(),
                "kind": kind,
                "success_criteria": success_criteria.strip(),
                "target_date": target_date,
                "why": (why or "").strip() or None,
                "status": "active",
                "created": _today(),
                "progress": [],
            }

            entry["goals"].append(goal)
            return goal

        return {"added": update_json(GOALS_PATH, mutate)}


class UpdateGoal(ChatScopedTool):
    name = "update_goal"
    description = (
        "Record progress on a goal, or change its status. Use this whenever "
        "the user reports doing something that bears on a goal, so the history "
        "builds up. Get goal_id from list_goals."
    )
    parameters = {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Goal id from list_goals, e.g. 'g2'."},
            "progress_note": {
                "type": "string",
                "description": "What happened, in one line. Dated automatically.",
            },
            "status": {
                "type": "string",
                "enum": list(STATUSES),
                "description": "Only pass this when the status actually changes.",
            },
            "target_date": {"type": "string", "description": "New target date, YYYY-MM-DD."},
        },
        "required": ["goal_id"],
    }

    def call(
        self,
        goal_id: str,
        progress_note: str | None = None,
        status: str | None = None,
        target_date: str | None = None,
    ) -> dict[str, Any]:
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if target_date:
            target_date = _parse_date(target_date)
        if progress_note is None and status is None and target_date is None:
            raise ValueError("nothing to update")

        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            entry = _chat(data, self.chat_id)

            for goal in entry["goals"]:
                if goal.get("id") == goal_id:
                    if progress_note:
                        goal.setdefault("progress", []).append(
                            {"date": _today(), "note": progress_note.strip()}
                        )
                    if status:
                        goal["status"] = status
                    if target_date:
                        goal["target_date"] = target_date

                    return goal

            available = [g.get("id") for g in entry["goals"]]
            raise KeyError(f"No goal {goal_id}. Existing ids: {available or 'none'}")

        return {"updated": update_json(GOALS_PATH, mutate)}


class LogCheckin(ChatScopedTool):
    name = "log_checkin"
    description = (
        "Save a dated summary of what the user DID today. Call this only after "
        "they have described their day or reported progress, and at most once "
        "per conversation. Do NOT call it when they ask a question, state a "
        "preference, or give an instruction: there is nothing to record about a "
        "day you have not been told about, and every needless entry is re-sent "
        "to you on every later message."
    )
    parameters = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Neutral factual summary of the day. No advice here.",
            },
            "mood": {
                "type": "string",
                "description": "Optional read on how they seemed: 'motivated', 'flat', 'stressed'.",
            },
        },
        "required": ["summary"],
    }

    def call(self, summary: str, mood: str | None = None) -> dict[str, Any]:
        if not summary.strip():
            raise ValueError("summary is required")

        checkin = {
            "date": _today(),
            "at": _now(),
            "summary": summary.strip(),
            "mood": (mood or "").strip() or None,
        }

        def mutate(data: dict[str, Any]) -> None:
            _chat(data, self.chat_id)["checkins"].append(checkin)

        update_json(GOALS_PATH, mutate)

        return {"logged": checkin}


def goal_tools(chat_id: int | str) -> list[Tool]:
    return [
        ListGoals(chat_id),
        AddGoal(chat_id),
        UpdateGoal(chat_id),
        LogCheckin(chat_id),
    ]
