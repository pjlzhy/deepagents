import json

from deepagents_server.app import AppResponse, ServerApp, create_app
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


def _decode_json(response: AppResponse) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


def _decode_sse_events(response: AppResponse) -> list[tuple[str, dict[str, object]]]:
    assert response.stream is not None
    raw_body = b"".join(response.stream).decode("utf-8")
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


def _create_test_app(*, execution_service=None) -> ServerApp:
    return create_app(
        execution_service=execution_service or FakeExecutionService(),
        thread_store=InMemoryThreadStore(generate_thread_id=lambda: "thread-test-1"),
    )


def test_health_route_returns_ok() -> None:
    app = _create_test_app()

    response = app.handle_request("GET", "/healthz")

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert _decode_json(response) == {"status": "ok"}


def test_unknown_route_returns_404() -> None:
    app = _create_test_app()

    response = app.handle_request("GET", "/missing")

    assert response.status_code == 404
    assert response.content_type == "application/json"
    assert _decode_json(response)["error"] == "not_found"


def test_create_thread_returns_schema_payload() -> None:
    app = _create_test_app()

    response = app.handle_request(
        "POST",
        "/v1/threads",
        body=b'{"assistant_id":"assistant-alpha","model":"gpt-5"}',
    )

    payload = _decode_json(response)
    assert response.status_code == 201
    assert payload["assistant_id"] == "assistant-alpha"
    assert payload["thread_id"] == "thread-test-1"
    assert payload["model"] == "gpt-5"
    assert payload["run_count"] == 0


def test_invalid_thread_body_returns_422() -> None:
    app = _create_test_app()

    response = app.handle_request(
        "POST",
        "/v1/threads",
        body=b'{"assistant_id":"assistant-alpha","assistant_id":"duplicate"}',
    )

    payload = _decode_json(response)
    assert response.status_code == 422
    assert payload["error"] == "validation_error"


def test_run_route_returns_output_and_thread_state() -> None:
    app = _create_test_app()
    app.handle_request(
        "POST",
        "/v1/threads",
        body=b'{"assistant_id":"assistant-alpha","model":"gpt-5"}',
    )

    response = app.handle_request(
        "POST",
        "/v1/threads/thread-test-1/runs",
        body=b'{"input":"hello"}',
    )

    payload = _decode_json(response)
    assert response.status_code == 200
    assert payload["assistant_id"] == "assistant-alpha"
    assert payload["thread_id"] == "thread-test-1"
    assert payload["model"] == "gpt-5"
    assert payload["input"] == "hello"
    assert payload["output"] == "echo:hello"
    assert payload["thread"]["run_count"] == 1


def test_stream_route_returns_sse_events() -> None:
    app = _create_test_app()
    app.handle_request(
        "POST",
        "/v1/threads",
        body=b'{"assistant_id":"assistant-alpha","model":"gpt-5"}',
    )

    response = app.handle_request(
        "POST",
        "/v1/threads/thread-test-1/runs/stream",
        body=b'{"input":"hello"}',
    )

    assert response.status_code == 200
    assert response.content_type == "text/event-stream"
    events = _decode_sse_events(response)

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
    assert [payload["type"] for _, payload in events] == [event_type for event_type, _ in events]
    assert [payload["sequence"] for _, payload in events] == list(range(1, len(events) + 1))
    assert all(payload["run_id"].startswith("run_") for _, payload in events)
    assert all(payload["thread_id"] == "thread-test-1" for _, payload in events)
    assert all(payload["timestamp"].endswith("Z") for _, payload in events)
    assert events[1][1]["payload"]["text"] == "streamed"
    assert events[2][1]["payload"]["name"] == "fetch_url"
    assert events[3][1]["payload"]["content"] == "ok"
    assert events[4][1]["payload"]["interrupt_id"] == "interrupt-1"
    assert events[5][1]["payload"]["output"] == "streamed"
    assert events[6][1]["payload"]["run_count"] == 1
    assert events[7][1]["payload"]["output"] == "streamed"


def test_stream_route_translates_runtime_errors_to_failed_events() -> None:
    app = _create_test_app(execution_service=FailingExecutionService())
    app.handle_request(
        "POST",
        "/v1/threads",
        body=b'{"assistant_id":"assistant-alpha","model":"gpt-5"}',
    )

    response = app.handle_request(
        "POST",
        "/v1/threads/thread-test-1/runs/stream",
        body=b'{"input":"hello"}',
    )

    events = _decode_sse_events(response)

    assert [event_type for event_type, _ in events] == [
        "run.started",
        "message.delta",
        "run.failed",
    ]
    assert events[-1][1]["payload"]["error"] == "runtime_error"
    assert all(event_type != "run.completed" for event_type, _ in events)
    assert all(event_type != "message.completed" for event_type, _ in events)
