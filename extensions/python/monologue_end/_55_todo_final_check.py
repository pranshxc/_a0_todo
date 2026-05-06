"""
monologue_end -> _55_todo_final_check

Fires once after the agent's complete response (including all tool calls).
Uses utility model to do a final accuracy pass:
 - Compare the todo list state against the full monologue summary
 - Catch any tasks the per-iteration tracker might have missed
 - Log a completion summary

This is the safety net that ensures accuracy even if the per-iteration
tracker missed something due to ambiguous language.
"""
from __future__ import annotations
import os
import json
import re
from datetime import datetime, timezone
from helpers.extension import Extension
from agent import LoopData
from helpers.history import output_text

TODO_DIR = os.path.join("work", "todo")

VALID_TRANSITIONS = {
    "queued":  ["started", "completed"],  # allow queued->completed if agent did it without explicit start
    "started": ["completed"],
    "blocked": ["started", "completed"],
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


class TodoFinalCheck(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        agent = self.agent
        if not agent or agent.number != 0:
            return

        chat_id = str(
            getattr(agent, "chat_id", None)
            or getattr(agent.context, "id", None)
            or "default"
        )

        data = _load(chat_id)
        if data is None:
            return

        tasks      = data.get("tasks", [])
        incomplete = [t for t in tasks if t["status"] != "completed"]
        done       = len(tasks) - len(incomplete)

        if not tasks:
            return

        # Build a concise summary of what happened this turn for the utility model
        # Use only the current topic messages (not full history) for cost efficiency
        try:
            current_topic_msgs = agent.history.current.output()
            turn_text = output_text(current_topic_msgs)[:3000]  # cap at ~750 tokens
        except Exception:
            turn_text = getattr(loop_data, "last_response", "")[:2000]

        if not turn_text.strip():
            return

        # Build compact task list
        task_lines = []
        for t in tasks:
            task_lines.append(f"[{t['id']}] {t['title']} (current: {t['status']})")
        todo_text = "\n".join(task_lines)

        system_prompt = """You are a task completion auditor. Given a full task list with current statuses and a summary of the agent's completed work this turn, identify any tasks that should now be marked 'completed' but aren't yet.

Rules:
- Only mark 'completed' if the work was clearly and fully done in the provided text.
- Do NOT complete tasks that were only partially done or just mentioned.
- Queued tasks can be marked completed directly if the work was done (skipping 'started').
- Return ONLY a JSON array: [{"id": N, "status": "completed"}, ...]
- If nothing to update, return: []
- Return ONLY the JSON array."""

        user_prompt = f"""All tasks:
{todo_text}

Work done this turn:
{turn_text}

Any tasks to mark completed? Return JSON:"""

        try:
            raw = await agent.call_utility_model(
                system=system_prompt,
                message=user_prompt,
                background=True,
            )
        except Exception:
            return

        updates = _parse_json(raw)
        if not updates:
            # Log final stats anyway
            _log_summary(agent, done, len(tasks), [])
            return

        # Apply with relaxed transitions for monologue-end accuracy pass
        changed_descs = []
        for upd in updates:
            try:
                tid    = int(upd.get("id", -1))
                status = str(upd.get("status", "")).strip().lower()
            except Exception:
                continue
            task = next((t for t in tasks if t["id"] == tid), None)
            if task is None:
                continue
            current = task["status"]
            allowed = VALID_TRANSITIONS.get(current, [])
            if status not in allowed:
                continue
            task["status"]         = status
            task["updated_at"]     = _now()
            task["blocked_reason"] = None
            changed_descs.append(f"[{tid}] {task['title']}: {current} → {status}")

        if changed_descs:
            _save(data, chat_id)
            done_after = sum(1 for t in tasks if t["status"] == "completed")
        else:
            done_after = done

        _log_summary(agent, done_after, len(tasks), changed_descs)


def _log_summary(agent, done: int, total: int, corrections: list[str]) -> None:
    try:
        remaining = total - done
        correction_note = ""
        if corrections:
            correction_note = "\nCaught by final pass:\n" + "\n".join(corrections)
        agent.context.log.log(
            type="hint",
            heading=f"📋 Todo: {done}/{total} done ({remaining} remaining)",
            content=f"Turn complete.{correction_note}",
        )
    except Exception:
        pass


def _parse_json(raw: str) -> list[dict]:
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
