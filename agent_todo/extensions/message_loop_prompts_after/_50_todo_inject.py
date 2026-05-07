"""
agent_todo -> message_loop_prompts_after -> _50_todo_inject

Injects a COMPACT todo summary + upcoming-3 hint into every prompt.

Key design choices:
  - Uses COMPACT format (grouped IDs, not full titles) to keep injection small
    and stop the agent from anchoring on the injected list instead of the
    tool response's `upcoming:` field.
  - The upcoming-3 block is injected explicitly so the agent always knows
    the next 3 tasks without calling todo_manager just to peek.
  - Compaction hint (Fix 3C) fires at 70%/90% of trigger threshold.

Threshold defaults MUST stay in sync with _a0_context_guard:
  CTX_GUARD_TARGET_TOKENS  40000
  CTX_GUARD_BUFFER_TOKENS  10000
  Effective trigger        50000
"""
import os
import json
from helpers.extension import Extension

TODO_DIR = os.path.join("work", "todo")

# Thresholds — must match _a0_context_guard _30_token_budget_enforcer defaults
_TARGET   = int(os.environ.get("CTX_GUARD_TARGET_TOKENS",  "40000"))
_BUFFER   = int(os.environ.get("CTX_GUARD_BUFFER_TOKENS",  "10000"))
_TRIGGER  = _TARGET + _BUFFER   # 50000 default
_WARN_70  = int(_TRIGGER * 0.70)  # ~35000
_WARN_90  = int(_TRIGGER * 0.90)  # ~45000

STATUS_ICONS = {
    "queued":    "⏳",
    "started":   "🔄",
    "completed": "✅",
    "blocked":   "🚫",
}


def _render_compact(data: dict) -> str:
    """Compact grouped view — IDs only, keeps injection token-lean."""
    tasks = data.get("tasks", [])
    if not tasks:
        return ""
    groups: dict[str, list] = {"completed": [], "started": [], "queued": [], "blocked": []}
    for t in tasks:
        groups.get(t["status"], groups["queued"]).append(t["id"])
    total = len(tasks)
    done  = len(groups["completed"])
    pct   = f"{100 * done // total}%" if total else "0%"
    lines = [f"<todo_list> {done}/{total} done ({pct})"]
    if groups["completed"]:
        lines.append(f"  ✅ completed : {groups['completed']}")
    if groups["started"]:
        lines.append(f"  🔄 in_progress: {groups['started']}")
    if groups["blocked"]:
        lines.append(f"  🚫 blocked    : {groups['blocked']}")
    if groups["queued"]:
        lines.append(f"  ⏳ queued     : {groups['queued']}")
    lines.append("</todo_list>")
    return "\n".join(lines)


def _upcoming_3(data: dict) -> str:
    """Next 3 queued tasks with titles — injected explicitly so agent never needs
    to call todo_manager just to peek at the queue."""
    queued = [t for t in data.get("tasks", []) if t["status"] == "queued"]
    if not queued:
        return ""
    parts = [f"[{t['id']}] {t['title']}" for t in queued[:3]]
    return "upcoming (next 3): " + " | ".join(parts)


def _get_context_tokens(agent) -> int:
    try:
        t = agent.history.get_tokens()
        if t and t > 0:
            return t
    except Exception:
        pass
    try:
        return agent.context.data.get("_ctxguard_last_tokens", 0)
    except Exception:
        pass
    return 0


def _compaction_hint(tokens: int) -> str:
    if tokens <= 0 or tokens < _WARN_70:
        return ""
    pct = int(100 * tokens / _TRIGGER)
    if tokens >= _WARN_90:
        return (
            f"[COMPACTION HINT ⚠️] context_at_{pct}%_capacity ({tokens:,}/{_TRIGGER:,} tokens) — "
            "URGENT: write critical state (file paths, tool notes, findings) to "
            "session notes NOW before compaction fires."
        )
    return (
        f"[COMPACTION HINT] context_at_{pct}%_capacity ({tokens:,}/{_TRIGGER:,} tokens) — "
        "consider writing important file paths and tool notes to session notes."
    )


class TodoInject(Extension):

    async def execute(self, prompt_msgs=None, **kwargs):
        agent   = self.agent
        chat_id = str(getattr(agent, "chat_id", None) or agent.context.id)
        todo_path = os.path.join(TODO_DIR, f"{chat_id}.json")

        needs_bootstrap = agent.data.pop("todo_needs_bootstrap", False)
        if needs_bootstrap:
            bootstrap_msg = (
                "[SYSTEM — agent_todo plugin]\n"
                "No todo list exists for this chat yet.\n"
                "Your FIRST action must be to call the `todo_manager` tool with action='create' "
                "and a 'tasks' array of 10–50 concise task titles that represent the complete "
                "work plan for this conversation.\n"
                "Do NOT respond to the user before creating the todo list."
            )
            if prompt_msgs is not None:
                prompt_msgs.append({"role": "system", "content": bootstrap_msg})
            return

        if not os.path.exists(todo_path):
            return
        try:
            with open(todo_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        compact  = _render_compact(data)
        if not compact:
            return

        upcoming = _upcoming_3(data)

        inject_msg = (
            "[SYSTEM — agent_todo plugin]\n"
            "Follow tasks in order (queued → started → completed). "
            "Mark each task before and after working on it. Never re-mark a completed task.\n\n"
            + compact
        )
        if upcoming:
            inject_msg += f"\n{upcoming}"

        tokens = _get_context_tokens(agent)
        hint   = _compaction_hint(tokens)
        if hint:
            inject_msg += f"\n\n{hint}"

        if prompt_msgs is not None:
            prompt_msgs.append({"role": "system", "content": inject_msg})
