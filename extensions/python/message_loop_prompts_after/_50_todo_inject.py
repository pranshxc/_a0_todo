"""
extensions/python/message_loop_prompts_after/_50_todo_inject.py

Active inject file loaded by Agent Zero.
Minimal format: completed count + upcoming-3 titles only.
No queued/blocked/started ID lists — those bloat tokens without adding signal.

Output format:
  ## Work Order (37 remaining)
  <todo 1/38 done (2%)>
    ✅ completed : [1]
  </todo>
  upcoming (next 3): [2] Title | [3] Title | [4] Title
"""
import os
import json
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")

_TARGET  = int(os.environ.get("CTX_GUARD_TARGET_TOKENS", "40000"))
_BUFFER  = int(os.environ.get("CTX_GUARD_BUFFER_TOKENS", "10000"))
_TRIGGER = _TARGET + _BUFFER
_WARN_70 = int(_TRIGGER * 0.70)
_WARN_90 = int(_TRIGGER * 0.90)


def _upcoming_3(tasks: list) -> str:
    queued = [t for t in tasks if t["status"] == "queued"]
    if not queued:
        return ""
    parts = [f"[{t['id']}] {t['title']}" for t in queued[:3]]
    return "upcoming (next 3): " + " | ".join(parts)


def _get_tokens(agent) -> int:
    try:
        t = agent.history.get_tokens()
        if t and t > 0:
            return t
    except Exception:
        pass
    try:
        return agent.context.data.get("_ctxguard_last_tokens", 0)
    except Exception:
        return 0


def _compaction_hint(tokens: int) -> str:
    if tokens <= 0 or tokens < _WARN_70:
        return ""
    pct = int(100 * tokens / _TRIGGER)
    if tokens >= _WARN_90:
        return (
            f"[COMPACTION HINT ⚠️] context_at_{pct}%_capacity — "
            "URGENT: write critical state to session notes NOW."
        )
    return f"[COMPACTION HINT] context_at_{pct}%_capacity — consider saving key notes."


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

        if done == total:
            loop_data.extras_persistent["todo_list"] = (
                f"✅ All {total} tasks completed. Give the final response."
            )
            return

        completed_ids = [t["id"] for t in tasks if t["status"] == "completed"]
        blocked_ids   = [t["id"] for t in tasks if t["status"] == "blocked"]
        pct = f"{100 * done // total}%"

        lines = [f"<todo {done}/{total} done ({pct})>"]
        if completed_ids:
            lines.append(f"  ✅ completed : {completed_ids}")
        lines.append("</todo>")

        upcoming = _upcoming_3(tasks)
        if upcoming:
            lines.append(upcoming)

        note = ""
        if blocked_ids:
            note = f"\n⚠️ Tasks {blocked_ids} blocked. Use todo_manager(action=unblock) if resolved."

        remaining = total - done
        body = (
            f"## Work Order ({remaining} remaining){note}\n\n"
            + "\n".join(lines)
        )

        hint = _compaction_hint(_get_tokens(agent))
        if hint:
            body += f"\n\n{hint}"

        loop_data.extras_persistent["todo_list"] = body
