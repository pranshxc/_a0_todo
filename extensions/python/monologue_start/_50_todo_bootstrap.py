"""
monologue_start -> _50_todo_bootstrap

At the start of each user turn:
 - If no todo list exists: inject a one-time instruction for the agent to create one.
 - If a list exists: inject a COMPACT status summary (not full rules) so the agent
   has context without being overwhelmed with strict rules on every loop iteration.

The full rules + live list are shown only in extras_persistent by the inject extension,
but ONLY when there are actually incomplete tasks. When everything is done, the extras
are suppressed so the agent can give a clean final response.
"""
import os
import json
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")


class TodoBootstrap(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        agent = self.agent
        if not agent:
            return

        chat_id = str(
            getattr(agent, "chat_id", None)
            or getattr(agent.context, "id", None)
            or "default"
        )

        os.makedirs(TODO_DIR, exist_ok=True)
        todo_path = os.path.join(TODO_DIR, f"{chat_id}.json")

        # Planner gate: if planner hasn't approved yet, let planner go first
        if loop_data.extras_persistent.get("_planner_blocking") == "true":
            return

        if os.path.exists(todo_path):
            # List exists — check if all done so we can suppress rules
            try:
                with open(todo_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tasks = data.get("tasks", [])
                done = sum(1 for t in tasks if t["status"] == "completed")
                total = len(tasks)
                if total > 0 and done < total:
                    # Incomplete — just note progress, the inject extension handles rules
                    loop_data.extras_persistent["_todo_progress"] = (
                        f"[Auto-tracker active: {done}/{total} tasks done. "
                        "Progress updates are handled automatically.]"
                    )
            except Exception:
                pass
            return

        # No list yet — bootstrap instruction (fires ONCE)
        already_bootstrapped = agent.get_data("_todo_bootstrapped") or False
        if already_bootstrapped:
            return

        agent.set_data("_todo_bootstrapped", True)
        loop_data.extras_persistent["todo_bootstrap"] = (
            "## ⚡ First Step: Create Your Work Plan\n"
            "Call `todo_manager(action=create, tasks=[...])` with 5–30 concise task titles "
            "covering the full work plan. After that, automatic tracking handles all "
            "start/complete updates — you NEVER need to call todo_manager for status updates. "
            "Just do the work."
        )
