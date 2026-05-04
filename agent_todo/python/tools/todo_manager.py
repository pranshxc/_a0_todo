import json
import os
from datetime import datetime, timezone
from helpers.tool import Tool, Response

TODO_DIR = os.path.join("work", "todo")

VALID_TRANSITIONS = {
    "queued": ["started"],
    "started": ["completed", "blocked"],
    "blocked": ["started"],
    "completed": [],  # terminal — no further transitions allowed
}


def _todo_path(chat_id: str) -> str:
    os.makedirs(TODO_DIR, exist_ok=True)
    return os.path.join(TODO_DIR, f"{chat_id}.json")


def _load(chat_id: str) -> dict:
    path = _todo_path(chat_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"chat_id": chat_id, "created_at": _now(), "tasks": []}


def _save(data: dict) -> None:
    path = _todo_path(data["chat_id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_list(data: dict) -> str:
    tasks = data.get("tasks", [])
    if not tasks:
        return "Todo list is empty."
    icons = {"queued": "⏳", "started": "🔄", "completed": "✅", "blocked": "🚫"}
    lines = [f"## Todo List ({len(tasks)} tasks)"]
    for t in tasks:
        icon = icons.get(t["status"], "❓")
        blocked = f" — BLOCKED: {t['blocked_reason']}" if t.get("blocked_reason") else ""
        lines.append(f"{icon} [{t['id']}] {t['title']} ({t['status']}){blocked}")
    return "\n".join(lines)


class TodoManager(Tool):
    """Manages the per-chat structured todo list."""

    async def execute(self, **kwargs) -> Response:
        action = (self.args.get("action") or "").strip().lower()
        chat_id = str(getattr(self.agent, "chat_id", None) or self.agent.context.id)
        data = _load(chat_id)

        # ── CREATE ──────────────────────────────────────────────────────────
        if action == "create":
            if data["tasks"]:
                return Response(
                    message="Todo list already exists. Use 'add' to append tasks or 'list' to view.",
                    break_loop=False,
                )
            raw_tasks = self.args.get("tasks", [])
            if not isinstance(raw_tasks, list) or len(raw_tasks) < 1:
                return Response(
                    message="Provide a 'tasks' array with at least 1 task title string.",
                    break_loop=False,
                )
            if len(raw_tasks) > 50:
                raw_tasks = raw_tasks[:50]
            for i, title in enumerate(raw_tasks, start=1):
                data["tasks"].append({
                    "id": i,
                    "title": str(title).strip(),
                    "status": "queued",
                    "created_at": _now(),
                    "updated_at": _now(),
                    "blocked_reason": None,
                })
            _save(data)
            return Response(message=f"Created todo list with {len(data['tasks'])} tasks.\n\n{_format_list(data)}", break_loop=False)

        # ── ADD ─────────────────────────────────────────────────────────────
        elif action == "add":
            title = (self.args.get("title") or "").strip()
            if not title:
                return Response(message="Provide a 'title' for the new task.", break_loop=False)
            if len(data["tasks"]) >= 50:
                return Response(message="Todo list is at the 50-task limit. Complete or remove tasks first.", break_loop=False)
            new_id = max((t["id"] for t in data["tasks"]), default=0) + 1
            data["tasks"].append({
                "id": new_id,
                "title": title,
                "status": "queued",
                "created_at": _now(),
                "updated_at": _now(),
                "blocked_reason": None,
            })
            _save(data)
            return Response(message=f"Added task [{new_id}]: {title}", break_loop=False)

        # ── START ────────────────────────────────────────────────────────────
        elif action == "start":
            return self._transition(data, task_id=self._get_id(), new_status="started")

        # ── COMPLETE ─────────────────────────────────────────────────────────
        elif action == "complete":
            return self._transition(data, task_id=self._get_id(), new_status="completed")

        # ── BLOCK ─────────────────────────────────────────────────────────────
        elif action == "block":
            reason = (self.args.get("reason") or "No reason provided.").strip()
            return self._transition(data, task_id=self._get_id(), new_status="blocked", reason=reason)

        # ── UNBLOCK (alias: start from blocked) ───────────────────────────────
        elif action == "unblock":
            return self._transition(data, task_id=self._get_id(), new_status="started")

        # ── LIST ─────────────────────────────────────────────────────────────
        elif action == "list":
            return Response(message=_format_list(data), break_loop=False)

        else:
            return Response(
                message=(
                    "Unknown action. Valid actions: create, add, start, complete, block, unblock, list.\n"
                    "Example: {\"action\": \"start\", \"task_id\": 1}"
                ),
                break_loop=False,
            )

    # ── helpers ────────────────────────────────────────────────────────────

    def _get_id(self) -> int:
        raw = self.args.get("task_id")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return -1

    def _transition(self, data: dict, task_id: int, new_status: str, reason: str = None) -> Response:
        task = next((t for t in data["tasks"] if t["id"] == task_id), None)
        if task is None:
            return Response(message=f"Task [{task_id}] not found. Use 'list' to see valid IDs.", break_loop=False)

        current = task["status"]
        allowed = VALID_TRANSITIONS.get(current, [])

        if new_status not in allowed:
            if current == new_status:
                return Response(
                    message=f"Task [{task_id}] is already '{current}'. No change made.",
                    break_loop=False,
                )
            return Response(
                message=(
                    f"Cannot transition task [{task_id}] from '{current}' to '{new_status}'. "
                    f"Allowed next states: {allowed or ['none (terminal)']}"
                ),
                break_loop=False,
            )

        task["status"] = new_status
        task["updated_at"] = _now()
        task["blocked_reason"] = reason if new_status == "blocked" else None

        chat_id = data["chat_id"]
        _save(data)

        # count remaining work
        remaining = sum(1 for t in data["tasks"] if t["status"] in ("queued", "started", "blocked"))
        next_queued = next((t for t in data["tasks"] if t["status"] == "queued"), None)
        next_hint = f" Next queued: [{next_queued['id']}] {next_queued['title']}" if next_queued else " All tasks complete!"

        return Response(
            message=f"Task [{task_id}] → {new_status}.{' Reason: ' + reason if reason else ''} ({remaining} tasks remaining).{next_hint}",
            break_loop=False,
        )
