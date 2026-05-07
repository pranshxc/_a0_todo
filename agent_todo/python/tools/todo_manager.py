"""
todo_manager.py v5  (agent_todo path — the active plugin copy)

Fixes vs previous:
  1. batch_complete  - close N tasks in ONE call (biggest token-burn fix)
  2. batch_start     - start N tasks in ONE call
  3. complete force  - skip mandatory start pre-call with force:true
  4. silent no-op    - duplicate complete/start returns {status:no_op}
  5. upcoming_tasks  - every response returns next 3 queued tasks (kills lookahead calls)
  6. compact list    - grouped IDs by state; verbose only when verbose:true
  7. block/unblock   - preserved
"""
import json
import os
from datetime import datetime, timezone
from helpers.tool import Tool, Response

TODO_DIR = os.path.join("work", "todo")


# ── persistence ────────────────────────────────────────────────────────────

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


# ── formatters ─────────────────────────────────────────────────────────────

ICONS = {"queued": "⏳", "started": "🔄", "completed": "✅", "blocked": "🚫"}


def _fmt_compact(data: dict) -> str:
    """Compact grouped view — IDs only, no full titles."""
    tasks = data.get("tasks", [])
    if not tasks:
        return "Todo list is empty."
    groups: dict[str, list] = {"completed": [], "started": [], "queued": [], "blocked": []}
    for t in tasks:
        groups.get(t["status"], groups["queued"]).append(t["id"])
    total = len(tasks)
    done = len(groups["completed"])
    pct = f"{100 * done // total}%" if total else "0%"
    lines = [f"Todo: {done}/{total} done ({pct})"]
    if groups["completed"]:
        lines.append(f"  ✅ completed : {groups['completed']}")
    if groups["started"]:
        lines.append(f"  🔄 in_progress: {groups['started']}")
    if groups["blocked"]:
        lines.append(f"  🚫 blocked    : {groups['blocked']}")
    if groups["queued"]:
        lines.append(f"  ⏳ queued     : {groups['queued']}")
    return "\n".join(lines)


def _fmt_verbose(data: dict) -> str:
    """Full list with titles — only when explicitly requested."""
    tasks = data.get("tasks", [])
    if not tasks:
        return "Todo list is empty."
    done = sum(1 for t in tasks if t["status"] == "completed")
    lines = [f"Todo ({done}/{len(tasks)} done)"]
    for t in tasks:
        bl = f" ← BLOCKED: {t['blocked_reason']}" if t.get("blocked_reason") else ""
        lines.append(f"{ICONS.get(t['status'], '?')} [{t['id']}] {t['title']} ({t['status']}){bl}")
    return "\n".join(lines)


def _upcoming(data: dict, n: int = 3) -> str:
    """Next N queued tasks — appended to every mutating response to kill lookahead calls."""
    queued = [t for t in data.get("tasks", []) if t["status"] == "queued"]
    if not queued:
        return "upcoming: none (all tasks complete or in-progress)"
    parts = [f"[{t['id']}] {t['title']}" for t in queued[:n]]
    return "upcoming: " + " | ".join(parts)


def _remaining_count(data: dict) -> int:
    return sum(1 for t in data.get("tasks", []) if t["status"] != "completed")


# ── tool ───────────────────────────────────────────────────────────────────

