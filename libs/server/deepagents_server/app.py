"""Application factory and route handling for the Deep Agents HTTP server."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from deepagents_server.runtime import (
    ExecutionRequest,
    ExecutionService,
    RuntimeDependencyError,
    RuntimeEvent,
)
from deepagents_server.schemas import (
    SchemaValidationError,
    parse_run_request,
    parse_thread_create_request,
    serialize_error,
)
from deepagents_server.state import InMemoryThreadStore, ThreadRecord

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping

_HEALTH_PATH = "/healthz"
_THREADS_PATH = "/v1/threads"
_THREAD_PATH_RE = re.compile(r"^/v1/threads/(?P<thread_id>[^/]+)$")
_RUN_PATH_RE = re.compile(r"^/v1/threads/(?P<thread_id>[^/]+)/runs$")
_STREAM_PATH_RE = re.compile(r"^/v1/threads/(?P<thread_id>[^/]+)/runs/stream$")


class ExecutionServiceProtocol(Protocol):
    """Protocol for route handlers that execute Deep Agents runs."""

    async def run(self, request: ExecutionRequest) -> object:
        """Run a request to completion."""

    async def stream(self, request: ExecutionRequest) -> AsyncIterator[RuntimeEvent]:
        """Stream runtime events for a request."""


@dataclass(frozen=True)
class AppRequest:
    """Normalized HTTP request passed from the server adapter to the app.

    Args:
        method: Uppercase HTTP method.
        path: URL path without query string.
        headers: Request headers indexed by original name.
        body: Raw request body bytes.
    """

    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes = b""


@dataclass
class AppResponse:
    """HTTP response returned by the app router.

    Args:
        status_code: HTTP status code.
        body: Serialized response body for non-streaming responses.
        content_type: MIME type sent to the client.
        headers: Additional HTTP headers.
        stream: Optional byte iterator for SSE responses.
    """

    status_code: int
    body: bytes = b""
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)
    stream: Iterator[bytes] | None = None


@dataclass
class _SseStreamState:
    """Mutable metadata for a single SSE stream response."""

    run_id: str
    thread_id: str
    sequence: int = 0


class ServerApp:
    """Route container for the MVP Deep Agents HTTP server.

    Args:
        execution_service: Runtime service used by run routes.
        thread_store: Persistent thread metadata store.
    """

    def __init__(
        self,
        *,
        execution_service: ExecutionServiceProtocol,
        thread_store: InMemoryThreadStore,
    ) -> None:
        """Create the route container.

        Args:
            execution_service: Runtime service used by run routes.
            thread_store: Persistent thread metadata store.
        """
        self._execution_service = execution_service
        self._thread_store = thread_store

    def handle_request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> AppResponse:
        """Handle a single HTTP request.

        Args:
            method: HTTP method from the incoming request.
            path: Request path.
            headers: Optional HTTP headers for the request.
            body: Optional raw request body.

        Returns:
            Application response ready to serialize over HTTP.
        """
        request = AppRequest(
            method=method.upper(),
            path=path,
            headers=headers or {},
            body=body,
        )

        try:
            return self._dispatch_request(request)
        except SchemaValidationError as exc:
            return self._json_response(exc.status_code, serialize_error(exc))
        except RuntimeDependencyError as exc:
            payload = {
                "error": "runtime_dependency_unavailable",
                "message": str(exc),
            }
            return self._json_response(503, payload)
        except Exception:  # noqa: BLE001
            payload = {
                "error": "internal_error",
                "message": "Internal server error.",
            }
            return self._json_response(500, payload)

    def _dispatch_request(self, request: AppRequest) -> AppResponse:
        if request.method == "GET" and request.path == _HEALTH_PATH:
            return self._json_response(200, {"status": "ok"})
        if request.method == "POST" and request.path == _THREADS_PATH:
            return self._handle_create_thread(request)

        thread_match = _THREAD_PATH_RE.match(request.path)
        if request.method == "GET" and thread_match:
            return self._handle_get_thread(thread_match.group("thread_id"))

        run_match = _RUN_PATH_RE.match(request.path)
        if request.method == "POST" and run_match:
            return self._handle_run(thread_id=run_match.group("thread_id"), request=request)

        stream_match = _STREAM_PATH_RE.match(request.path)
        if request.method == "POST" and stream_match:
            return self._handle_stream(thread_id=stream_match.group("thread_id"), request=request)

        return self._json_response(404, {"error": "not_found", "message": "Route not found."})

    def _handle_create_thread(self, request: AppRequest) -> AppResponse:
        thread_request = parse_thread_create_request(request.body)
        thread = self._thread_store.create_thread(
            assistant_id=thread_request.assistant_id,
            model=thread_request.model,
        )
        return self._json_response(201, thread.to_payload())

    def _handle_get_thread(self, thread_id: str) -> AppResponse:
        thread = self._thread_store.get_thread(thread_id)
        if thread is None:
            return self._json_response(
                404,
                {"error": "not_found", "message": f"Unknown thread_id '{thread_id}'."},
            )
        return self._json_response(200, thread.to_payload())

    def _handle_run(self, *, thread_id: str, request: AppRequest) -> AppResponse:
        thread = self._thread_store.get_thread(thread_id)
        if thread is None:
            return self._json_response(
                404,
                {"error": "not_found", "message": f"Unknown thread_id '{thread_id}'."},
            )

        run_request = parse_run_request(request.body)
        effective_assistant = run_request.assistant_id or thread.assistant_id
        effective_model = run_request.model if run_request.model is not None else thread.model
        run_id = self._generate_run_id()
        result = asyncio.run(
            self._execution_service.run(
                ExecutionRequest(
                    assistant_id=effective_assistant,
                    input=run_request.input,
                    model=effective_model,
                    thread_id=thread.thread_id,
                )
            )
        )
        result_model = getattr(result, "model", effective_model)
        updated = self._thread_store.record_run(
            thread.thread_id,
            assistant_id=effective_assistant,
            model=result_model,
        )
        payload = {
            "assistant_id": effective_assistant,
            "thread_id": thread.thread_id,
            "run_id": run_id,
            "model": result_model,
            "input": run_request.input,
            "output": getattr(result, "output", ""),
            "thread": updated.to_payload() if updated is not None else thread.to_payload(),
        }
        return self._json_response(200, payload)

    def _handle_stream(self, *, thread_id: str, request: AppRequest) -> AppResponse:
        thread = self._thread_store.get_thread(thread_id)
        if thread is None:
            return self._json_response(
                404,
                {"error": "not_found", "message": f"Unknown thread_id '{thread_id}'."},
            )

        run_request = parse_run_request(request.body)
        effective_assistant = run_request.assistant_id or thread.assistant_id
        effective_model = run_request.model if run_request.model is not None else thread.model
        run_id = self._generate_run_id()
        execution_request = ExecutionRequest(
            assistant_id=effective_assistant,
            input=run_request.input,
            model=effective_model,
            thread_id=thread.thread_id,
        )
        return AppResponse(
            status_code=200,
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "close"},
            stream=self._stream_response(
                thread=thread,
                run_id=run_id,
                input_text=run_request.input,
                effective_assistant=effective_assistant,
                effective_model=effective_model,
                execution_request=execution_request,
            ),
        )

    def _stream_response(  # noqa: PLR0913
        self,
        *,
        thread: ThreadRecord,
        run_id: str,
        input_text: str,
        effective_assistant: str,
        effective_model: str | None,
        execution_request: ExecutionRequest,
    ) -> Iterator[bytes]:
        stream_state = _SseStreamState(run_id=run_id, thread_id=thread.thread_id)
        yield self._encode_stream_event(
            stream_state=stream_state,
            event_type="run.started",
            payload={
                "assistant_id": effective_assistant,
                "model": effective_model,
                "input": input_text,
            },
        )
        collected_output: list[str] = []
        completion_payload: dict[str, object] | None = None
        try:
            for event in self._iter_runtime_events(execution_request):
                encoded_event, completion_payload, should_stop = self._handle_runtime_event(
                    event,
                    stream_state=stream_state,
                    collected_output=collected_output,
                    completion_payload=completion_payload,
                )
                if encoded_event is not None:
                    yield encoded_event
                if should_stop:
                    return
        except RuntimeDependencyError as exc:
            yield self._encode_stream_event(
                stream_state=stream_state,
                event_type="run.failed",
                payload={
                    "assistant_id": effective_assistant,
                    "model": effective_model,
                    "error": "runtime_dependency_unavailable",
                    "message": str(exc),
                },
            )
            return
        except Exception:  # noqa: BLE001
            yield self._encode_stream_event(
                stream_state=stream_state,
                event_type="run.failed",
                payload={
                    "assistant_id": effective_assistant,
                    "model": effective_model,
                    "error": "runtime_error",
                    "message": "Execution failed.",
                },
            )
            return

        try:
            yield from self._emit_success_events(
                stream_state=stream_state,
                thread=thread,
                effective_assistant=effective_assistant,
                effective_model=effective_model,
                collected_output=collected_output,
                completion_payload=completion_payload,
            )
        except Exception:  # noqa: BLE001
            yield self._encode_stream_event(
                stream_state=stream_state,
                event_type="run.failed",
                payload={
                    "assistant_id": effective_assistant,
                    "model": effective_model,
                    "error": "runtime_error",
                    "message": "Execution failed.",
                },
            )

    def _handle_runtime_event(
        self,
        event: RuntimeEvent,
        *,
        stream_state: _SseStreamState,
        collected_output: list[str],
        completion_payload: dict[str, object] | None,
    ) -> tuple[bytes | None, dict[str, object] | None, bool]:
        payload = self._normalize_stream_payload(event.payload)

        if event.type == "message.delta":
            text = payload.get("text")
            if isinstance(text, str):
                collected_output.append(text)

        if event.type == "run.completed":
            return None, payload, False

        if event.type == "run.failed":
            return (
                self._encode_stream_event(
                    stream_state=stream_state,
                    event_type=event.type,
                    payload=payload,
                ),
                completion_payload,
                True,
            )

        return (
            self._encode_stream_event(
                stream_state=stream_state,
                event_type=event.type,
                payload=payload,
            ),
            completion_payload,
            False,
        )

    def _emit_success_events(  # noqa: PLR0913
        self,
        *,
        stream_state: _SseStreamState,
        thread: ThreadRecord,
        effective_assistant: str,
        effective_model: str | None,
        collected_output: list[str],
        completion_payload: dict[str, object] | None,
    ) -> Iterator[bytes]:
        updated = self._thread_store.record_run(
            thread.thread_id,
            assistant_id=effective_assistant,
            model=effective_model,
        )
        final_output = self._resolve_final_output(collected_output, completion_payload)
        if final_output:
            yield self._encode_stream_event(
                stream_state=stream_state,
                event_type="message.completed",
                payload={
                    "assistant_id": effective_assistant,
                    "model": effective_model,
                    "output": final_output,
                },
            )
        if updated is not None:
            yield self._encode_stream_event(
                stream_state=stream_state,
                event_type="thread.updated",
                payload=self._normalize_stream_payload(updated.to_payload()),
            )
        yield self._encode_stream_event(
            stream_state=stream_state,
            event_type="run.completed",
            payload=self._build_completion_payload(
                completion_payload,
                assistant_id=effective_assistant,
                model=effective_model,
                output=final_output,
            ),
        )

    def _iter_runtime_events(self, request: ExecutionRequest) -> Iterator[RuntimeEvent]:
        iterator = self._execution_service.stream(request).__aiter__()
        loop = asyncio.new_event_loop()
        try:
            while True:
                try:
                    yield loop.run_until_complete(iterator.__anext__())
                except StopAsyncIteration:
                    break
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _json_response(self, status_code: int, payload: dict[str, object]) -> AppResponse:
        return AppResponse(
            status_code=status_code,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

    def _encode_sse(self, *, event_type: str, payload: dict[str, object]) -> bytes:
        data = json.dumps(payload, ensure_ascii=False)
        return f"event: {event_type}\ndata: {data}\n\n".encode()

    def _encode_stream_event(
        self,
        *,
        stream_state: _SseStreamState,
        event_type: str,
        payload: dict[str, object],
    ) -> bytes:
        return self._encode_sse(
            event_type=event_type,
            payload=self._build_stream_envelope(
                stream_state=stream_state,
                event_type=event_type,
                payload=payload,
            ),
        )

    def _build_stream_envelope(
        self,
        *,
        stream_state: _SseStreamState,
        event_type: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        stream_state.sequence += 1
        return {
            "type": event_type,
            "run_id": stream_state.run_id,
            "thread_id": stream_state.thread_id,
            "sequence": stream_state.sequence,
            "timestamp": self._timestamp_now(),
            "payload": payload,
        }

    def _normalize_stream_payload(self, payload: dict[str, object]) -> dict[str, object]:
        normalized = dict(payload)
        normalized.pop("thread_id", None)
        return normalized

    def _resolve_final_output(
        self,
        collected_output: list[str],
        completion_payload: dict[str, object] | None,
    ) -> str:
        if completion_payload is not None:
            output = completion_payload.get("output")
            if isinstance(output, str):
                return output
        return "".join(collected_output)

    def _build_completion_payload(
        self,
        completion_payload: dict[str, object] | None,
        *,
        assistant_id: str,
        model: str | None,
        output: str,
    ) -> dict[str, object]:
        if completion_payload is not None:
            return completion_payload
        return {
            "assistant_id": assistant_id,
            "model": model,
            "output": output,
        }

    def _timestamp_now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _generate_run_id(self) -> str:
        return f"run_{uuid4().hex}"


def create_app(
    *,
    execution_service: ExecutionServiceProtocol | None = None,
    thread_store: InMemoryThreadStore | None = None,
) -> ServerApp:
    """Create the Deep Agents server application.

    Args:
        execution_service: Optional execution service override for tests.
        thread_store: Optional thread store override for tests.

    Returns:
        Configured route container with MVP HTTP routes.
    """
    return ServerApp(
        execution_service=execution_service or ExecutionService(),
        thread_store=thread_store or InMemoryThreadStore(),
    )
