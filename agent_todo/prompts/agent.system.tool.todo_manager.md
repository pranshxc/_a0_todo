## todo_manager

Manages your per-chat structured **Todo List** — a persistent work order of 10–50 tasks you must follow throughout this conversation.

### Rules you MUST follow
1. **Create the list first.** At the very start of every new chat, call `todo_manager` with `action=create` before doing anything else.
2. **Mark before you work.** Call `start` on a task before beginning it.
3. **Mark when done.** Call `complete` immediately after finishing a task.
4. **Mark blockers honestly.** If a task cannot proceed, call `block` with a clear reason.
5. **Never loop.** Do NOT call `start` or `complete` on a task that is already in that state — the system will reject it.
6. **Follow order.** Work through tasks sequentially unless a dependency forces otherwise.

### Actions

| action | required args | description |
|---|---|---|
| `create` | `tasks: ["title1", ...]` | Create the initial todo list (10–50 tasks). Only works if the list is empty. |
| `add` | `title: "string"` | Append a new queued task (max 50 total). |
| `start` | `task_id: int` | Mark a task as started. Only valid from `queued` or `blocked`. |
| `complete` | `task_id: int` | Mark a task as completed. Only valid from `started`. |
| `block` | `task_id: int`, `reason: "string"` | Mark a task as blocked. Only valid from `started`. |
| `unblock` | `task_id: int` | Move a blocked task back to started. |
| `list` | _(none)_ | Print the full current todo list. |

### Valid state transitions
```
queued → started
started → completed  (terminal)
started → blocked
blocked → started
```

### Example usage

```json
{"action": "create", "tasks": ["Clarify requirements", "Research solution", "Implement feature", "Write tests", "Document changes"]}
```

```json
{"action": "start", "task_id": 1}
```

```json
{"action": "complete", "task_id": 1}
```

```json
{"action": "block", "task_id": 3, "reason": "Waiting for API credentials from user"}
```
