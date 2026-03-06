# CLI / SDK / HTTP Server Boundary

## Goal

This document defines the runtime boundary between the existing CLI, the shared SDK/runtime, and the planned HTTP server package. The intent is to reuse execution semantics without pulling Textual, terminal rendering, or approval UI state into `libs/server`.

## Core terminology

The server MVP keeps the existing names used by the CLI runtime so that request schema, thread persistence, and execution metadata do not drift.

| Name | Current meaning | Source of truth | Server rule |
| --- | --- | --- | --- |
| `assistant_id` | Stable agent identity used for prompts, memory, and config lookup | `libs/cli/deepagents_cli/agent.py` | Keep the field name unchanged in request config and metadata |
| `thread_id` | Stable conversation/run context identifier passed through runnable config | `libs/cli/deepagents_cli/non_interactive.py` | Keep the field name unchanged in routes, services, and storage |
| `model` | User-selected model spec or initialized model instance | `libs/deepagents/deepagents/graph.py` and CLI model creation flow | Keep the field name unchanged in request schema and runtime service input |

## Capability matrix

| Capability | CLI interactive | CLI non-interactive | Server MVP | Later server work | Explicitly excluded from server MVP |
| --- | --- | --- | --- | --- | --- |
| Interactive session loop | Owns chat input, layout, widgets, status bars, hotkeys | Not used | Not included | Websocket/UI adapter can be evaluated later | `DeepAgentsApp`, Textual widgets, terminal rendering |
| Non-interactive execution | Shares agent creation but adds console output and CLI exit handling | Primary current execution path | Reuse runtime semantics only | Can grow richer request/response helpers | `Console` formatting, stdout streaming helpers |
| Approval / HITL | Owns approval widgets and key bindings | Uses CLI shell allow-list semantics | Reuse approval semantics, not approval UI | Remote approval flow may be added later | Approval menu state machine, keyboard navigation |
| Skills | Reads user and built-in skills | Enabled when runtime config allows | Included when runtime service can safely pass through skill configuration | Remote skill management | Any UI used to browse or explain skills |
| Memory | Reads/writes assistant memory sources | Enabled when runtime config allows | Included when runtime service can pass through memory configuration | Remote memory admin APIs | Any CLI-only memory presentation |
| Sandbox | CLI creates provider backends and handles local setup ergonomics | Non-interactive path already defines auto-approve/shell semantics | Included only through typed runtime config and explicit provider support | More provider parity | CLI-only setup prompts, provider UX, terminal progress |

## Reuse boundary

### Reuse in server MVP

- Model resolution and deep agent construction in `libs/deepagents`
- CLI runtime semantics around `assistant_id`, `thread_id`, checkpointer wiring, and non-interactive run behavior
- Shared tool and middleware behavior that does not depend on Textual or terminal rendering

### Wrap before reuse

- `create_cli_agent()` may inform the future runtime adapter, but server code should depend on a non-UI service wrapper instead of importing CLI app code directly
- Non-interactive streaming/message conversion should be adapted into typed service and SSE events before exposing it as HTTP
- Session/checkpointer access should move behind a server-safe context object so routes do not know CLI persistence internals

### Do not reuse directly

- `deepagents_cli.app.DeepAgentsApp`
- Any `textual` runtime import, widget, binding, or screen implementation
- Terminal-specific rendering, headers, status messages, and approval menus
- UI-driven state transitions that only exist to support keyboard navigation or alternate-screen rendering

## Dependency rules

- `libs/server` must not import `deepagents_cli.app` at runtime
- `libs/server` must not import `textual` at runtime
- Shared execution helpers consumed by server must remain pure Python modules with no terminal UI dependency
- If a helper needs both CLI and server consumers, extract or wrap it behind a non-UI boundary instead of importing from the Textual app layer

## First-pass implementation path

1. Create `libs/server` as an independent package with lightweight app/config/routes modules.
2. Add a server runtime service that accepts `assistant_id`, `thread_id`, `model`, checkpointer, sandbox, memory, and skills configuration without importing the Textual app.
3. Keep API schema names aligned with CLI/runtime terminology.
4. Add regression tests in the server package to prevent `textual` or `deepagents_cli.app` runtime imports.

## Phase gates

- Advanced capabilities such as approval callbacks, file transfer, authn/authz, deployment packaging, and observability are tracked in `docs/cli_http_server_backlog.md`.
- Changes that cross the current MVP boundary must update the active plan or `issues/*.csv` snapshot before implementation begins.

## Review checklist

- Does the change preserve `assistant_id`, `thread_id`, and `model` naming across route schema and runtime config?
- Does server code depend only on non-UI runtime helpers?
- Did any new import accidentally pull `textual` or `deepagents_cli.app` into server runtime paths?
- Is the server MVP still limited to execution, thread management, and streaming instead of inheriting CLI UI behavior?
