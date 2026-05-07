"""
extensions/python/message_loop_prompts_after/_50_todo_inject.py

This is the ACTIVE inject file loaded by Agent Zero.
Injects compact todo status + NEXT 3 UPCOMING tasks into every prompt.

Fix: replaced old single-next-task format with upcoming_3 block so agent
always sees next 3 queued tasks without calling todo_manager to peek.
"""
import os
import json
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")
ICONS = {"queued": "⏳", "started": "🔄", "completed": "✅", "blocked": "🚫"}

# Compaction hint thresholds — keep in sync with _a0_context_guard
_TARGET  = int(os.environ.get("CTX_GUARD_TARGET_TOKENS", "40000"))
_BUFFER  = int(os.environ.get("CTX_GUARD_BUFFER_TOKENS", "10000"))
_TRIGGER = _TARGET + _BUFFER   # 50000
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

        # Compact grouped view — IDs only, no full titles (saves tokens)
        groups: dict[str, list] = {"completed": [], "started": [], "queued": [], "blocked": []}
        for t in tasks:
            groups.get(t["status"], groups["queued"]).append(t["id"])

        pct   = f"{100 * done // total}%"
        lines = [f"<todo {done}/{total} done ({pct})>"]
        if groups["completed"]:
            lines.append(f"  ✅ completed : {groups['completed']}")
        if groups["started"]:
            lines.append(f"  🔄 in_progress: {groups['started']}")
        if groups["blocked"]:
            lines.append(f"  🚫 blocked    : {groups['blocked']}")
        if groups["queued"]:
            lines.append(f"  ⏳ queued     : {groups['queued']}")
        lines.append("</todo>")

        # Upcoming 3 — the critical fix
        upcoming = _upcoming_3(tasks)
        if upcoming:
            lines.append(upcoming)

        blocked_ids = groups["blocked"]
        note = ""
        if blocked_ids:
            note = f"\n⚠️ Tasks {blocked_ids} blocked. Use todo_manager(action=unblock) if resolved."

        remaining = total - done
        body = (
            f"## Work Order ({remaining} remaining){note}\n\n"
            + "\n".join(lines)
        )

        # Compaction hint
        hint = _compaction_hint(_get_tokens(agent))
        if hint:
            body += f"\n\n{hint}"

        loop_data.extras_persistent["todo_list"] = body
