# REMOVED in v4 - tracker moved to response_stream_end which fires
# after LLM text is complete (agent's intention is in text, not tool results).
# This file is kept as a placeholder to prevent old cached version from running.
# It will be ignored by A0 since the class does nothing.
from helpers.extension import Extension
from agent import LoopData

class TodoAutoTracker(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        pass  # moved to response_stream_end/_55_todo_auto_tracker.py
