import os
import json
from datetime import datetime, timezone
from helpers.extension import Extension

TODO_DIR = os.path.join("work", "todo")

STATUS_ICONS = {
    "queued": "⏳",
    "started": "🔄",
    "completed": "✅",
    "blocked": "🚫",
}


def _render_todo(data: dict) -> str:
    tasks = data.get("tasks", [])
    if not tasks:
        return ""

    total = len(tasks)
    done = sum(1 for t in tasks if t["status"] == "completed")
    active = next((t for t in tasks if t["status"] == "started"), None)

    lines = [
        "<todo_list>",
        f"  Progress: {done}/{total} completed",
    ]
    if active:
        lines.append(f"  Currently active: [{active['id']}] {active['title']}")
    lines.append("  Tasks:")
    for t in tasks:
        icon = STATUS_ICONS.get(t["status"], "❓")
        blocked = f"  ← BLOCKED: {t['blocked_reason']}" if t.get("blocked_reason") else ""
        lines.append(f"    {icon} [{t['id']:>2}] {t['title']} ({t['status']}){blocked}")
    lines.append("</todo_list>")
    return "\n".join(lines)


class TodoInject(Extension):
    """After prompts are built: inject the current chat todo list into the system context."""

    async def execute(self, prompt_msgs=None, **kwargs):
        agent = self.agent
        chat_id = str(getattr(agent, "chat_id", None) or agent.context.id)
        todo_path = os.path.join(TODO_DIR, f"{chat_id}.json")

        needs_bootstrap = agent.data.pop("todo_needs_bootstrap", False)

        if needs_bootstrap:
            bootstrap_msg = (
                "[SYSTEM — agent_todo plugin]\n"
                "No todo list exists for this chat yet.\n"
                "Your FIRST action must be to call the `todo_manager` tool with action='create' "
                "and a 'tasks' array of 10–50 concise task titles that represent the complete "
                "work plan for this conversation.\n"
                "Do NOT respond to the user before creating the todo list."
            )
            if prompt_msgs is not None:
                prompt_msgs.append({"role": "system", "content": bootstrap_msg})
            return

        if not os.path.exists(todo_path):
            return

        try:
            with open(todo_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        rendered = _render_todo(data)
        if not rendered:
            return

        inject_msg = (
            "[SYSTEM — agent_todo plugin]\n"
            "Below is your current work order. Follow tasks in order (queued → started → completed). "
            "Mark each task before and after working on it. Never re-mark a completed task.\n\n"
            + rendered
        )

        if prompt_msgs is not None:
            prompt_msgs.append({"role": "system", "content": inject_msg})
