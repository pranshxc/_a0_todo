import os
import json
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")

STATUS_ICONS = {
    "queued":    "⏳",
    "started":   "🔄",
    "completed": "✅",
    "blocked":   "🚫",
}


def _render(data: dict) -> str:
    tasks = data.get("tasks", [])
    if not tasks:
        return ""
    done  = sum(1 for t in tasks if t["status"] == "completed")
    active = next((t for t in tasks if t["status"] == "started"), None)
    lines = [
        "<todo_list>",
        f"  progress: {done}/{len(tasks)} completed",
    ]
    if active:
        lines.append(f"  active_task: [{active['id']}] {active['title']}")
    for t in tasks:
        icon = STATUS_ICONS.get(t["status"], "❓")
        bl = f"  ← BLOCKED: {t['blocked_reason']}" if t.get("blocked_reason") else ""
        lines.append(f"    {icon} [{t['id']:>2}] {t['title']} ({t['status']}){bl}")
    lines.append("</todo_list>")
    return "\n".join(lines)


class TodoInject(Extension):
    """After prompts are assembled: inject the current todo list into extras_persistent
    so it appears in the system prompt alongside memory on every loop iteration."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        agent = self.agent
        if not agent:
            return

        chat_id = str(
            getattr(agent, "chat_id", None)
            or getattr(agent.context, "id", None)
            or "default"
        )

        todo_path = os.path.join(TODO_DIR, f"{chat_id}.json")
        if not os.path.exists(todo_path):
            return

        try:
            with open(todo_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        rendered = _render(data)
        if not rendered:
            return

        loop_data.extras_persistent["todo_list"] = (
            "## 📋 Your Work Order (Todo List)\n"
            "Work tasks in order. Mark each task with `todo_manager` before and after working on it. "
            "Never re-mark a completed task. If blocked, use action=block with a reason.\n\n"
            + rendered
        )
