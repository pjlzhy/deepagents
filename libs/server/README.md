# deepagents-server

`deepagents-server` is the planned HTTP server package for the Deep Agents monorepo.

## Current scope

This package currently provides:

- A standalone package skeleton under `libs/server`
- A lightweight `python -m deepagents_server` entry point
- A placeholder health check route at `GET /healthz`
- A shared `ExecutionService` with sync and streaming run APIs for non-UI orchestration
- No runtime dependency on `deepagents-cli` or `textual` for the health route; the CLI-backed runtime adapter is loaded lazily

## Quick start

```bash
cd libs/server
python -m deepagents_server --host 127.0.0.1 --port 8080
```

Then call the health endpoint:

```bash
curl http://127.0.0.1:8080/healthz
```

Expected response:

```json
{"status":"ok"}
```

## Design notes

- The server skeleton intentionally uses only the Python standard library for the health route.
- Future issues will add runtime execution, schema validation, thread state, streaming, and tests.
- The package boundary follows `docs/cli_http_server_boundary.md`.

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
