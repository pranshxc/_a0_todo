"""
message_loop_end -> _55_todo_auto_tracker

This is the CORE of v3. Fires after EVERY loop iteration (every LLM response
and tool call) using the UTILITY MODEL (cheap, fast, no full context sent).

What it does:
 1. Reads the agent's last AI response from loop_data
 2. Builds a tiny prompt: [todo list] + [last AI message summary]
 3. Asks the utility model: "which tasks just started or completed?"
 4. Applies those transitions directly to the JSON file
 5. The main LLM never has to call todo_manager for status updates again

Cost: ~200-500 utility tokens per loop iteration (vs 70k+ main model tokens
for the same update when the agent does it manually).
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
    "queued":  ["started"],
    "started": ["completed", "blocked"],
    "blocked": ["started"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(chat_id: str) -> dict | None:
    path = os.path.join(TODO_DIR, f"{chat_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(data: dict, chat_id: str) -> None:
    os.makedirs(TODO_DIR, exist_ok=True)
    path = os.path.join(TODO_DIR, f"{chat_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _render_for_prompt(data: dict) -> str:
    """Ultra-compact todo list for the utility model prompt."""
    lines = []
    for t in data.get("tasks", []):
        if t["status"] == "completed":
            continue  # don't bother the utility model with done tasks
        lines.append(f"[{t['id']}] {t['title']} ({t['status']})")
    return "\n".join(lines) if lines else "(all tasks completed)"


def _apply_updates(data: dict, updates: list[dict]) -> tuple[int, list[str]]:
    """Apply validated transitions. Returns (count_changed, change_descriptions)."""
    changed = 0
    descriptions = []
    for upd in updates:
        try:
            tid    = int(upd.get("id", -1))
            status = str(upd.get("status", "")).strip().lower()
        except Exception:
            continue

        task = next((t for t in data["tasks"] if t["id"] == tid), None)
        if task is None:
            continue

        current = task["status"]
        allowed = VALID_TRANSITIONS.get(current, [])
        if status not in allowed:
            continue  # invalid transition, skip silently

        task["status"]     = status
        task["updated_at"] = _now()
        if status != "blocked":
            task["blocked_reason"] = None
        changed += 1
        descriptions.append(f"[{tid}] {task['title']}: {current} → {status}")

    return changed, descriptions


class TodoAutoTracker(Extension):
    """
    Utility-model-powered automatic todo state tracker.
    Fires after every loop iteration. Zero main LLM cost.
    """

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        agent = self.agent
        if not agent:
            return
        # Only root agent
        if agent.number != 0:
            return

        chat_id = str(
            getattr(agent, "chat_id", None)
            or getattr(agent.context, "id", None)
            or "default"
        )

        data = _load(chat_id)
        if data is None:
            return  # no todo list yet

        tasks = data.get("tasks", [])
        if not tasks:
            return

        incomplete = [t for t in tasks if t["status"] != "completed"]
        if not incomplete:
            return  # all done, nothing to track

        # Get the agent's last response text
        last_response = getattr(loop_data, "last_response", "") or ""
        if not last_response.strip():
            return  # nothing to analyse

        # Trim the response for the utility model (we only need enough context)
        trimmed_response = last_response[:2000]  # ~500 tokens max

        todo_text = _render_for_prompt(data)

        system_prompt = """You are a task tracker. Given a list of active tasks and an agent's latest response/action, determine which tasks just STARTED or just COMPLETED based on what the agent actually did.

Rules:
- Only mark a task 'started' if the agent explicitly began working on it in this response.
- Only mark a task 'completed' if the agent actually finished and verified the work in this response.
- A task that was merely mentioned or planned is NOT started.
- Return ONLY a JSON array of objects: [{"id": N, "status": "started|completed"}, ...]
- If no tasks changed state, return: []
- Return ONLY the JSON array, no explanation."""

        user_prompt = f"""Active tasks:
{todo_text}

Agent's last action/response:
{trimmed_response}

Which tasks changed state? Return JSON array:"""

        try:
            raw = await agent.call_utility_model(
                system=system_prompt,
                message=user_prompt,
                background=True,  # non-blocking, runs in background
            )
        except Exception:
            return  # utility model unavailable, fail silently

        if not raw or not raw.strip():
            return

        # Parse JSON from utility model response
        updates = _parse_json_updates(raw)
        if not updates:
            return

        changed, descriptions = _apply_updates(data, updates)
        if changed == 0:
            return

        _save(data, chat_id)

        # Log changes in sidebar (visible but non-intrusive)
        try:
            agent.context.log.log(
                type="hint",
                heading="📋 Todo Auto-Updated",
                content="\n".join(descriptions),
            )
        except Exception:
            pass


def _parse_json_updates(raw: str) -> list[dict]:
    """Robustly extract JSON array from utility model response."""
    raw = raw.strip()
    # Try direct parse
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except Exception:
        pass
    # Extract first [...] block
    try:
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
    except Exception:
        pass
    return []
