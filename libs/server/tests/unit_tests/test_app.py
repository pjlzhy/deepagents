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
            type="run.completed",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-missing",
                "model": request.model,
                "output": "streamed",
            },
        )


def _decode_json(response: AppResponse) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


def _create_test_app() -> ServerApp:
    return create_app(
        execution_service=FakeExecutionService(),
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
    assert response.stream is not None
    body = b"".join(response.stream).decode("utf-8")
    assert "event: run.started" in body
    assert "event: message.delta" in body
    assert "event: run.completed" in body
    assert "event: message.completed" in body
