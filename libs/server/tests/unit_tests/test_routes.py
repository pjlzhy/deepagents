from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from deepagents_server.app import create_app
from deepagents_server.config import RuntimeDefaults
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


class RecordingExecutionService(FakeExecutionService):
    def __init__(self) -> None:
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return await super().run(request)


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


def test_run_route_injects_thread_runtime_defaults() -> None:
    service = RecordingExecutionService()
    thread_store = InMemoryThreadStore(
        generate_thread_id=lambda: "thread-routes-config",
        default_runtime_defaults=RuntimeDefaults(
            checkpointer_backend="memory",
            enable_memory=True,
            enable_skills=True,
        ),
    )

    with TestClient(create_app(execution_service=service, thread_store=thread_store)) as client:
        create_response = client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-routes","model":"gpt-4.1"}',
        )
        run_response = client.post(
            "/v1/threads/thread-routes-config/runs",
            content=b'{"input":"hello"}',
        )

    assert create_response.status_code == 201
    assert run_response.status_code == 200
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.thread_id == "thread-routes-config"
    assert request.checkpointer_backend == "memory"
    assert request.enable_memory is True
    assert request.enable_skills is True
    assert request.run_id is not None
    assert request.run_id.startswith("run_")
