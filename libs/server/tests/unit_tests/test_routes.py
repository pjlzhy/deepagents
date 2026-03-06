from __future__ import annotations

import json

from deepagents_server.app import AppResponse, ServerApp, create_app
from deepagents_server.runtime import ExecutionResult, RuntimeEvent
from deepagents_server.state import InMemoryThreadStore


class FakeExecutionService:
    async def run(self, request):
        return ExecutionResult(
            assistant_id=request.assistant_id,
            thread_id=request.thread_id or "thread-routes-1",
            model=request.model,
            output="done",
        )

    async def stream(self, request):
        yield RuntimeEvent(
            type="message.delta",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-routes-1",
                "model": request.model,
                "text": "chunk",
            },
        )
        yield RuntimeEvent(
            type="run.completed",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-routes-1",
                "model": request.model,
                "output": "chunk",
            },
        )


def _create_app() -> ServerApp:
    return create_app(
        execution_service=FakeExecutionService(),
        thread_store=InMemoryThreadStore(generate_thread_id=lambda: "thread-routes-1"),
    )


def _decode_json(response: AppResponse) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


def test_get_thread_returns_created_record() -> None:
    app = _create_app()
    app.handle_request(
        "POST",
        "/v1/threads",
        body=b'{"assistant_id":"assistant-routes","model":"gpt-4.1"}',
    )

    response = app.handle_request("GET", "/v1/threads/thread-routes-1")

    assert response.status_code == 200
    assert _decode_json(response)["assistant_id"] == "assistant-routes"


def test_unknown_thread_returns_404() -> None:
    app = _create_app()

    response = app.handle_request("GET", "/v1/threads/missing-thread")

    payload = _decode_json(response)
    assert response.status_code == 404
    assert payload["error"] == "not_found"


def test_run_route_rejects_invalid_json() -> None:
    app = _create_app()
    app.handle_request(
        "POST",
        "/v1/threads",
        body=b'{"assistant_id":"assistant-routes"}',
    )

    response = app.handle_request(
        "POST",
        "/v1/threads/thread-routes-1/runs",
        body=b'{"input":',
    )

    payload = _decode_json(response)
    assert response.status_code == 400
    assert payload["error"] == "invalid_json"


def test_run_route_rejects_unknown_fields() -> None:
    app = _create_app()
    app.handle_request(
        "POST",
        "/v1/threads",
        body=b'{"assistant_id":"assistant-routes"}',
    )

    response = app.handle_request(
        "POST",
        "/v1/threads/thread-routes-1/runs",
        body=b'{"input":"hello","unexpected":true}',
    )

    payload = _decode_json(response)
    assert response.status_code == 422
    assert payload["error"] == "validation_error"
