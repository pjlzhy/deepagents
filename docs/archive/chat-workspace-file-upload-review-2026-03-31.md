# Chat Workspace File Upload Review

> Status: implemented, pending code review
> Last updated: 2026-03-31
> Scope: chat workspace upload flow, thread-scoped workspace contract, runtime-backed file staging

## 1. Goal

This change adds file upload to the chat workspace with the following user flow:

1. User selects an agent and optionally an existing thread in the chat page.
2. User clicks `Upload` in the chat composer action row, selects one or more files, and waits for upload completion.
3. User describes what the uploaded file is and how the agent should use it in the composer text area.
4. User clicks `Send` and the agent replies with access to the uploaded files.

The upload entry is intentionally placed in the chat composer row beside `Cancel` and `Send`, not in top-level page chrome.

## 2. Contract Change

The main change is that workspace behavior is now enforced by the runtime rather than left to prompt compliance alone.

### Before

- Filesystem prompt told the model that workspace lived under `/workspace`.
- Shell commands still started in the agent runtime root.
- Uploaded files landing under `runtime/workspace/...` were not guaranteed to be visible to naive shell usage like `ls` or `cat file.txt`.
- `local` mode mixed two different absolute-path semantics:
  - file tools used virtual-root semantics
  - shell used host absolute-path semantics

### After

- File tools now use explicit virtual roots:
  - `/workspace/...`
  - `/memory/...`
  - `/skills/...`
  - `/conversation_history/...`
- Shell commands start in the current thread workspace.
- Relative shell paths are now the portable contract for uploaded/generated workspace files.
- Workspace and conversation-history storage are thread-scoped.
- Workspace uploads are staged by the runtime itself rather than by northbound prompt tricks.

## 3. Runtime Design

### 3.1 Thread-scoped backend adapter

Added `ThreadScopedRuntimeBackend` in [runtime_backend.py](/D:/open_project/deepagents/libs/runtime/deepagents-runtime/deepagents_runtime/runtime_backend.py).

Responsibilities:

- Route file operations to explicit visible prefixes.
- Bind shell execution to the current thread workspace.
- Keep `memory` and `skills` agent-scoped.
- Keep `workspace` and `conversation_history` thread-scoped.

Two construction paths are supported:

- `for_local(...)`
  - uses local filesystem-backed routes
  - shell `cwd` is bound to `runtime/workspace/<thread_id>`
- `for_container(...)`
  - keeps file and shell paths in the same container namespace
  - shell runs as `cd <thread workspace> && <command>`

### 3.2 Registry layout

The registry still keeps the agent runtime root under `runtime/`, but thread-specific helpers were added in [registry.py](/D:/open_project/deepagents/libs/runtime/deepagents-runtime/deepagents_runtime/registry.py):

- `thread_workspace_dir(name, thread_id)`
- `thread_history_dir(name, thread_id)`

Current physical layout:

```text
runtime/
  memory/AGENTS.md
  skills/
  workspace/
    <thread_id>/
  conversation_history/
    <thread_id>/
```

### 3.3 RuntimeAgent changes

Updated [agent.py](/D:/open_project/deepagents/libs/runtime/deepagents-runtime/deepagents_runtime/agent.py) to:

- build an `AgentFilesystemView` that separates:
  - host runtime root
  - host workspace root
  - host history root
  - backend root path for container-backed execution
- expose explicit virtual visible paths:
  - `/workspace`
  - `/memory/AGENTS.md`
  - `/skills`
  - `/conversation_history`
- assemble with `ThreadScopedRuntimeBackend` instead of exposing raw `LocalShellBackend` directly to agent tools
- bind the current thread workspace before each run
- provide `upload_workspace_files(...)` for runtime-managed staging

The execute approval description was also changed to stop showing `Path.cwd()` from the host process and instead report `current thread workspace`.

## 4. Southbound Protocol

Added workspace upload RPCs to [runtime.proto](/D:/open_project/deepagents/proto/runtime.proto):

- `UploadWorkspaceFiles(UploadWorkspaceFilesRequest) returns (UploadWorkspaceFilesResponse)`

Added messages:

- `UploadWorkspaceFile`
- `UploadWorkspaceFilesRequest`
- `UploadWorkspaceFileResult`
- `UploadWorkspaceFilesResponse`

Generated artifacts were updated for:

- Go control stubs
- Python runtime stubs

## 5. Control Plane Changes

### 5.1 Domain and southbound client

Added workspace upload request/response models in [runtime.go](/D:/open_project/deepagents/libs/control/pkg/domain/runtime.go).

Extended `ResourceSyncClient` in [client.go](/D:/open_project/deepagents/libs/control/pkg/runtimeclient/client.go) with:

- `UploadWorkspaceFiles(ctx, req)`

Implemented gRPC request/response mapping in:

- [grpc_mapper.go](/D:/open_project/deepagents/libs/control/pkg/runtimeclient/grpc_mapper.go)
- [grpc_client.go](/D:/open_project/deepagents/libs/control/pkg/runtimeclient/grpc_client.go)

### 5.2 Orchestrator behavior

Added `UploadWorkspaceFiles(...)` to [service.go](/D:/open_project/deepagents/libs/control/pkg/orchestrator/service.go).

