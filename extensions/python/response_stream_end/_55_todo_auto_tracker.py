"""
response_stream_end -> _55_todo_auto_tracker

Fires after EVERY complete LLM response (including mid-turn tool loops).
Uses agent.call_utility_model() which sends ONLY:
  - A tiny system prompt (~150 tokens)
  - The incomplete task list (~50 tokens per task)
  - The last LLM response trimmed to 1500 chars (~375 tokens)

Total: ~600-800 utility tokens per LLM call.
Vs main model call for start/complete: 70,000 input tokens.

This file replaces message_loop_end which fired AFTER tool execution.
response_stream_end fires AFTER the LLM response text is complete but
BEFORE tool execution — giving us the agent's INTENTION in text, which
is the right signal to track ("Starting T160", "Completing T160", etc).

API confirmed from agent.py:
  await agent.call_utility_model(system=..., message=..., background=True)
  background=True = skip rate limiter (non-blocking in terms of UI progress)
"""
from __future__ import annotations
import os
import json
import re
from datetime import datetime, timezone
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")

VALID_TRANSITIONS = {
    "queued":    ["started", "completed"],  # allow direct queued->completed
    "started":   ["completed"],
    "blocked":   ["started", "completed"],
}

_SYSTEM = """You are a task tracker assistant. Given a list of pending tasks and an agent's response text, identify which tasks just started or completed.

Rules:
- 'started': agent explicitly began this task in the response ("Starting T5", "Working on", "Executing T5")
- 'completed': agent finished and confirmed the task ("Completed T5", "T5 done", "Completing T5 and continuing")
- Do NOT infer. Only mark what is explicit in the text.
- Return ONLY a compact JSON array: [{"id":N,"status":"started|completed"}, ...]
- If nothing changed: return []"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load(chat_id):
    p = os.path.join(TODO_DIR, f"{chat_id}.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(data, chat_id):
    os.makedirs(TODO_DIR, exist_ok=True)
    with open(os.path.join(TODO_DIR, f"{chat_id}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _pending_text(data):
    lines = []
    for t in data.get("tasks", []):
        if t["status"] != "completed":
            lines.append(f"[{t['id']}] {t['title']} ({t['status']})")
    return "\n".join(lines) if lines else ""


def _parse(raw):
    if not raw:
        return []
    raw = raw.strip()
    try:
        r = json.loads(raw)
        if isinstance(r, list):
            return r
    except Exception:
        pass
    try:
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if m:
            r = json.loads(m.group(0))
            if isinstance(r, list):
                return r
    except Exception:
        pass
    return []


def _apply(data, updates):
    changed = []
    for u in updates:
        try:
            tid = int(u.get("id", -1))
            st  = str(u.get("status", "")).strip().lower()
        except Exception:
            continue
        task = next((t for t in data["tasks"] if t["id"] == tid), None)
        if not task:
            continue
        allowed = VALID_TRANSITIONS.get(task["status"], [])
        if st not in allowed:
            continue
        old = task["status"]
        task["status"]         = st
        task["updated_at"]     = _now()
        task["blocked_reason"] = None
        changed.append(f"[{tid}] {task['title']}: {old} → {st}")
    return changed


class TodoAutoTracker(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        agent = self.agent
        if not agent or agent.number != 0:
            return

        # Get last response text from loop_data
        last_response = getattr(loop_data, "last_response", "") or ""
        if not last_response.strip() or len(last_response.strip()) < 10:
            return

        chat_id = str(
            getattr(agent, "chat_id", None)
            or getattr(agent.context, "id", None)
            or "default"
        )

        data = _load(chat_id)
        if not data:
            return

        pending = _pending_text(data)
        if not pending:
            return  # all done

        # Trim response to control token cost
        # The agent's GEN messages like "Starting T160: Identify cloud infrastructure IPs"
        # are typically <200 chars. 1500 chars = more than enough context.
        trimmed = last_response[:1500]

        user_msg = f"Pending tasks:\n{pending}\n\nAgent response:\n{trimmed}\n\nJSON:"

        try:
            raw = await agent.call_utility_model(
                system=_SYSTEM,
                message=user_msg,
                background=True,  # skip rate limiter UI progress bar
            )
        except Exception:
            return

        updates = _parse(raw)
        if not updates:
            return

        changed = _apply(data, updates)
        if not changed:
            return

        _save(data, chat_id)

        try:
            agent.context.log.log(
                type="hint",
                heading="📋 Auto-tracked",
                content="\n".join(changed),
            )
        except Exception:
            pass
