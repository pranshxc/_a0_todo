# _a0_todo — Agent Todo Plugin

A production-grade Agent Zero plugin that gives every chat its own persistent, structured **Todo List** — a 10–50 task work order the agent follows, marks, and stays aware of at all times.

## Installation

Copy this folder as `_a0_todo` into your Agent Zero `plugins/` directory and restart:

```bash
cp -r _a0_todo/ /path/to/agent-zero/plugins/_a0_todo/
docker restart agent-zero
```

The plugin auto-discovers — no manual registration needed.

## Correct Plugin Structure

```
plugins/_a0_todo/
├── plugin.yaml                                          # plugin metadata (name must match folder)
├── README.md
├── tools/
│   └── todo_manager.py                                  # tool the agent calls
├── extensions/
│   └── python/
│       ├── monologue_start/
│       │   └── _50_todo_bootstrap.py                    # bootstrap on new chat
│       └── message_loop_prompts_after/
│           └── _50_todo_inject.py                       # inject todo into every prompt
└── prompts/
    └── agent.system.tool.todo_manager.md                # LLM tool description
```

## How It Works

### 1. Bootstrap (`monologue_start`)
When a new chat starts and no `work/todo/{chat_id}.json` exists, injects a hard system instruction via `extras_persistent` telling the agent its first action must be calling `todo_manager` with `action=create`.

### 2. Inject (`message_loop_prompts_after`)
On every loop iteration, reads the chat's JSON and injects a compact `<todo_list>` block into `extras_persistent` — the same mechanism memory uses — so the LLM always sees the full work order alongside memory.

### 3. Tool (`todo_manager`)
Single tool with 7 actions: `create`, `add`, `start`, `complete`, `block`, `unblock`, `list`.

Strict state machine prevents loops:
```
queued → started → completed  (terminal)
                ↘ blocked → started
```
Re-marking or invalid transitions return an error immediately — the agent cannot loop.

## Task JSON Schema

```json
{
  "chat_id": "abc123",
  "created_at": "2026-05-04T10:00:00+00:00",
  "tasks": [
    {
      "id": 1,
      "title": "Research the topic",
      "status": "completed",
      "created_at": "2026-05-04T10:00:00+00:00",
      "updated_at": "2026-05-04T10:05:00+00:00",
      "blocked_reason": null
    }
  ]
}
```

Todo files are stored at `work/todo/{chat_id}.json` inside the Agent Zero working directory.

## License
MIT