Behavior:

- validates `agent_name`
- calls `EnsureRunnable` first
- delegates upload to the runtime via `ResourceSync`

This keeps upload behavior aligned with the assembled runtime contract rather than assuming local control-plane disk access.

### 5.3 Northbound HTTP API

Added a new northbound endpoint in [http_handler.go](/D:/open_project/deepagents/libs/control/pkg/api/http_handler.go):

- `POST /api/v1/agents/{agent}/workspace/files`

Request:

- multipart form
- `files` repeated file parts
- optional `thread_id`

Response:

- resolved `thread_id`
- per-file results including visible workspace path and error code

Important behavior:

- filenames are normalized with `filepath.Base(...)`
- upload requires at least one file
- if no `thread_id` is supplied, runtime may generate one and return it

## 6. UI Changes

Updated the chat page in [index.tsx](/D:/open_project/deepagents/libs/control/ui/src/pages/chat/index.tsx).

### Composer interaction

- Added a hidden `<input type="file" multiple>`
- Added `Upload` button beside `Cancel` and `Send`
- Disabled upload while a run is active
- Disabled send while files are currently uploading

### Upload behavior

- Uses new control client API from [controlClient.ts](/D:/open_project/deepagents/libs/control/ui/src/shared/api/controlClient.ts)
- Sends selected files to `POST /api/v1/agents/{agent}/workspace/files`
- Reuses current `thread_id` when available
- If runtime returns a new `thread_id`, UI navigates to that thread route
- Displays uploaded workspace file tags above the composer

### API types

Added upload response DTOs in [api.ts](/D:/open_project/deepagents/libs/control/ui/src/shared/types/api.ts).

## 7. Review Focus

Suggested review order:

1. Southbound contract
   - [runtime.proto](/D:/open_project/deepagents/proto/runtime.proto)
   - generated Go/Python stubs
2. Runtime filesystem semantics
   - [runtime_backend.py](/D:/open_project/deepagents/libs/runtime/deepagents-runtime/deepagents_runtime/runtime_backend.py)
   - [agent.py](/D:/open_project/deepagents/libs/runtime/deepagents-runtime/deepagents_runtime/agent.py)
   - [registry.py](/D:/open_project/deepagents/libs/runtime/deepagents-runtime/deepagents_runtime/registry.py)
3. Control upload path
   - [service.go](/D:/open_project/deepagents/libs/control/pkg/orchestrator/service.go)
   - [grpc_client.go](/D:/open_project/deepagents/libs/control/pkg/runtimeclient/grpc_client.go)
   - [http_handler.go](/D:/open_project/deepagents/libs/control/pkg/api/http_handler.go)
4. Chat UX
   - [index.tsx](/D:/open_project/deepagents/libs/control/ui/src/pages/chat/index.tsx)

Main questions to review:

- Is thread-scoped workspace the right storage scope for chat uploads?
- Is `EnsureRunnable` on upload the right behavior, or should upload be allowed before assembly?
- Is `filepath.Base(...)` sufficient for filename normalization on the northbound HTTP boundary?
- Do we want richer upload UI later:
  - remove uploaded file from pending list
  - show upload error per file
  - drag/drop
  - folder upload

## 8. Known Boundaries

### 8.1 Local shell absolute paths remain host-native

This change intentionally does **not** make `local` shell absolute paths behave like virtual `/workspace/...` paths.

Contract is now:

- file tools use explicit virtual prefixes
- shell uses current thread workspace as `cwd`
- relative shell paths are the portable contract
- shell absolute paths remain backend-native:
  - host paths in `local`
  - container paths in `docker`

### 8.2 Upload path nesting is intentionally minimal for now

Current northbound upload accepts raw files and stores them by filename under the thread workspace. There is no directory-upload protocol yet.

### 8.3 Current chat UI does not auto-generate user prompt text

Upload only stages files and shows them in the composer area. The user still needs to describe what the file is and how the agent should use it before clicking `Send`.

## 9. Verification

The following commands were run after implementation:

```bash
go test ./pkg/api ./pkg/orchestrator ./pkg/runtimeclient
```

```bash
uv run --project libs/runtime/deepagents-runtime pytest \
  tests/unit_tests/test_runtime_agent_sandbox_lifecycle.py \
  tests/unit_tests/test_manager_runtime_agent.py \
  tests/unit_tests/test_server_hitl.py \
  tests/unit_tests/test_server_health.py \
  tests/unit_tests/test_docker_sandbox_backend.py \
  tests/unit_tests/test_proto_codegen.py
```

```bash
uv run --project libs/runtime/deepagents-runtime ruff check \
  deepagents_runtime/agent.py \
  deepagents_runtime/entry/server.py \
  deepagents_runtime/manager/manager.py \
  deepagents_runtime/registry.py \
  deepagents_runtime/runtime_backend.py \
  tests/unit_tests/test_runtime_agent_sandbox_lifecycle.py \
  tests/unit_tests/test_manager_runtime_agent.py
```

```bash
pnpm exec tsc --noEmit
```

## 10. Review Notes

- Existing untracked items `libs/control/control.exe` and `libs/control/.deepagents-control/` are unrelated to this feature.
- This review note documents the implemented state as of 2026-03-31, not a future design target.
