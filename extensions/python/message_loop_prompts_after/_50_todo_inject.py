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
    done = sum(1 for t in tasks if t["status"] == "completed")
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
    """After prompts are assembled: inject the current todo list + strict rules
    into extras_persistent so the agent sees them on every loop iteration."""

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

        tasks = data.get("tasks", [])
        incomplete = [t for t in tasks if t["status"] != "completed"]
        all_done = len(incomplete) == 0 and len(tasks) > 0

        # Build strict rules based on current state
        if all_done:
            rules = (
                "All tasks are marked ✅ completed. "
                "You may now call `todo_manager(action=check_done)` to confirm, then give the final response."
            )
        else:
            incomplete_ids = ", ".join(f"[{t['id']}]" for t in incomplete[:10])
            overflow = f" + {len(incomplete)-10} more" if len(incomplete) > 10 else ""
            rules = (
                f"⛔ {len(incomplete)} task(s) still incomplete: {incomplete_ids}{overflow}.\n"
                "STRICT RULES — you MUST follow these or your response will be rejected:\n"
                "1. Work tasks IN ORDER. Do NOT skip tasks or respond early.\n"
                "2. Before starting ANY task: call `todo_manager(action=start, task_id=N)`.\n"
                "3. After finishing ANY task: call `todo_manager(action=complete, task_id=N)` immediately.\n"
                "   If you finished MULTIPLE tasks in one action: call `todo_manager(action=batch_complete, task_ids=[N,M,...])`.\n"
                "   batch_complete verifies each task was in 'started' state — check the report for any failures.\n"
                "4. NEVER call `response` while any task is ⏳ queued, 🔄 started, or 🚫 blocked.\n"
                "5. Before giving your final response: call `todo_manager(action=check_done)` first.\n"
                "   If check_done returns incomplete tasks, finish them before responding.\n"
                "6. Do NOT mark a task completed without having actually done the work."
            )

        loop_data.extras_persistent["todo_list"] = (
            "## 📋 Your Work Order (Todo List)\n"
            + rules + "\n\n"
            + rendered
        )
