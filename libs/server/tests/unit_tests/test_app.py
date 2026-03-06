import json
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deepagents_server.app import create_app
from deepagents_server.runtime import ExecutionResult, RuntimeEvent
from deepagents_server.state import InMemoryThreadStore


class FakeExecutionService:
    async def run(self, request):
        return ExecutionResult(
            assistant_id=request.assistant_id,
            thread_id=request.thread_id or "thread-missing",
            model=request.model,
            output=f"echo:{request.input}",
        )

    async def stream(self, request):
        yield RuntimeEvent(
            type="message.delta",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-missing",
                "model": request.model,
                "text": "streamed",
            },
        )
        yield RuntimeEvent(
            type="tool.call",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-missing",
                "model": request.model,
                "name": "fetch_url",
                "tool_call_id": "tool-1",
                "index": 0,
            },
        )
        yield RuntimeEvent(
            type="tool.result",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-missing",
                "model": request.model,
                "name": "fetch_url",
                "tool_call_id": "tool-1",
                "content": "ok",
            },
        )
        yield RuntimeEvent(
            type="interrupt.required",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-missing",
                "model": request.model,
                "interrupt_id": "interrupt-1",
                "action_requests": [{"name": "fetch_url", "args": {"url": "https://example.com"}}],
            },
        )
        yield RuntimeEvent(
            type="run.completed",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-missing",
                "model": request.model,
                "output": "streamed",
            },
        )


class FailingExecutionService(FakeExecutionService):
    async def stream(self, request):
        yield RuntimeEvent(
            type="message.delta",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-missing",
                "model": request.model,
                "text": "partial",
            },
        )
        msg = "boom"
        raise RuntimeError(msg)


def _decode_sse_events(raw_body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for chunk in raw_body.strip().split("\n\n"):
        lines = chunk.splitlines()
        event_line = next(line for line in lines if line.startswith("event: "))
        data_line = next(line for line in lines if line.startswith("data: "))
        events.append(
            (
                event_line.removeprefix("event: "),
                json.loads(data_line.removeprefix("data: ")),
            )
        )
    return events


def _event_payload(event: tuple[str, dict[str, object]]) -> dict[str, object]:
    payload = event[1]["payload"]
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _string_field(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    assert isinstance(value, str)
    return value


def _create_test_app(*, execution_service=None) -> FastAPI:
    return create_app(
        execution_service=execution_service or FakeExecutionService(),
        thread_store=InMemoryThreadStore(generate_thread_id=lambda: "thread-test-1"),
    )


def test_health_route_returns_ok() -> None:
    with TestClient(_create_test_app()) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_404() -> None:
    with TestClient(_create_test_app()) as client:
        response = client.get("/missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"] == "not_found"


def test_create_thread_returns_schema_payload() -> None:
    with TestClient(_create_test_app()) as client:
        response = client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-alpha","model":"gpt-5"}',
        )

    payload = response.json()
    assert response.status_code == 201
    assert payload["assistant_id"] == "assistant-alpha"
    assert payload["thread_id"] == "thread-test-1"
    assert payload["model"] == "gpt-5"
    assert payload["run_count"] == 0


def test_invalid_thread_body_returns_422() -> None:
    with TestClient(_create_test_app()) as client:
        response = client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-alpha","assistant_id":"duplicate"}',
        )

    payload = response.json()
    assert response.status_code == 422
    assert payload["error"] == "validation_error"


def test_run_route_returns_output_and_thread_state() -> None:
    with TestClient(_create_test_app()) as client:
        client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-alpha","model":"gpt-5"}',
        )
        response = client.post(
            "/v1/threads/thread-test-1/runs",
            content=b'{"input":"hello"}',
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["assistant_id"] == "assistant-alpha"
    assert payload["thread_id"] == "thread-test-1"
    assert payload["model"] == "gpt-5"
    assert payload["input"] == "hello"
    assert payload["output"] == "echo:hello"
    assert payload["thread"]["run_count"] == 1


def test_stream_route_returns_sse_events() -> None:
    with TestClient(_create_test_app()) as client:
        client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-alpha","model":"gpt-5"}',
        )
        with client.stream(
            "POST",
            "/v1/threads/thread-test-1/runs/stream",
            content=b'{"input":"hello"}',
        ) as response:
            body = "".join(response.iter_text())

    events = _decode_sse_events(body)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [payload["type"] for _, payload in events] == [event_type for event_type, _ in events]
    assert [payload["sequence"] for _, payload in events] == list(range(1, len(events) + 1))
    assert [event_type for event_type, _ in events] == [
        "run.started",
        "message.delta",
        "tool.call",
        "tool.result",
        "interrupt.required",
        "message.completed",
        "thread.updated",
        "run.completed",
    ]
    assert all(_string_field(payload, "run_id").startswith("run_") for _, payload in events)
    assert all(payload["thread_id"] == "thread-test-1" for _, payload in events)
    assert all(_string_field(payload, "timestamp").endswith("Z") for _, payload in events)
    assert _event_payload(events[1])["text"] == "streamed"
    assert _event_payload(events[2])["name"] == "fetch_url"
    assert _event_payload(events[3])["content"] == "ok"
    assert _event_payload(events[4])["interrupt_id"] == "interrupt-1"
    assert _event_payload(events[5])["output"] == "streamed"
    assert _event_payload(events[6])["run_count"] == 1
    assert _event_payload(events[7])["output"] == "streamed"


def test_stream_route_translates_runtime_errors_to_failed_events() -> None:
    with TestClient(_create_test_app(execution_service=FailingExecutionService())) as client:
        client.post(
            "/v1/threads",
            content=b'{"assistant_id":"assistant-alpha","model":"gpt-5"}',
        )
        with client.stream(
            "POST",
            "/v1/threads/thread-test-1/runs/stream",
            content=b'{"input":"hello"}',
        ) as response:
            body = "".join(response.iter_text())

    events = _decode_sse_events(body)

    assert [event_type for event_type, _ in events] == [
        "run.started",
        "message.delta",
        "run.failed",
    ]
    assert _event_payload(events[-1])["error"] == "runtime_error"
    assert all(event_type != "run.completed" for event_type, _ in events)
    assert all(event_type != "message.completed" for event_type, _ in events)
