# Browser Deep Agents CLI Architecture

## Status

Draft design for a local-first browser version of `deepagents-cli`.

## Summary

The goal is to build a browser UI for the current Deep Agents CLI without
dropping any meaningful CLI behavior. The browser should become a new client
surface, not a forked implementation with a narrower capability set.

The safest path is:

1. Keep `libs/deepagents` as the core SDK and graph assembly layer.
2. Extract shared runtime logic out of `libs/cli`.
3. Reuse that runtime from both the existing Textual app and a new web server.
4. Add a browser client on top of the server.

This keeps current CLI semantics intact while making future clients easier to
add.

## Goals

- Reach feature parity with the current interactive CLI.
- Preserve local-first behavior for workspace access, shell, skills, and
  `AGENTS.md`.
- Avoid duplicating business logic across Textual and web clients.
- Leave room for future clients such as desktop wrappers or editor plugins.
- Preserve current public SDK behavior in `libs/deepagents`.

## Non-goals

- Multi-tenant hosted product in the first phase.
- Replacing the current CLI.
- Breaking `deepagents.create_deep_agent()` or other current SDK entry points.
- Introducing browser-only behavior that weakens current safety or approval
  semantics.
- Building a PTY-grade terminal emulator in v1.

## Product framing

The initial product is a browser version of `deepagents-cli`, not a hosted
agent platform.

That means the backend process should run close to the user's workspace and
keep the same assumptions the CLI already relies on:

- local filesystem access
- local shell access
- local `~/.deepagents` state
- project-local `.deepagents/` and `.agents/` directories
- local skills and subagents discovery
- optional remote sandbox providers on top of the local control plane

## Current CLI capability inventory

The browser version must cover all of the following capability groups.

### Interactive run loop

- Streaming assistant output
- Tool call timeline and tool output rendering
- Human-in-the-loop approvals
- Per-thread auto-approve state
- Interrupt and cancellation
- Queued user messages while a run is active
- Session usage stats

Current implementation is spread across:

- `deepagents_cli.agent.create_cli_agent()`
- `deepagents_cli.textual_adapter.TextualUIAdapter`
- `deepagents_cli.app.DeepAgentsApp`

### Threads and persistence

- Generate new thread IDs
- Resume the most recent thread
- Resume a specific thread
- List threads
- Delete threads
- Switch threads mid-session
- Load history from checkpoint state
- Build LangSmith trace links

Current implementation is spread across:

- `deepagents_cli.sessions`
- `deepagents_cli.app`
- `deepagents_cli.main`

### Agent configuration

- Agent selection via `--agent`
- Agent reset and `AGENTS.md` management
- Model selection and hot-swap
- Default model management
- Recent model persistence
- Provider auto-detection
- `--profile-override`
- `--model-params`

Current implementation is spread across:

- `deepagents_cli.main`
- `deepagents_cli.config`
- `deepagents_cli.model_config`
- `deepagents_cli.app`

### Workspace interactions

- File mention parsing with `@filename`
- File path paste parsing
- Image and video attachments
- Direct `!command` shell execution
- Local context middleware

Current implementation is spread across:

- `deepagents_cli.input`
- `deepagents_cli.media_utils`
- `deepagents_cli.textual_adapter`
- `deepagents_cli.app`
- `deepagents_cli.local_context`

### Agent tools and approvals

- Local file access
- Local shell execution
- Web search
- URL fetch
- HTTP request
- Subagent `task` calls
- Approval prompts for tool calls
- Allow-list based shell auto-approval

Current implementation is spread across:

- `deepagents_cli.agent`
- `deepagents_cli.tools`
- `deepagents_cli.config`
- `deepagents_cli.widgets.approval`

### Skills and subagents

- Discover built-in, user, and project skills
- Create, inspect, and delete skills
- Load custom subagents from filesystem
- Respect precedence across user and project directories

Current implementation is spread across:

