"""Tool package.

Without this file `from tools import GoogleTasks` binds the *module*, not the
class inside it, which is why the old TOOL_LIST held modules and blew up with
"'module' object is not callable" the moment anything tried to use it.
"""

from .tool import Tool, ToolRegistry


def build_registry(
    tool_names: list[str] | None,
    chat_id: int | str,
    context_path: str | None = None,
) -> ToolRegistry:
    """Assemble the tools one handle is allowed to use.

    Names come from handles.json, so a handle only gets what it is granted:
    the default agent has no reason to be able to write goals or rewrite its
    own identity. Unknown names raise rather than being skipped - a typo
    silently costing the agent a capability is much harder to notice than a
    startup error.
    """

    from .context_files import context_tools
    from .goals import goal_tools
    from .GoogleTasks import google_task_tools

    tools = google_task_tools() + goal_tools(chat_id)

    if context_path:
        tools += context_tools(context_path)

    available = {tool.name: tool for tool in tools}

    groups = {
        "google_tasks": ["list_tasks", "create_task", "complete_task"],
        "goals": ["list_goals", "add_goal", "update_goal", "log_checkin"],
        "context": ["read_context_file", "remember", "update_context_file"],
    }

    selected: list[Tool] = []

    for name in tool_names or []:
        for expanded in groups.get(name, [name]):
            tool = available.get(expanded)

            if tool is None:
                raise ValueError(
                    f"Unknown tool '{expanded}' in handles.json. "
                    f"Available: {', '.join(sorted(available))} "
                    f"or groups: {', '.join(groups)}"
                )

            selected.append(tool)

    return ToolRegistry(selected)


__all__ = ["Tool", "ToolRegistry", "build_registry"]
