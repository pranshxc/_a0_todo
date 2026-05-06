# a0-plugin-todo

Per-chat work-order task tracker for [Agent Zero](https://github.com/agent0ai/agent-zero), with **automatic utility-model tracking** in v3.

## The Problem (Before v3)

Every `start`, `complete`, and `check_done` call was done by the **main chat model** — meaning 70k+ input tokens were billed just to update a task status JSON file. A 49-task session like a DNS recon would make 100+ such calls, each consuming the full context.

## How v3 Works

```
Main model:  create todo list once at start
             block/unblock if a task is blocked
             give final response when done
             ← that's it

Utility model (tiny, cheap):  
  [message_loop_end]   after every agent response/tool call:
                       reads last 2000 chars of response
                       reads active tasks list
                       infers what started/completed
                       updates JSON silently
                       logs to sidebar only

  [monologue_end]      after the full turn:
                       reads current topic messages
                       catches any missed transitions
                       logs final stats
```

## Token Cost Comparison

| Operation | v2 (manual) | v3 (automatic) |
|---|---|---|
| Mark task started | 70k+ main tokens | ~300 utility tokens |
| Mark task completed | 70k+ main tokens | ~300 utility tokens |
| 49-task session (100 updates) | ~7M input tokens | ~30k utility tokens |
| Main model role | Do work + manage todo | Do work only |

## File Structure

```
extensions/python/
  monologue_start/_50_todo_bootstrap.py    # create list instruction (once)
  message_loop_prompts_after/_50_todo_inject.py  # compact status in context
  message_loop_end/_55_todo_auto_tracker.py      # utility model tracker (per call)
  monologue_end/_55_todo_final_check.py          # utility model final pass

tools/
  todo_manager.py   # manual escape hatch (create, add, block, unblock, list)
```

## Installation

```bash
cd /a0/agent-zero/plugins
git clone https://github.com/pranshxc/a0-plugin-todo
docker restart agent-zero
```

## What the Agent Sees

The agent only needs to:
1. Call `todo_manager(action=create, tasks=[...])` once at the start
2. Do the actual work
3. Call `todo_manager(action=block/unblock)` only if stuck
4. Give the final response when done

Everything else is automatic.
