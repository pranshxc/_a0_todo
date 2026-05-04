import os
import json
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")


class TodoBootstrap(Extension):
    """At the start of each monologue: if no todo exists for this chat, inject a
    bootstrap instruction into extras_persistent so the agent creates one first.

    Respects _a0_planner: if the planner is blocking (plan not yet approved),
    suppress this bootstrap entirely so the agent doesn't skip the planning step.
    """

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

        # Only inject bootstrap when no list exists yet AND not already done this session
        already_bootstrapped = agent.get_data("_todo_bootstrapped") or False
        if os.path.exists(todo_path) or already_bootstrapped:
            return

        # ── Planner gate ────────────────────────────────────────────────────────
        # If _a0_planner is active and blocking (plan not yet approved),
        # do NOT inject the todo bootstrap — the planner intercept takes priority.
        if loop_data.extras_persistent.get("_planner_blocking") == "true":
            return
        # ────────────────────────────────────────────────────────────────────────

        agent.set_data("_todo_bootstrapped", True)

        loop_data.extras_persistent["todo_bootstrap"] = (
            "## ⚡ Todo List Required\n"
            "No todo list exists for this chat yet. "
            "Your VERY FIRST action MUST be calling `todo_manager` with `action=create` "
            "and a `tasks` array of 10–50 concise task titles that represent the full "
            "work plan for this conversation. "
            "Do NOT respond to the user before creating the todo list."
        )
