from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from deepagents_server.app import create_app
from deepagents_server.runtime import ExecutionResult, RuntimeEvent
from deepagents_server.state import InMemoryThreadStore

if TYPE_CHECKING:
    from fastapi import FastAPI


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


def _create_app() -> FastAPI:
    return create_app(
        execution_service=FakeExecutionService(),
        thread_store=InMemoryThreadStore(generate_thread_id=lambda: "thread-routes-1"),
    )


def test_get_thread_returns_created_record() -> None:
    with TestClient(_create_app()) as client:
        client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-routes","model":"gpt-4.1"}',
        )
        response = client.get("/v1/threads/thread-routes-1")

    assert response.status_code == 200
    assert response.json()["assistant_id"] == "assistant-routes"


def test_unknown_thread_returns_404() -> None:
    with TestClient(_create_app()) as client:
        response = client.get("/v1/threads/missing-thread")

    payload = response.json()
    assert response.status_code == 404
    assert payload["error"] == "not_found"


def test_run_route_rejects_invalid_json() -> None:
    with TestClient(_create_app()) as client:
        client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-routes"}',
        )
        response = client.post(
            "/v1/threads/thread-routes-1/runs",
            content=b'{"input":',
        )

    payload = response.json()
    assert response.status_code == 400
    assert payload["error"] == "invalid_json"


def test_run_route_rejects_unknown_fields() -> None:
    with TestClient(_create_app()) as client:
        client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-routes"}',
        )
        response = client.post(
            "/v1/threads/thread-routes-1/runs",
            content=b'{"input":"hello","unexpected":true}',
        )

    payload = response.json()
    assert response.status_code == 422
    assert payload["error"] == "validation_error"
