import json
import os
from datetime import datetime, timezone
from helpers.tool import Tool, Response

TODO_DIR = os.path.join("work", "todo")

# Valid state machine — prevents agent looping
VALID_TRANSITIONS = {
    "queued":    ["started"],
    "started":   ["completed", "blocked"],
    "blocked":   ["started"],
    "completed": [],  # terminal
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
    with open(_todo_path(data["chat_id"]), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_list(data: dict) -> str:
    tasks = data.get("tasks", [])
    if not tasks:
        return "Todo list is empty."
    icons = {"queued": "⏳", "started": "🔄", "completed": "✅", "blocked": "🚫"}
    done = sum(1 for t in tasks if t["status"] == "completed")
    lines = [f"## Todo ({done}/{len(tasks)} done)"]
    for t in tasks:
        icon = icons.get(t["status"], "❓")
        blocked = f"  ← BLOCKED: {t['blocked_reason']}" if t.get("blocked_reason") else ""
        lines.append(f"{icon} [{t['id']:>2}] {t['title']} ({t['status']}){blocked}")
    return "\n".join(lines)


class TodoManager(Tool):
    """Per-chat work-order todo list manager."""

    async def execute(self, **kwargs) -> Response:
        action = (self.args.get("action") or "").strip().lower()
        chat_id = self._chat_id()
        data = _load(chat_id)

        # ── create ─────────────────────────────────────────────────────────────
        if action == "create":
            if data["tasks"]:
                return Response(
                    message="Todo list already exists. Use 'add' to append or 'list' to view.",
                    break_loop=False,
                )
            raw = self.args.get("tasks", [])
            if not isinstance(raw, list) or not raw:
                return Response(message="Provide a non-empty 'tasks' array of title strings.", break_loop=False)
            for i, title in enumerate(raw[:50], start=1):
                data["tasks"].append({
                    "id": i, "title": str(title).strip(),
                    "status": "queued",
                    "created_at": _now(), "updated_at": _now(),
                    "blocked_reason": None,
                })
            _save(data)
            return Response(message=f"Created {len(data['tasks'])} tasks.\n\n{_format_list(data)}", break_loop=False)

        # ── add ────────────────────────────────────────────────────────────────
        elif action == "add":
            title = (self.args.get("title") or "").strip()
            if not title:
                return Response(message="Provide a 'title' for the new task.", break_loop=False)
            if len(data["tasks"]) >= 50:
                return Response(message="At 50-task limit. Complete tasks before adding more.", break_loop=False)
            new_id = max((t["id"] for t in data["tasks"]), default=0) + 1
            data["tasks"].append({
                "id": new_id, "title": title, "status": "queued",
                "created_at": _now(), "updated_at": _now(), "blocked_reason": None,
            })
            _save(data)
            return Response(message=f"Added task [{new_id}]: {title}", break_loop=False)

        # ── start ──────────────────────────────────────────────────────────────
        elif action == "start":
            return self._transition(data, self._get_id(), "started")

        # ── complete ───────────────────────────────────────────────────────────
        elif action == "complete":
            return self._transition(data, self._get_id(), "completed")

        # ── batch_complete ─────────────────────────────────────────────────────
        # Use this when you finished multiple tasks in one action.
        # Provide task_ids=[1,2,3] — ALL must be in 'started' state.
        # Returns a per-task verification report so you can see exactly what
        # succeeded, what was already completed, and what still needs starting.
        elif action == "batch_complete":
            raw_ids = self.args.get("task_ids", [])
            if not isinstance(raw_ids, list) or not raw_ids:
                return Response(
                    message="Provide 'task_ids' as a non-empty list of integer IDs.",
                    break_loop=False,
                )

            successes, skipped, errors = [], [], []

            for tid in raw_ids:
                try:
                    tid = int(tid)
                except (TypeError, ValueError):
                    errors.append(f"  ✗ '{tid}' — not a valid integer ID")
                    continue

                task = next((t for t in data["tasks"] if t["id"] == tid), None)
                if task is None:
                    errors.append(f"  ✗ [{tid}] — task not found")
                    continue

                current = task["status"]
                if current == "completed":
                    skipped.append(f"  ⚠ [{tid}] '{task['title']}' — already completed (skipped)")
                    continue
                if current != "started":
                    errors.append(
                        f"  ✗ [{tid}] '{task['title']}' — cannot complete from '{current}' "
                        f"(must be 'started' first). Call action=start for this task."
                    )
                    continue

                # Valid transition: started → completed
                task["status"] = "completed"
                task["updated_at"] = _now()
                task["blocked_reason"] = None
                successes.append(f"  ✅ [{tid}] '{task['title']}' → completed")

            _save(data)

            remaining = sum(1 for t in data["tasks"] if t["status"] in ("queued", "started", "blocked"))
            nxt = next((t for t in data["tasks"] if t["status"] == "queued"), None)
            next_hint = f"▶ Next queued: [{nxt['id']}] {nxt['title']}" if nxt else "🎉 All tasks complete!"

            report_lines = [f"batch_complete report ({len(successes)} completed, {len(skipped)} skipped, {len(errors)} errors):"]
            report_lines += successes + skipped + errors
            report_lines += ["", f"{remaining} task(s) remaining. {next_hint}"]

            # If there were errors (tasks not yet started), block response until fixed
            if errors:
                report_lines += [
                    "",
                    "⚠️ Some tasks could not be completed — they were NOT in 'started' state.",
                    "You MUST call action=start for each failed task before completing it.",
                    "Do NOT call response until all intended tasks are properly marked completed.",
                ]

            return Response(message="\n".join(report_lines), break_loop=False)

        # ── block ──────────────────────────────────────────────────────────────
        elif action == "block":
            reason = (self.args.get("reason") or "No reason provided.").strip()
            return self._transition(data, self._get_id(), "blocked", reason)

        # ── unblock ────────────────────────────────────────────────────────────
        elif action == "unblock":
            return self._transition(data, self._get_id(), "started")

        # ── list ───────────────────────────────────────────────────────────────
        elif action == "list":
            return Response(message=_format_list(data), break_loop=False)

        # ── check_done ─────────────────────────────────────────────────────────
        # Explicit pre-response gate: call this before giving a final response.
        # Returns a hard BLOCK message if any tasks are incomplete.
        elif action == "check_done":
            incomplete = [t for t in data["tasks"] if t["status"] != "completed"]
            if not incomplete:
                return Response(
                    message="✅ All tasks are completed. You may now give the final response.",
                    break_loop=False,
                )
            icons = {"queued": "⏳", "started": "🔄", "blocked": "🚫"}
            lines = [
                f"🚫 BLOCKED — {len(incomplete)} task(s) are not yet completed.",
                "You MUST finish and mark ALL tasks before responding to the user.",
                "",
                "Incomplete tasks:",
            ]
            for t in incomplete:
                icon = icons.get(t["status"], "❓")
                lines.append(f"  {icon} [{t['id']}] {t['title']} ({t['status']})")
            lines += ["", "Complete remaining tasks, then call check_done again before responding."]
            return Response(message="\n".join(lines), break_loop=False)

        else:
            return Response(
                message="Valid actions: create, add, start, complete, batch_complete, block, unblock, list, check_done.",
                break_loop=False,
            )

    def _chat_id(self) -> str:
        return str(
            getattr(self.agent, "chat_id", None)
            or getattr(self.agent.context, "id", None)
            or "default"
        )

    def _get_id(self) -> int:
        try:
            return int(self.args.get("task_id", -1))
        except (TypeError, ValueError):
            return -1

    def _transition(self, data: dict, task_id: int, new_status: str, reason: str = None) -> Response:
        task = next((t for t in data["tasks"] if t["id"] == task_id), None)
        if task is None:
            return Response(message=f"Task [{task_id}] not found. Use 'list' to see valid IDs.", break_loop=False)

        current = task["status"]
        allowed = VALID_TRANSITIONS.get(current, [])

        if current == new_status:
            return Response(message=f"Task [{task_id}] is already '{current}'. No change made.", break_loop=False)
        if new_status not in allowed:
            return Response(
                message=f"Cannot move task [{task_id}] from '{current}' → '{new_status}'. Allowed: {allowed or ['none — task is terminal']}.",
                break_loop=False,
            )

        task["status"] = new_status
        task["updated_at"] = _now()
        task["blocked_reason"] = reason if new_status == "blocked" else None
        _save(data)

        remaining = sum(1 for t in data["tasks"] if t["status"] in ("queued", "started", "blocked"))
        nxt = next((t for t in data["tasks"] if t["status"] == "queued"), None)
        hint = f" ▶ Next: [{nxt['id']}] {nxt['title']}" if nxt else " 🎉 All tasks complete!"
        suffix = f" Reason: {reason}" if reason else ""
        return Response(
            message=f"Task [{task_id}] → {new_status}.{suffix} ({remaining} remaining.){hint}",
            break_loop=False,
        )
