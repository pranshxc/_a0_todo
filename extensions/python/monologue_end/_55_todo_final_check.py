"""
monologue_end -> _55_todo_final_check

End-of-turn accuracy pass. After the full agent turn (all tool calls done),
ask utility model to review what was accomplished vs what's still pending.
Catches tasks the per-response tracker missed (ambiguous language, etc).

Cost: ~800-1200 utility tokens once per user turn.
"""
from __future__ import annotations
import os
import json
import re
from datetime import datetime, timezone
from helpers.extension import Extension
from agent import LoopData

TODO_DIR = os.path.join("work", "todo")

_SYSTEM = """You are a task completion auditor. Given a full task list and a summary of agent work this turn, identify any tasks that are now complete but not yet marked as such.

Rules:
- Only mark 'completed' if the work was clearly and fully done.
- Partial or planned work does NOT count as complete.
- Queued tasks can be marked completed directly if clearly done.
- Return ONLY a JSON array: [{"id":N,"status":"completed"}, ...]
- If nothing to update: return []"""


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
    with open(os.path.join(TODO_DIR, f"{chat_id}.json"), "w", encoding="it-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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
        if not data:
            return

        tasks = data.get("tasks", [])
        if not tasks:
            return

        incomplete = [t for t in tasks if t["status"] != "completed"]
        done = len(tasks) - len(incomplete)

        if not incomplete:
            try:
                agent.context.log.log(
                    type="hint",
                    heading=f"📋 All {len(tasks)} tasks complete",
                    content="Turn finished.",
                )
            except Exception:
                pass
            return

        # Build minimal context for utility model
        # Only send incomplete tasks + last_response (not full history)
        task_lines = "\n".join(
            f"[{t['id']}] {t['title']} (current: {t['status']})"
            for t in incomplete
        )

        # Use last_response as the work summary (already in loop_data)
        work_summary = getattr(loop_data, "last_response", "") or ""
        work_summary = work_summary[:2000]  # cap tokens

        if not work_summary.strip():
            return

        user_msg = f"Incomplete tasks:\n{task_lines}\n\nWork done this turn:\n{work_summary}\n\nJSON:"

        try:
            raw = await agent.call_utility_model(
                system=_SYSTEM,
                message=user_msg,
                background=True,
            )
        except Exception:
            return

        updates = _parse(raw)
        changed = []
        ALLOWED = {"queued": ["completed"], "started": ["completed"], "blocked": ["completed"]}
        for u in updates:
            try:
                tid = int(u.get("id", -1))
                st  = str(u.get("status", "")).strip().lower()
            except Exception:
                continue
            task = next((t for t in tasks if t["id"] == tid), None)
            if not task:
                continue
            if st not in ALLOWED.get(task["status"], []):
                continue
            old = task["status"]
            task["status"]         = st
            task["updated_at"]     = _now()
            task["blocked_reason"] = None
            changed.append(f"[{tid}] {task['title']}: {old} → {st}")

        if changed:
            _save(data, chat_id)
            done += len(changed)

        remaining = len(tasks) - done
        try:
            correction = ("\nFinal-pass corrections:\n" + "\n".join(changed)) if changed else ""
            agent.context.log.log(
                type="hint",
                heading=f"📋 Todo: {done}/{len(tasks)} done ({remaining} remaining)",
                content=f"Turn complete.{correction}",
            )
        except Exception:
            pass
