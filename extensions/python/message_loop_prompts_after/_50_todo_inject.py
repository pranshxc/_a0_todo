"""
message_loop_prompts_after -> _50_todo_inject

Injects current todo state into extras_persistent ONLY when relevant:
 - No list: nothing injected (bootstrap handles it)
 - List exists, incomplete: compact status block injected (no walls of rules)
 - List exists, all done: minimal "all done" note injected

Rules are SHORT and non-repetitive. The utility model tracker handles updates,
so the main LLM doesn't need threatening rule walls to stay on track.
"""
import os
import json
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")
STATUS_ICONS = {"queued": "⏳", "started": "🔄", "completed": "✅", "blocked": "🚫"}


def _render_compact(data: dict) -> str:
    """Compact single-line-per-task format for the extras block."""
    tasks = data.get("tasks", [])
    if not tasks:
        return ""
    done  = sum(1 for t in tasks if t["status"] == "completed")
    lines = [f"<todo progress=\"{done}/{len(tasks)}\">"]  
    for t in tasks:
        icon = STATUS_ICONS.get(t["status"], "❓")
        bl   = f" [BLOCKED: {t['blocked_reason']}]" if t.get("blocked_reason") else ""
        lines.append(f"  {icon} [{t['id']}] {t['title']}{bl}")
    lines.append("</todo>")
    return "\n".join(lines)


class TodoInject(Extension):

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

        tasks      = data.get("tasks", [])
        incomplete = [t for t in tasks if t["status"] != "completed"]
        all_done   = len(tasks) > 0 and len(incomplete) == 0

        rendered = _render_compact(data)
        if not rendered:
            return

        if all_done:
            loop_data.extras_persistent["todo_list"] = (
                "✅ All tasks completed. You may now give the final response to the user."
            )
        else:
            blocked = [t for t in incomplete if t["status"] == "blocked"]
            blocked_note = ""
            if blocked:
                blocked_note = (
                    f"\n⚠️ {len(blocked)} task(s) blocked — "
                    "use `todo_manager(action=unblock, task_id=N)` if the blocker is resolved."
                )
            loop_data.extras_persistent["todo_list"] = (
                f"## 📋 Work Order ({len(incomplete)} remaining)\n"
                f"Automatic tracking is active. Focus on the work.{blocked_note}\n\n"
                + rendered
            )
