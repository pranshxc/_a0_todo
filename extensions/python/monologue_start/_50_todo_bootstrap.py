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
        if loop_data.extras_persistent.get("_planner_blocking") == "true":
            return

        chat_id = str(
            getattr(agent, "chat_id", None)
            or getattr(agent.context, "id", None)
            or "default"
        )

        os.makedirs(TODO_DIR, exist_ok=True)
        todo_path = os.path.join(TODO_DIR, f"{chat_id}.json")

        if os.path.exists(todo_path):
            return  # already exists, inject extension handles display

        already = agent.get_data("_todo_bootstrapped") or False
        if already:
            return
        agent.set_data("_todo_bootstrapped", True)

        loop_data.extras_persistent["todo_bootstrap"] = (
            "## First Step\n"
            "Call `todo_manager(action=create, tasks=[...])` with 5-30 concise task titles. "
            "After that, just do the work — never call todo_manager for start/complete updates. "
            "The system tracks progress automatically from your work output."
        )