- `deepagents_cli.skills.commands`
- `deepagents_cli.skills.load`
- `deepagents_cli.subagents`
- `deepagents.middleware.skills`
- `deepagents.middleware.subagents`

### Sandboxes

- Local mode
- `modal`, `daytona`, `runloop`, `langsmith` sandboxes
- Sandbox setup scripts
- Reuse an existing sandbox by ID

Current implementation is spread across:

- `deepagents_cli.integrations.sandbox_factory`
- provider-specific integrations under `deepagents_cli.integrations`
- `deepagents_cli.main`

### Headless execution

- `-n` non-interactive runs
- `--quiet`
- `--no-stream`
- headless approval handling
- shell allow-list behavior in headless mode

Current implementation is spread across:

- `deepagents_cli.non_interactive`
- `deepagents_cli.main`

### Slash commands and UI affordances

- `/help`
- `/clear`
- `/compact`
- `/model`
- `/remember`
- `/tokens`
- `/threads`
- `/trace`
- `/docs`
- `/changelog`
- `/feedback`
- `/version`

Status (as of 2026-03-10): slash command parsing and execution are shared via
`deepagents_runtime.commands`, and `deepagents_cli.app` executes the resulting
UI-neutral runtime actions (instead of owning command semantics).

## Architectural direction

The CLI currently mixes three layers:

1. Runtime behavior
2. Client behavior
3. Textual rendering

The browser effort should separate them.

### Layer 1: SDK

`libs/deepagents` remains the lowest layer. It should continue to own:

- graph assembly
- middleware contracts
- backend protocols
- subagent middleware
- skills middleware
- memory middleware
- summarization middleware

This layer should stay UI-agnostic.

### Layer 2: shared app runtime

Introduce a new shared Python package for product-level runtime logic.

Suggested package:

- path: `libs/runtime/`
- package name: `deepagents_runtime`

This package would own behavior that is currently specific to the product but
should not remain specific to Textual.

Suggested modules:

- `deepagents_runtime.agent_factory`
  - wraps current `create_cli_agent()`
  - assembles tools, middleware, subagents, sandboxes, and system prompt
- `deepagents_runtime.sessions`
  - wraps thread storage, IDs, listing, deletion, history hydration, trace URL
- `deepagents_runtime.runs`
  - run orchestration for normal agent messages, slash commands, and direct
    shell commands
- `deepagents_runtime.shell`
  - direct `!command` subprocess execution helpers and output formatting
- `deepagents_runtime.events`
  - canonical event schema used by all clients
- `deepagents_runtime.approvals`
  - pending approval lifecycle and resume handling
- `deepagents_runtime.workspace`
  - workspace root, agent directories, skills directories, subagent discovery,
    and local context helpers
- `deepagents_runtime.inputs`
  - normalized input envelopes with text, attachments, and mode
- `deepagents_runtime.commands`
  - slash command routing and command handlers
- `deepagents_runtime.models`
  - model resolution, default model, recent model, provider detection
- `deepagents_runtime.sandboxes`
  - provider-agnostic sandbox lifecycle

### Layer 3: clients

Each client becomes a thin renderer around the shared runtime.

Initial clients:

- Textual client in `libs/cli`
- FastAPI server package for web access
- Browser frontend

## Proposed repository shape

One reasonable target shape is:

```txt
deepagents/
|-- libs/
|   |-- deepagents/          # SDK, unchanged role
|   |-- runtime/             # shared runtime for CLI and web
|   |-- cli/                 # Textual client only
|   `-- web/                 # FastAPI server
`-- apps/
    `-- web/                 # browser frontend
