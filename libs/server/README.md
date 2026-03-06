# deepagents-server

`deepagents-server` is the planned HTTP server package for the Deep Agents monorepo.

## Current scope

This package currently provides:

- A standalone package skeleton under `libs/server`
- A lightweight `python -m deepagents_server` entry point
- A placeholder health check route at `GET /healthz`
- No runtime dependency on `deepagents-cli` or `textual`

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
