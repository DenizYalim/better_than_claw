"""Tool interface the agent exposes to the model.

One Tool subclass is one callable function, because that is the shape the
OpenAI Responses API wants: a flat list of named functions with JSON Schema
parameters. Grouping several actions behind one Tool would mean the model has
to guess a sub-action from prose, which it does badly.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Tool(ABC):
    #: Function name the model calls. Keep it snake_case and verb-first.
    name: str = ""

    #: Shown to the model. Say what it does AND when to reach for it.
    description: str = ""

    #: JSON Schema for the arguments object.
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    @abstractmethod
    def call(self, **kwargs: Any) -> Any:
        """Run the tool. Return anything JSON-serialisable."""

    def schema(self) -> dict[str, Any]:
        """The tool definition passed to the Responses API."""

        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Holds the tools one handle is allowed to use, and dispatches calls."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}

        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"{type(tool).__name__} has no name")

        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")

        self._tools[tool.name] = tool

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def call(self, name: str, arguments: str | dict[str, Any]) -> str:
        """Run one tool call and return a JSON string for the model.

        Never raises. A tool that blows up has to come back as an error the
        model can read and work around, because an exception here would
        abandon the whole turn and the user would just see a generic failure.
        """

        try:
            if isinstance(arguments, str):
                arguments = json.loads(arguments or "{}")

            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")

            tool = self._tools.get(name)

            if tool is None:
                raise KeyError(f"No such tool: {name}. Available: {', '.join(self.names())}")

            logger.info("tool %s(%s)", name, json.dumps(arguments)[:200])

            result = tool.call(**arguments)

            return json.dumps({"ok": True, "result": result}, default=str)

        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            # The model passed something wrong. Routine, and it gets the error
            # back to retry with - a traceback per bad argument is just noise.
            logger.warning("tool %s rejected: %s", name, exc)

            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

        except Exception as exc:
            # Anything else is our bug, and the traceback is worth having.
            logger.exception("tool %s failed", name)

            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