```

If introducing `apps/` is too much in the first pass, the server can land
first and the browser frontend can be added later. The important part is that
the runtime extraction happens before the browser client becomes large.

## Core design choices

### 1. Keep local-first control plane

The browser should talk to a local Python service bound to the user's active
workspace.

Benefits:

- preserves filesystem and shell semantics
- preserves `~/.deepagents` state
- avoids inventing a remote workspace abstraction too early
- makes skill and subagent discovery continue to work
- keeps current security boundaries understandable

### 2. Version a shared event protocol

The browser and Textual clients should both consume the same event stream.

This event protocol should be the stable seam between runtime and clients.

### 3. Move command semantics out of Textual

Today slash commands are interpreted inside `DeepAgentsApp`. That makes the
Textual app the owner of product behavior.

The shared runtime should instead own command parsing and command execution.
Textual and browser clients should only collect input and render the results.

### 4. Preserve the current `InputMode`

The current CLI has three modes:

- `normal`
- `command`
- `bash`

These map cleanly to a client-neutral input envelope and should be preserved.

### 5. Treat direct `!command` as first-class runtime behavior

The current `!command` path is not a PTY. It is a direct shell command runner
with buffered output and a timeout. The browser can preserve that exact
behavior in v1.

A richer terminal emulator can be added later as a separate feature.

## Input model

Both Textual and browser clients should send a normalized input envelope.

Suggested shape:

```json
{
  "thread_id": "abcd1234",
  "mode": "normal",
  "text": "summarize @README.md",
  "attachments": [
    {
      "kind": "file",
      "path": "/abs/path/README.md",
      "inject": true
    },
    {
      "kind": "image",
      "name": "diagram.png",
      "data_url": "data:image/png;base64,..."
    }
  ]
}
```

Rules:

- `mode=normal` routes to the agent.
- `mode=command` routes to slash command handling.
- `mode=bash` routes to direct shell execution.
- `attachments` should allow browser-native uploads without forcing the web
  client to emulate terminal paste behavior.
- `@file` parsing should remain supported for parity and convenience.

## Event protocol

### Event envelope

Suggested envelope:

```json
{
  "schema_version": 1,
  "event_id": "evt_123",
  "run_id": "run_123",
  "thread_id": "abcd1234",
  "timestamp": "2026-03-09T15:00:00Z",
  "type": "assistant.delta",
  "payload": {}
}
```

### Required event types

Agent run events:

- `run.started`
- `run.completed`
- `run.failed`
- `run.cancelled`

User and assistant message events:

- `message.user.created`
- `message.assistant.started`
- `message.assistant.delta`
- `message.assistant.completed`

Tool lifecycle events:

- `tool.started`
- `tool.output`
- `tool.completed`
- `tool.failed`

Approval events:

- `approval.requested`
- `approval.resolved`

Direct shell events:

- `bash.started`
- `bash.output`
- `bash.completed`
- `bash.failed`

Thread and session events:

- `thread.created`
- `thread.updated`
- `thread.switched`
- `history.loaded`
- `usage.updated`

Command result events:

- `command.result`
- `command.open_url`

### Notes on parity

- `/docs`, `/changelog`, and `/feedback` should not open a browser from the
  server. They should emit `command.open_url` so the client opens the link.
- `/trace` should resolve the URL server-side and emit a client-consumable URL
  event.
- approval requests must be durable enough to survive browser refresh and
  reconnect.

## Runtime services

### Agent factory service

Extract a client-neutral version of `create_cli_agent()` that:

- resolves model and provider
- loads skills
- loads subagents
- configures local or remote backends
- configures interrupt behavior
- configures memory, skills, local context, and summarization middleware

Textual and web should both call the same function.

### Session service

Wrap existing thread and checkpoint behavior behind a narrow interface:

- `generate_thread_id()`
- `list_threads()`
- `delete_thread()`
- `get_thread_history()`
- `get_most_recent_thread()`
- `get_checkpointer()`
- `build_trace_url()`

This service should continue using the current SQLite-backed checkpoint store
at first.

### Run service

The run service should own:

- invoking the agent
- consuming the `astream()` output
- translating chunks into canonical runtime events
- pausing for approvals
- resuming after decisions
- surfacing usage stats

The existing logic in `textual_adapter.py` and `non_interactive.py` should be
merged into this service instead of maintained separately.

### Approval service

Approval state should move out of widget-local state into a runtime-managed
object keyed by `run_id` and `thread_id`.

It should support:

- approve
- reject
- auto-approve for the current thread

The runtime should persist enough state to recover from client reconnects.

### Command service

Slash commands should become runtime handlers, not Textual-only methods.

Current status (Phase 1, complete):

- `deepagents_runtime.commands` now owns slash command routing and returns
  UI-neutral actions for: `/quit`, `/help`, `/clear`, `/compact`, `/threads`,
  `/model` (selector + switching + default management), `/remember`, `/version`,
  `/tokens`, `/trace`, `/docs`, `/changelog`, `/feedback`, plus an unknown
  command fallback.
- `deepagents_cli.app` now focuses on executing those actions:
  - Textual-specific UI (model/thread selector screens, Rich rendering)
  - side effects (webbrowser opens, model persistence, compaction execution)
- CLI unit tests validate shared parsing/routing through `DeepAgentsApp` for
  `/remember`, `/model` (selector + switch + default usage), `/threads`,
  `/tokens`, `/docs`, and `/clear`.

Suggested command mapping:

- `/help` -> returns command metadata or formatted help payload
- `/clear` -> clear current conversation view and start a new thread
- `/compact` -> execute compaction on the current thread
- `/model` -> list, switch, or update default model
- `/remember` -> send the generated remember prompt through the normal agent path
- `/tokens` -> return current token usage information
- `/threads` -> client usually opens thread UI, but runtime still owns the
  thread listing/switching semantics
- `/trace` -> resolve current LangSmith trace URL
- `/docs`, `/changelog`, `/feedback` -> open URL instructions
- `/version` -> runtime and SDK version info

Commands that are fundamentally UI selectors, such as the model picker or
thread picker, should be split into:

- structured data from the runtime
- rendering and selection in the client

## HTTP API sketch

The first web API can stay simple and local-first.

### Workspace and configuration

- `GET /api/workspace`
  - current workspace root
  - active agent
  - current model
  - sandbox mode
  - capability flags
- `GET /api/models`
  - providers, models, current selection, missing credential hints
- `POST /api/models/switch`
  - switch active model for the current session
- `POST /api/models/default`
  - set or clear default model

### Agents, skills, and subagents

- `GET /api/agents`
- `POST /api/agents/{agent_name}/reset`
- `GET /api/skills`
- `POST /api/skills`
- `GET /api/skills/{skill_name}`
- `DELETE /api/skills/{skill_name}`
- `GET /api/subagents`

### Threads

- `GET /api/threads`
- `POST /api/threads`
- `GET /api/threads/{thread_id}/history`
- `POST /api/threads/{thread_id}/switch`
- `DELETE /api/threads/{thread_id}`
- `GET /api/threads/{thread_id}/trace`

### Runs and approvals

- `POST /api/threads/{thread_id}/inputs`
  - accepts the normalized input envelope
  - returns `run_id`
- `GET /api/runs/{run_id}/events`
  - SSE endpoint
- `POST /api/runs/{run_id}/approval`
  - `{ "decision": "approve" | "reject" | "auto_approve_all" }`
- `POST /api/runs/{run_id}/cancel`

### Thread operations

- `POST /api/threads/{thread_id}/compact`
- `GET /api/threads/{thread_id}/tokens`

### Sandbox lifecycle

- `GET /api/sandboxes`
- `POST /api/sandboxes/connect`
- `POST /api/sandboxes/create`
- `POST /api/sandboxes/{sandbox_id}/setup`
- `DELETE /api/sandboxes/{sandbox_id}`

## Browser UX mapping

The browser UI should preserve semantics while using browser-native affordances.

Suggested layout:

- left rail: threads, agent selection, settings entry points
- center: chat timeline
- right panel: tool timeline, approval cards, token/session stats, run details
- composer: text input, slash command support, `@file` support, attachments

Important parity notes:

- approval cards should behave like the current approval menu and stay visible
  until resolved
- thread switching should preserve the current "load history then continue"
  model
- `/clear` should start a new thread, not just clear the visible DOM
- browser should expose auto-approve as an explicit toggle, not a hidden state
- browser should expose direct `!command` behavior in the same composer for v1

## CLI parity checklist

The browser launch should not be considered complete until all items below are
covered.

### Must-have parity

- Normal chat run loop
- Tool streaming and tool results
- Human-in-the-loop approvals
- Thread creation, resume, switch, delete, and history load
- `!command`
- `/clear`
- `/compact`
- `/remember`
- `/tokens`
- `/trace`
- `/model` including hot-swap
- image and video attachments
- file mention injection
- skills discovery and management
- agent reset and agent selection
- subagent discovery and `task` behavior
- local mode and remote sandbox mode

### Nice-to-have parity before general use

- exact rendering parity for diff and tool display widgets
- browser polish for command shortcuts
- richer file explorer than the terminal offers

### Explicitly deferred from v1

- PTY terminal emulation
- multi-user authentication
- remote hosted workspaces
- collaborative editing

## Migration plan

### Phase 1: runtime extraction

- create `deepagents_runtime`
- move agent assembly, session services, run orchestration, command handling,
  and approvals there
- keep Textual behavior unchanged

Acceptance criteria:

- CLI behavior remains unchanged
- Textual app uses the shared runtime instead of owning core behavior

### Phase 2: server package

- add FastAPI server package
- expose thread, run, approval, model, skill, and agent APIs
- expose SSE stream for run events

Acceptance criteria:

- a local HTTP client can drive an end-to-end agent run with approvals
- thread history and trace URLs are accessible over the API

### Phase 3: browser client

- build browser chat, thread list, approval UI, and model switcher
- implement attachments, slash commands, and direct `!command`

Acceptance criteria:

- browser can fully replace the Textual app for the main chat loop

### Phase 4: parity closure

- close remaining gaps around skills management, sandbox setup, trace actions,
  and command ergonomics
- add regression tests comparing runtime behavior across Textual and web

## Testing strategy

The runtime extraction should make parity testable.

Suggested test layers:

- unit tests for event translation and command routing
- unit tests for approval lifecycle
- unit tests for session service
- integration tests for end-to-end run streaming through the web API
- browser tests for the main approval and thread-switch flows

Important rule:

Behavioral assertions should target the shared runtime first. UI tests should
only validate rendering and client-specific behavior.

## Major risks

### Approval persistence

Today approvals are tightly bound to the Textual widget lifecycle. Web requires
them to survive reconnects and page refreshes.

### Hidden Textual coupling

Some current behavior is implemented in `DeepAgentsApp` methods rather than a
runtime service. This will need deliberate extraction rather than simple reuse.

### Command semantics drift

If the browser re-implements slash commands independently, it will drift from
the CLI quickly. Shared command handlers are required.

### Attachment handling drift

The browser should not try to mimic terminal paste quirks exactly. It should
use the normalized attachment model while preserving the same runtime outcome.

### Sandbox lifecycle and cleanup

Long-lived browser sessions create more opportunities for orphaned sandboxes.
The server should own cleanup semantics, not the browser.

## Recommended first implementation slice

The first slice should be the smallest thing that proves the architecture:

1. Extract shared run orchestration and event protocol.
2. Rewire the current Textual app to consume those runtime events.
3. Expose the same runtime through a local SSE API.
4. Build a browser client that supports:
   - normal chat
   - tool timeline
   - approvals
   - thread list and history
   - model switch
   - direct `!command`

Only after this slice is working should the project move on to skills
management pages, richer file exploration, or browser-native enhancements.
