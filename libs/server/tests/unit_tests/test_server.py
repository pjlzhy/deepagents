from __future__ import annotations

import json
import socket
import time
from contextlib import closing
from http.client import HTTPConnection
from threading import Thread
from urllib.request import urlopen

from deepagents_server.app import create_app
from deepagents_server.config import ServerConfig
from deepagents_server.runtime import ExecutionResult, RuntimeEvent
from deepagents_server.server import run_server
from deepagents_server.state import InMemoryThreadStore


class FakeExecutionService:
    async def run(self, request):
        return ExecutionResult(
            assistant_id=request.assistant_id,
            thread_id=request.thread_id or "thread-http-1",
            model=request.model,
            output=f"http:{request.input}",
        )

    async def stream(self, request):
        yield RuntimeEvent(
            type="message.delta",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-http-1",
                "model": request.model,
                "text": "http-stream",
            },
        )
        yield RuntimeEvent(
            type="run.completed",
            payload={
                "assistant_id": request.assistant_id,
                "thread_id": request.thread_id or "thread-http-1",
                "model": request.model,
                "output": "http-stream",
            },
        )


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


def _get_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def test_http_server_serves_healthz() -> None:
    port = _get_free_port()
    config = ServerConfig(host="127.0.0.1", port=port)
    thread = Thread(
        target=run_server,
        kwargs={
            "config": config,
            "app": create_app(
                execution_service=FakeExecutionService(),
                thread_store=InMemoryThreadStore(generate_thread_id=lambda: "thread-http-1"),
            ),
        },
        daemon=True,
    )

    thread.start()
    time.sleep(0.1)

    with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
        assert response.status == 200
        assert response.read() == b'{"status": "ok"}'


def test_http_server_supports_thread_run_and_stream_flow() -> None:
    port = _get_free_port()
    config = ServerConfig(host="127.0.0.1", port=port)
    thread = Thread(
        target=run_server,
        kwargs={
            "config": config,
            "app": create_app(
                execution_service=FakeExecutionService(),
                thread_store=InMemoryThreadStore(generate_thread_id=lambda: "thread-http-1"),
            ),
        },
        daemon=True,
    )

    thread.start()
    time.sleep(0.1)

    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(
            "POST",
            "/v1/threads",
            body='{"assistant_id":"assistant-http","model":"gpt-5"}',
            headers={"Content-Type": "application/json"},
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        assert create_response.status == 201
        assert create_payload["thread_id"] == "thread-http-1"

        connection.request("GET", "/v1/threads/thread-http-1")
        get_response = connection.getresponse()
        get_payload = json.loads(get_response.read().decode("utf-8"))
        assert get_response.status == 200
        assert get_payload["assistant_id"] == "assistant-http"

        connection.request(
            "POST",
            "/v1/threads/thread-http-1/runs",
            body='{"input":"hello"}',
            headers={"Content-Type": "application/json"},
        )
        run_response = connection.getresponse()
        run_payload = json.loads(run_response.read().decode("utf-8"))
        assert run_response.status == 200
        assert run_payload["output"] == "http:hello"

        connection.request(
            "POST",
            "/v1/threads/thread-http-1/runs/stream",
            body='{"input":"hello"}',
            headers={"Content-Type": "application/json"},
        )
        stream_response = connection.getresponse()
        stream_payload = stream_response.read().decode("utf-8")
        stream_events = _decode_sse_events(stream_payload)
        assert stream_response.status == 200
        assert [event_type for event_type, _ in stream_events] == [
            "run.started",
            "message.delta",
            "message.completed",
            "thread.updated",
            "run.completed",
        ]
        assert [payload["sequence"] for _, payload in stream_events] == list(
            range(1, len(stream_events) + 1)
        )
        assert stream_events[-1][1]["payload"]["output"] == "http-stream"
    finally:
        connection.close()
