# HTTP Server MVP Backlog and Phase Gates

This document tracks advanced server capabilities that are intentionally excluded from the first HTTP server MVP.

Any request that expands the server beyond the MVP boundary below must first update the active plan or the current `issues/*.csv` snapshot before implementation starts.

## Scope gates

| Capability | Entry gate | Explicit non-goal for MVP | Impact on MVP if deferred |
| --- | --- | --- | --- |
| Approval callbacks | A stable remote approval API contract and a non-UI state machine that can resume runs across client disconnects | Reproducing the CLI approval widgets, keyboard flow, or terminal state machine over HTTP | MVP continues to expose only current HITL semantics through runtime events; remote approval UX is postponed |
| File upload and download APIs | Storage contract, size limits, virus scanning policy, and lifecycle ownership for temporary artifacts | Ad-hoc multipart endpoints or direct filesystem exposure from the server process | MVP remains text-first; tools must continue to rely on existing local/runtime access patterns |
| Skills management APIs | Server-safe CRUD semantics for built-in, user, and project skill scopes with conflict resolution rules | Remote skill browsing, editing, or deletion endpoints without a reviewed scope model | MVP can reuse configured skills during execution, but administration stays in CLI and repo workflows |
| Authentication and authorization | Chosen authn/authz model, credential transport, tenant boundaries, and error semantics across all routes | Implicit trust of every caller or ad-hoc headers that are not enforced consistently | MVP is suitable only for trusted local or internal development environments |
| Deployment images and packaging | Release process, base image hardening, runtime dependency audit, and configuration story for containerized startup | Shipping an unofficial container or background service template without support guarantees | MVP remains a local package and development-time server entry point |
| Observability | Agreed logs, metrics, tracing, and redaction policy that preserve privacy and correlate `thread_id`/`run_id` safely | Promise of production telemetry or permanent request history without reviewed storage rules | MVP keeps lightweight logs and test evidence only; production monitoring is deferred |

## Review gates

Before any backlog item moves into implementation, confirm all of the following:

1. The change is captured in the current plan or `issues/*.csv` snapshot.
2. The API contract names still preserve `assistant_id`, `thread_id`, `run_id`, and `model` semantics.
3. The proposal does not pull Textual, terminal rendering, or CLI-only UI state into `libs/server`.
4. The README and boundary documents are updated in the same change.

## Current MVP posture

- The server MVP focuses on health checks, thread lifecycle, sync runs, SSE streaming, and runtime configuration defaults.
- Backlog items above are excluded even if nearby CLI functionality already exists.
- Later work may promote an item only after the entry gate is satisfied and scope is re-baselined.
