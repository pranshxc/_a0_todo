"""
agent_todo -> message_loop_prompts_after -> _50_todo_inject

Injects the current todo list into every prompt as a system message.
Also injects a compaction_hint warning when context is approaching capacity
(Fix 3C) — signals the agent to proactively write important state to
session notes BEFORE compaction fires and strips it from context.
"""
import os
import json
from helpers.extension import Extension

TODO_DIR = os.path.join("work", "todo")

# Compaction hint thresholds — read from env to stay in sync with context_guard
# CTX_GUARD_TARGET_TOKENS default 40000, BUFFER default 10000 = trigger at 50000
_TARGET   = int(os.environ.get("CTX_GUARD_TARGET_TOKENS",  "40000"))
_BUFFER   = int(os.environ.get("CTX_GUARD_BUFFER_TOKENS",  "10000"))
_TRIGGER  = _TARGET + _BUFFER  # 50000 default

# Warn at 70% and 90% of trigger
_WARN_70  = int(_TRIGGER * 0.70)   # ~35000
_WARN_90  = int(_TRIGGER * 0.90)   # ~45000

STATUS_ICONS = {
    "queued":    "⏳",
    "started":   "🔄",
    "completed": "✅",
    "blocked":   "🚫",
}


def _render_todo(data: dict) -> str:
    tasks = data.get("tasks", [])
    if not tasks:
        return ""

    total  = len(tasks)
    done   = sum(1 for t in tasks if t["status"] == "completed")
    active = next((t for t in tasks if t["status"] == "started"), None)

    lines = [
        "<todo_list>",
        f"  Progress: {done}/{total} completed",
    ]
    if active:
        lines.append(f"  Currently active: [{active['id']}] {active['title']}")
    lines.append("  Tasks:")
    for t in tasks:
        icon    = STATUS_ICONS.get(t["status"], "❓")
        blocked = f"  ← BLOCKED: {t['blocked_reason']}" if t.get("blocked_reason") else ""
        lines.append(f"    {icon} [{t['id']:>2}] {t['title']} ({t['status']}){blocked}")
    lines.append("</todo_list>")
    return "\n".join(lines)


def _get_context_tokens(agent) -> int:
    """Best-effort context token count — mirrors context_guard helpers."""
    try:
        t = agent.history.get_tokens()
        if t and t > 0:
            return t
    except Exception:
        pass
    try:
        # Fallback: read last known value stored by context_guard
        return agent.context.data.get("_ctxguard_last_tokens", 0)
    except Exception:
        pass
    return 0


def _compaction_hint(tokens: int) -> str:
    """Return a compaction_hint string if context is at 70%+ capacity, else ''."""
    if tokens <= 0 or tokens < _WARN_70:
        return ""
    pct = int(100 * tokens / _TRIGGER)
    if tokens >= _WARN_90:
        return (
            f"[COMPACTION HINT ⚠️] context_at_{pct}%_capacity — "
            "URGENT: write critical state (file paths, tool notes, findings) to "
            "session notes NOW before compaction fires. "
            "Use todo_manager action='list' verbose=true to confirm current task state."
        )
    return (
        f"[COMPACTION HINT] context_at_{pct}%_capacity — "
        "consider writing important file paths and tool notes to session notes "
        "before context is compressed."
    )


class TodoInject(Extension):
    """Inject the current chat todo list + optional compaction hint into the system prompt."""

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

        rendered = _render_todo(data)
        if not rendered:
            return

        inject_msg = (
            "[SYSTEM — agent_todo plugin]\n"
            "Below is your current work order. Follow tasks in order (queued → started → completed). "
            "Mark each task before and after working on it. Never re-mark a completed task.\n\n"
            + rendered
        )

        # Fix 3C: append compaction_hint if context is getting full
        tokens = _get_context_tokens(agent)
        hint   = _compaction_hint(tokens)
        if hint:
            inject_msg += f"\n\n{hint}"

        if prompt_msgs is not None:
            prompt_msgs.append({"role": "system", "content": inject_msg})
