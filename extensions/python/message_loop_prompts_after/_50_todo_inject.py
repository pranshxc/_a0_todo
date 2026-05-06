"""
Injects a compact read-only todo status into extras_persistent each loop.
NO rules about calling start/complete/check_done — those are automatic.
Agent only needs to know: what tasks exist, how many done, any blocked.
"""
import os
import json
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")
ICONS = {"queued": "⏳", "started": "🔄", "completed": "✅", "blocked": "🚫"}


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
        except Exception:
            return

        tasks = data.get("tasks", [])
        if not tasks:
            return

        done  = sum(1 for t in tasks if t["status"] == "completed")
        total = len(tasks)
        incomplete = [t for t in tasks if t["status"] != "completed"]

        if done == total:
            loop_data.extras_persistent["todo_list"] = (
                f"✅ All {total} tasks completed. Give the final response."
            )
            return

        # Compact XML block — only show incomplete tasks to save tokens
        lines = [f'<todo done="{done}/{total}">']
        blocked_tasks = []
        for t in incomplete:
            icon = ICONS.get(t["status"], "?")
            bl = f' [BLOCKED: {t["blocked_reason"]}]' if t.get("blocked_reason") else ""
            lines.append(f"  {icon} [{t['id']}] {t['title']}{bl}")
            if t["status"] == "blocked":
                blocked_tasks.append(t["id"])
        lines.append("</todo>")

        note = ""
        if blocked_tasks:
            ids = ", ".join(str(i) for i in blocked_tasks)
            note = f"\n⚠️ Tasks {ids} are blocked. Use todo_manager(action=unblock) if resolved."

        loop_data.extras_persistent["todo_list"] = (
            f"## Work Order ({len(incomplete)} remaining){note}\n"
            "Track automatically — focus on the work, not on calling todo_manager.\n\n"
            + "\n".join(lines)
        )
