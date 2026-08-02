"""Let an agent edit its own context markdown.

These files ARE the agent's system prompt: _build_context_from_md concatenates
every *.md in the handle's context directory and sends the result with every
single message. That makes self-editing genuinely useful - the agent can keep
notes that outlive any one conversation - and genuinely dangerous:

* An agent that blanks IDENTITY.md loses its personality permanently.
* An agent that appends without restraint makes every future message more
  expensive, and eventually pushes its own instructions out of the window.
* Anything written here persists, so a bad instruction absorbed from a message
  would keep applying long after that conversation.

So writes are bounded rather than trusted: confined to the agent's own
directory, markdown only, size-capped, never empty, and the previous version
is always kept alongside as .bak.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from .tool import Tool

# The whole context is re-sent on every message, so an unbounded file is a
# permanent tax on every future turn, not a one-off cost.
MAX_FILE_CHARS = 10_000


class ContextScopedTool(Tool):
    """Base for tools that edit one handle's context directory.

    The directory is bound when the registry is built, never passed as a tool
    argument: the model must not be able to choose which agent's identity it
    rewrites, and a path in the schema is a path an injected message can aim.
    """

    def __init__(self, context_path: str | Path) -> None:
        self.context_path = Path(context_path).resolve()

    def _resolve(self, filename: str) -> Path:
        """Resolve filename inside the context directory, or refuse."""

        if not filename or not filename.strip():
            raise ValueError("filename is required")

        name = filename.strip()

        if not name.endswith(".md"):
            raise ValueError("only .md files can be edited")

        # Reject separators outright rather than trying to sanitise them, then
        # confirm the resolved path really is inside the directory - the second
        # check is what actually stops '..' and symlink escapes.
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("filename must be a plain name like MEMORY.md")

        target = (self.context_path / name).resolve()

        if target.parent != self.context_path:
            raise ValueError("that file is outside this agent's context directory")

        return target


class ReadContextFile(ContextScopedTool):
    name = "read_context_file"
    description = (
        "Read one of your own context files exactly as stored. Do this before "
        "rewriting one, so you edit the real current text instead of what you "
        "remember of it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "e.g. MEMORY.md, USER.md, IDENTITY.md, BOOTSTRAP.md",
            }
        },
        "required": ["filename"],
    }

    def call(self, filename: str) -> dict[str, Any]:
        target = self._resolve(filename)

        if not target.exists():
            available = sorted(p.name for p in self.context_path.glob("*.md"))
            return {"exists": False, "available": available}

        content = target.read_text(encoding="utf-8")

        return {
            "exists": True,
            "filename": target.name,
            "content": content,
            "chars": len(content),
            "chars_remaining": MAX_FILE_CHARS - len(content),
        }


class Remember(ContextScopedTool):
    name = "remember"
    description = (
        "Append one durable note to MEMORY.md. Use it the moment you learn "
        "something about the user that should still matter next week - how they "
        "work, what keeps failing, what they decided. Prefer this over "
        "update_context_file for adding a fact: appending cannot lose anything "
        "that is already written."
    )
    parameters = {
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": (
                    "One line, specific and self-contained. Do not start it with "
                    "a date - today's date is added for you."
                ),
            }
        },
        "required": ["note"],
    }

    def call(self, note: str) -> dict[str, Any]:
        if not note or not note.strip():
            raise ValueError("note is required")

        # Models tend to date their own notes despite being told not to, which
        # reads as "- (2026-08-02) 2026-08-02: ...". Strip it rather than nag.
        note = _strip_leading_date(note)

        target = self._resolve("MEMORY.md")
        existing = target.read_text(encoding="utf-8") if target.exists() else "MEMORY.md - YOUR MEMORIES/LOGS\n"

        line = f"- ({date.today().isoformat()}) {note.strip()}"
        updated = existing.rstrip("\n") + "\n" + line + "\n"

        if len(updated) > MAX_FILE_CHARS:
            raise ValueError(
                f"MEMORY.md would exceed {MAX_FILE_CHARS} characters. It is sent to you "
                "with every message, so condense it first: read_context_file('MEMORY.md'), "
                "merge the stale notes, then update_context_file with the shorter version."
            )

        _write_with_backup(target, updated)

        return {"remembered": line, "chars": len(updated)}


class UpdateContextFile(ContextScopedTool):
    name = "update_context_file"
    description = (
        "Replace one of your own context files completely. Use this to "
        "restructure or condense - to correct something wrong in USER.md, or to "
        "merge a sprawling MEMORY.md back into something tight. Read the file "
        "first: this overwrites everything, so whatever you leave out is gone "
        "from your future context. The previous version is kept as a .bak."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "e.g. MEMORY.md, USER.md, IDENTITY.md",
            },
            "content": {
                "type": "string",
                "description": "The complete new contents of the file. Not a fragment.",
            },
            "reason": {
                "type": "string",
                "description": "One line on why you are changing it. Kept in the log.",
            },
        },
        "required": ["filename", "content"],
    }

    def call(self, filename: str, content: str, reason: str | None = None) -> dict[str, Any]:
        target = self._resolve(filename)

        if not content or not content.strip():
            # An empty IDENTITY.md is an agent with no personality and no way to
            # reason its way back, so this is refused rather than backed up.
            raise ValueError("content cannot be empty - use a shorter file, not a blank one")

        if len(content) > MAX_FILE_CHARS:
            raise ValueError(
                f"{target.name} would be {len(content)} characters, over the "
                f"{MAX_FILE_CHARS} limit. This text is re-sent with every message, "
                "so make it shorter."
            )

        existed = target.exists()
        _write_with_backup(target, content)

        return {
            "updated": target.name,
            "created": not existed,
            "chars": len(content),
            "reason": reason,
            "backup": f"{target.name}.bak" if existed else None,
        }


def _strip_leading_date(note: str) -> str:
    """Drop a leading 'YYYY-MM-DD' (and any ':', '-' or brackets around it)."""

    cleaned = re.sub(r"^[\(\[]?\s*\d{4}-\d{2}-\d{2}\s*[\)\]]?\s*[:\-–]?\s*", "", note.strip())

    # If the note was nothing but a date, keep the original rather than return
    # an empty string that would then fail validation confusingly.
    return cleaned or note.strip()


def _write_with_backup(target: Path, content: str) -> None:
    """Keep the previous version, then swap the new one in atomically."""

    if target.exists():
        backup = target.with_suffix(target.suffix + ".bak")
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")

    temp_path = target.with_suffix(target.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(target)


def context_tools(context_path: str | Path) -> list[Tool]:
    return [
        ReadContextFile(context_path),
        Remember(context_path),
        UpdateContextFile(context_path),
    ]
