"""
todo_manager.py v4 - MINIMUM SURFACE tool.

The agent can ONLY call:
  create   - build the initial task list
  add      - add a new unexpected task
  block    - mark a task blocked with reason
  unblock  - clear a block
  list     - inspect current state

start / complete / batch_complete / check_done are GONE.
They are handled automatically by the utility model tracker.
If the agent tries to call them, it gets a clear redirect message
telling it to just do the work.
"""
import json
import os
from datetime import datetime, timezone
from helpers.tool import Tool, Response

TODO_DIR = os.path.join("work", "todo")


def _path(chat_id: str) -> str:
    os.makedirs(TODO_DIR, exist_ok=True)
    return os.path.join(TODO_DIR, f"{chat_id}.json")


def _load(chat_id: str) -> dict:
    p = _path(chat_id)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"chat_id": chat_id, "created_at": _now(), "tasks": []}


def _save(data: dict) -> None:
    with open(_path(data["chat_id"]), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt(data: dict) -> str:
    tasks = data.get("tasks", [])
    if not tasks:
        return "Todo list is empty."
    icons = {"queued": "⏳", "started": "🔄", "completed": "✅", "blocked": "🚫"}
    done = sum(1 for t in tasks if t["status"] == "completed")
    lines = [f"Todo ({done}/{len(tasks)} done)"]
    for t in tasks:
        bl = f" ← BLOCKED: {t['blocked_reason']}" if t.get("blocked_reason") else ""
        lines.append(f"{icons.get(t['status'],  '?')} [{t['id']}] {t['title']} ({t['status']}){bl}")
    return "\n".join(lines)


REDIRECT_MSG = (
    "You do not need to call todo_manager for task status updates. "
    "The system tracks start/complete automatically based on your work. "
    "Just do the actual work and the todo list will update itself."
)


class TodoManager(Tool):

    async def execute(self, **kwargs) -> Response:
        action = (self.args.get("action") or "").strip().lower()
        chat_id = self._cid()
        data = _load(chat_id)

        # ── silently redirect wasted calls back to work ─────────────────────
        if action in ("start", "complete", "batch_complete", "check_done"):
            return Response(message=REDIRECT_MSG, break_loop=False)

        # ── create ──────────────────────────────────────────────────────────
        if action == "create":
            if data["tasks"]:
                return Response(
                    message="Todo list already exists. Use 'add' to append tasks.",
                    break_loop=False,
                )
            raw = self.args.get("tasks", [])
            if not isinstance(raw, list) or not raw:
                return Response(message="Provide a non-empty 'tasks' array.", break_loop=False)
            for i, title in enumerate(raw[:50], start=1):
                data["tasks"].append({
                    "id": i, "title": str(title).strip(), "status": "queued",
                    "created_at": _now(), "updated_at": _now(), "blocked_reason": None,
                })
            _save(data)
            return Response(
                message=(
                    f"Created {len(data['tasks'])} tasks. "
                    "Start working immediately — the system tracks progress automatically.\n\n"
                    + _fmt(data)
                ),
                break_loop=False,
            )

        # ── add ─────────────────────────────────────────────────────────────
        elif action == "add":
            title = (self.args.get("title") or "").strip()
            if not title:
                return Response(message="Provide a 'title'.", break_loop=False)
            new_id = max((t["id"] for t in data["tasks"]), default=0) + 1
            data["tasks"].append({
                "id": new_id, "title": title, "status": "queued",
                "created_at": _now(), "updated_at": _now(), "blocked_reason": None,
            })
            _save(data)
            return Response(message=f"Task [{new_id}] added: {title}", break_loop=False)

        # ── block ────────────────────────────────────────────────────────────
        elif action == "block":
            tid = self._tid()
            reason = (self.args.get("reason") or "No reason.").strip()
            task = next((t for t in data["tasks"] if t["id"] == tid), None)
            if not task:
                return Response(message=f"Task [{tid}] not found.", break_loop=False)
            task["status"] = "blocked"
            task["blocked_reason"] = reason
            task["updated_at"] = _now()
            _save(data)
            return Response(message=f"Task [{tid}] blocked: {reason}", break_loop=False)

        # ── unblock ──────────────────────────────────────────────────────────
        elif action == "unblock":
            tid = self._tid()
            task = next((t for t in data["tasks"] if t["id"] == tid), None)
            if not task:
                return Response(message=f"Task [{tid}] not found.", break_loop=False)
            task["status"] = "started"
            task["blocked_reason"] = None
            task["updated_at"] = _now()
            _save(data)
            return Response(message=f"Task [{tid}] unblocked, resumed.", break_loop=False)

        # ── list ─────────────────────────────────────────────────────────────
        elif action == "list":
            return Response(message=_fmt(data), break_loop=False)

        else:
            return Response(
                message="Valid actions: create, add, block, unblock, list.",
                break_loop=False,
            )

    def _cid(self) -> str:
        return str(
            getattr(self.agent, "chat_id", None)
            or getattr(self.agent.context, "id", None)
            or "default"
        )

    def _tid(self) -> int:
        try:
            return int(self.args.get("task_id", -1))
        except (TypeError, ValueError):
            return -1
