# Agent Todo Plugin for Agent Zero

A production-grade plugin that gives every Agent Zero chat its own persistent, structured **Todo List** — a 10–50 task work order the agent follows, marks, and stays aware of at all times.

## Features

- **Per-chat todo list** scoped to each conversation
- **4 task states**: `queued` → `started` → `completed` | `blocked`
- **Always-visible context**: todo list is injected alongside memory into every LLM prompt via the Utility model
- **Loop-safe design**: task state transitions are validated — an agent cannot re-mark or loop on the same task
- **Atomic JSON storage**: each chat's todo is stored at `work/todo/{chat_id}.json`
- **Single tool interface**: one clean `todo_manager` tool the agent uses to manage all task operations

## Installation

Copy the `agent_todo/` directory into your Agent Zero `plugins/` folder:

```bash
cp -r agent_todo/ /path/to/agent-zero/plugins/
```

Then restart Agent Zero. The plugin auto-discovers and loads.

## Plugin Structure

```
plugins/agent_todo/
├── README.md
├── plugin.yaml                          # plugin metadata
├── python/
│   └── tools/
│       └── todo_manager.py             # tool the agent calls
├── extensions/
│   ├── agent_init/
│   │   └── _50_todo_init.py            # initialize todo list on chat start
│   └── message_loop_prompts_after/
│       └── _50_todo_inject.py          # inject todo into every prompt
└── prompts/
    └── agent.system.tool.todo_manager.md  # LLM tool description
```

## How It Works

1. **On agent init** (`_50_todo_init.py`): Checks if a todo list exists for the current chat. If not, injects a system instruction prompting the agent to create an initial todo list using the `todo_manager` tool.

2. **Every message loop** (`_50_todo_inject.py`): Reads the current chat's todo JSON and appends a formatted block to the agent's prompt — always keeping the task list visible.

3. **The `todo_manager` tool**: The agent calls this with actions:
   - `create` — build the initial list (10–50 tasks)
   - `start` — mark a task as `started`
   - `complete` — mark a task as `completed`
   - `block` — mark a task as `blocked` with a reason
   - `add` — add a new task
   - `list` — retrieve the current list

## Task JSON Schema

```json
{
  "chat_id": "abc123",
  "created_at": "2026-05-04T10:00:00Z",
  "tasks": [
    {
      "id": 1,
      "title": "Research the topic",
      "status": "completed",
      "created_at": "2026-05-04T10:00:00Z",
      "updated_at": "2026-05-04T10:05:00Z",
      "blocked_reason": null
    }
  ]
}
```

## Valid State Transitions

```
queued → started
started → completed
started → blocked
blocked → started   (unblock/retry)
```

Any other transition is rejected with an error message, preventing the agent from looping.

## License

MIT
