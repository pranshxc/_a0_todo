## todo_manager

Manages your per-chat **Todo List** — a persistent work order of 10–50 tasks you must follow throughout this conversation.

### Rules (strictly enforced)
1. **Create first.** At the start of every new chat, call `todo_manager` with `action=create` before doing anything else.
2. **Start before working.** Call `start` on a task before you begin it.
3. **Complete when done.** Call `complete` immediately after finishing.
4. **Block honestly.** If you cannot proceed, call `block` with a clear reason.
5. **Never loop.** The tool REJECTS re-marking tasks already in the target state. Move on.
6. **Follow order.** Work tasks sequentially unless a dependency requires otherwise.

### Actions

| action | required args | description |
|---|---|---|
| `create` | `tasks: ["t1", "t2", ...]` | Create the initial list (10–50 tasks). Only works once per chat. |
| `add` | `title: "string"` | Append a queued task (max 50 total). |
| `start` | `task_id: int` | queued → started |
| `complete` | `task_id: int` | started → completed |
| `block` | `task_id: int`, `reason: "string"` | started → blocked |
| `unblock` | `task_id: int` | blocked → started |
| `list` | _(none)_ | Print the full todo list. |

### Valid state machine
```
queued → started → completed  (terminal)
                ↘ blocked → started
```

### Examples
```json
{"action": "create", "tasks": ["Understand requirements", "Draft solution", "Implement", "Test", "Summarize"]}
```
```json
{"action": "start", "task_id": 1}
```
```json
{"action": "complete", "task_id": 1}
```
```json
{"action": "block", "task_id": 3, "reason": "Waiting for API key from user"}
```