class TodoManager(Tool):

    async def execute(self, **kwargs) -> Response:
        action = (self.args.get("action") or "").strip().lower()
        chat_id = str(getattr(self.agent, "chat_id", None) or self.agent.context.id)
        data = _load(chat_id)

        # ── create ──────────────────────────────────────────────────────────
        if action == "create":
            if data["tasks"]:
                return Response(
                    message="Todo list already exists. Use 'add' to append tasks or 'list' to view.",
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
                    f"Created {len(data['tasks'])} tasks.\n"
                    + _fmt_compact(data) + "\n"
                    + _upcoming(data)
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
            return Response(
                message=f"Added task [{new_id}]: {title}\n" + _upcoming(data),
                break_loop=False,
            )

        # ── start ────────────────────────────────────────────────────────────
        elif action == "start":
            tid = self._get_id()
            task = self._find(data, tid)
            if task is None:
                return Response(message=f"Task [{tid}] not found. Use 'list' to see valid IDs.", break_loop=False)
            if task["status"] == "started":
                return Response(message=f'{{"status":"no_op","task_id":{tid}}}', break_loop=False)
            task["status"] = "started"
            task["updated_at"] = _now()
            _save(data)
            return Response(
                message=(
                    f"Task [{tid}] → started. {_remaining_count(data)} remaining.\n"
                    + _upcoming(data)
                ),
                break_loop=False,
            )

        # ── complete ─────────────────────────────────────────────────────────
        elif action == "complete":
            tid = self._get_id()
            force = str(self.args.get("force", "false")).lower() in ("true", "1", "yes")
            note = (self.args.get("completion_note") or "").strip()
            task = self._find(data, tid)
            if task is None:
                return Response(message=f"Task [{tid}] not found.", break_loop=False)
            # silent no-op on duplicate complete
            if task["status"] == "completed":
                return Response(message=f'{{"status":"no_op","task_id":{tid}}}', break_loop=False)
            # force skips start requirement
            if task["status"] != "started" and not force:
                return Response(
                    message=(
                        f"Task [{tid}] is '{task['status']}', not started. "
                        "Use force:true to complete directly, or start it first."
                    ),
                    break_loop=False,
                )
            task["status"] = "completed"
            task["updated_at"] = _now()
            if note:
                task["completion_note"] = note
            _save(data)
            return Response(
                message=(
                    f"Task [{tid}] → completed. {_remaining_count(data)} remaining.\n"
                    + _upcoming(data)
                ),
                break_loop=False,
            )

        # ── batch_start ───────────────────────────────────────────────────────
        elif action == "batch_start":
            ids = self.args.get("task_ids", [])
            if not isinstance(ids, list) or not ids:
                return Response(message="Provide a non-empty 'task_ids' array.", break_loop=False)
            ok, skipped = [], []
            for tid in ids:
                task = self._find(data, int(tid))
                if task is None or task["status"] == "completed":
                    skipped.append(tid)
                    continue
                task["status"] = "started"
                task["updated_at"] = _now()
                ok.append(tid)
            _save(data)
            return Response(
                message=(
                    f"batch_start: started={ok} skipped={skipped}. "
                    f"{_remaining_count(data)} remaining.\n"
                    + _upcoming(data)
                ),
                break_loop=False,
            )

        # ── batch_complete ────────────────────────────────────────────────────
        elif action == "batch_complete":
            ids = self.args.get("task_ids", [])
            if not isinstance(ids, list) or not ids:
                return Response(message="Provide a non-empty 'task_ids' array.", break_loop=False)
            note = (self.args.get("completion_note") or "").strip()
            ok, already_done, not_found = [], [], []
            for tid in ids:
                task = self._find(data, int(tid))
                if task is None:
                    not_found.append(tid)
                    continue
                if task["status"] == "completed":
                    already_done.append(tid)
                    continue
                task["status"] = "completed"
                task["updated_at"] = _now()
                if note:
                    task["completion_note"] = note
                ok.append(tid)
            _save(data)
            return Response(
                message=(
                    f"batch_complete: completed={ok} already_done={already_done} not_found={not_found}.\n"
                    f"{_remaining_count(data)} remaining.\n"
                    + _upcoming(data)
                ),
                break_loop=False,
            )

        # ── block ─────────────────────────────────────────────────────────────
        elif action == "block":
            tid = self._get_id()
            reason = (self.args.get("reason") or "No reason provided.").strip()
            task = self._find(data, tid)
            if task is None:
                return Response(message=f"Task [{tid}] not found.", break_loop=False)
            task["status"] = "blocked"
            task["blocked_reason"] = reason
            task["updated_at"] = _now()
            _save(data)
            return Response(
                message=f"Task [{tid}] blocked: {reason}\n" + _upcoming(data),
                break_loop=False,
            )

        # ── unblock ───────────────────────────────────────────────────────────
        elif action == "unblock":
            tid = self._get_id()
            task = self._find(data, tid)
            if task is None:
                return Response(message=f"Task [{tid}] not found.", break_loop=False)
            task["status"] = "started"
            task["blocked_reason"] = None
            task["updated_at"] = _now()
            _save(data)
            return Response(
                message=f"Task [{tid}] unblocked → started.\n" + _upcoming(data),
                break_loop=False,
            )

        # ── list ──────────────────────────────────────────────────────────────
        elif action == "list":
            verbose = str(self.args.get("verbose", "false")).lower() in ("true", "1", "yes")
            return Response(
                message=_fmt_verbose(data) if verbose else _fmt_compact(data),
                break_loop=False,
            )

        else:
            return Response(
                message=(
                    "Valid actions: create, add, start, complete, batch_start, "
                    "batch_complete, block, unblock, list.\n"
                    "  batch_complete: {\"action\":\"batch_complete\",\"task_ids\":[15,16,17],\"completion_note\":\"done\"}\n"
                    "  complete force: {\"action\":\"complete\",\"task_id\":5,\"force\":true}\n"
                    "  list verbose  : {\"action\":\"list\",\"verbose\":true}"
                ),
                break_loop=False,
            )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_id(self) -> int:
        raw = self.args.get("task_id")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return -1

    def _find(self, data: dict, tid: int):
        return next((t for t in data.get("tasks", []) if t["id"] == tid), None)
