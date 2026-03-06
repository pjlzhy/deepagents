# deepagents-server

`deepagents-server` is the planned HTTP server package for the Deep Agents monorepo.

## Current scope

This package currently provides:

- A standalone package skeleton under `libs/server`
- A lightweight `python -m deepagents_server` entry point
- A FastAPI-based HTTP application served by `uvicorn`
- A health check route at `GET /healthz`
- A shared `ExecutionService` with sync and streaming run APIs for non-UI orchestration
- No runtime dependency on `deepagents-cli` or `textual` for the health route; the CLI-backed runtime adapter is loaded lazily

## Quick start

```bash
cd libs/server
uv run --project . python -m deepagents_server --host 127.0.0.1 --port 8080 --checkpointer-backend local
```

Then call the health endpoint:

```bash
curl http://127.0.0.1:8080/healthz
```

Expected response:

```json
{"status":"ok"}
```

## Environment variables

The MVP package does not define any server-specific environment variables yet.

- Bind settings come from the CLI flags `--host` and `--port`
- Runtime defaults can also set `--checkpointer-backend` (`local` or `memory`) and `--sandbox-type` (`none` only in the MVP server)
- Runtime execution inherits the process environment of the launched server
- If the CLI-backed runtime reads existing `deepagents-cli` environment variables, the server sees the same values because it runs in the same process environment

## API examples

Create a thread:

```bash
curl -X POST http://127.0.0.1:8080/v1/threads \
  -H "Content-Type: application/json" \
  -d '{"assistant_id":"assistant-alpha","model":"gpt-5"}'
```

Fetch a thread:

```bash
curl http://127.0.0.1:8080/v1/threads/thread_123
```

Run a synchronous request:

```bash
curl -X POST http://127.0.0.1:8080/v1/threads/thread_123/runs \
  -H "Content-Type: application/json" \
  -d '{"input":"Say hello","assistant_id":"assistant-alpha","model":"gpt-5"}'
```

Run a streaming request:

```bash
curl -N -X POST http://127.0.0.1:8080/v1/threads/thread_123/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"input":"Say hello","assistant_id":"assistant-alpha","model":"gpt-5"}'
```

## Validation

Run the server package checks from `libs/server`:

```bash
uv run --project . --group test pytest tests/unit_tests/test_config.py tests/unit_tests/test_schemas.py tests/unit_tests/test_app.py tests/unit_tests/test_routes.py tests/unit_tests/test_runtime.py tests/unit_tests/test_server.py
uv run --project . --group test ruff check deepagents_server tests README.md
uv run --project . --group test ty check deepagents_server tests
```

## Design notes

- The HTTP transport now uses FastAPI plus `uvicorn`, while request validation and runtime orchestration stay in local modules.
- New threads inherit a session context that carries `thread_id`, per-thread runtime defaults, optional injected checkpointer, and the generated `run_id` used for each execution.
- The MVP test matrix covers config parsing, request schema validation, runtime service behavior, HTTP routes, SSE streaming, and uvicorn-backed server smoke checks.
- The package boundary follows `docs/cli_http_server_boundary.md`.

## Known limitations

- The only persistence mode today is the in-memory thread store in `deepagents_server.state`
- Execution requests can reuse either the CLI-backed local checkpointer or an in-process memory backend, but unsupported sandbox providers fail fast with a clear error
- The CLI-backed runtime adapter is still a local-process integration, not a standalone remote execution service
- Approval callbacks, file upload and download APIs, authentication, deployment packaging, and observability are not part of the MVP
- Health checks are dependency-light, but runtime execution still requires the CLI-backed dependencies to be importable in the same environment

## Differences from the CLI

- The server exposes JSON and SSE contracts only; it does not render Textual or terminal UI state
- Thread lifecycle is explicit through `POST /v1/threads` and `GET /v1/threads/{thread_id}` instead of interactive CLI session controls
- Health checks and HTTP startup must not import `deepagents_cli.app` or `textual` at runtime
- CLI-only features such as approval UI presentation and terminal-focused affordances remain out of scope for the server MVP

## Streaming contract

`POST /v1/threads/{thread_id}/runs/stream` returns Server-Sent Events where the SSE `event:` name and
the JSON `type` field match. Every streamed frame uses the same envelope:

```json
{
  "type": "message.delta",
  "run_id": "run_123",
  "thread_id": "thread_123",
  "sequence": 2,
  "timestamp": "2026-03-07T10:00:00.000000Z",
  "payload": {
    "assistant_id": "assistant-alpha",
    "model": "gpt-5",
    "text": "hello"
  }
}
```

The current MVP stream supports these event types:

- `run.started`
- `message.delta`
- `tool.call`
- `tool.result`
- `interrupt.required`
- `message.completed`
- `thread.updated`
- `run.completed`
- `run.failed`

Within a single run, `sequence` is strictly increasing, `run.completed` and `run.failed` are mutually
exclusive, and runtime exceptions are translated into a terminal `run.failed` event.
