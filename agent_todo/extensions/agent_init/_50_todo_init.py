import os
import json
from helpers.extension import Extension

TODO_DIR = os.path.join("work", "todo")


class TodoInit(Extension):
    """On agent init: if no todo list exists for this chat, instruct the agent to create one."""

    async def execute(self, **kwargs):
        agent = self.agent
        chat_id = str(getattr(agent, "chat_id", None) or agent.context.id)

        os.makedirs(TODO_DIR, exist_ok=True)
        todo_path = os.path.join(TODO_DIR, f"{chat_id}.json")

        if os.path.exists(todo_path):
            # already initialised for this chat — nothing to do
            return

        # Signal to the agent that it should create a todo list at the start of this chat.
        # We store the flag in agent.data so the prompt injector can render the bootstrap nudge.
        agent.data["todo_needs_bootstrap"] = True
