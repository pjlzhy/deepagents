"""FastAPI application factory and route handling for the Deep Agents HTTP server."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    from collections.abc import AsyncIterator, Iterator


_NOT_FOUND_STATUS = 404


class ExecutionServiceProtocol(Protocol):
    """Protocol for route handlers that execute Deep Agents runs."""

    async def run(self, request: ExecutionRequest) -> object:
        """Run a request to completion."""

    def stream(self, request: ExecutionRequest) -> AsyncIterator[RuntimeEvent]:
        """Stream runtime events for a request."""


@dataclass
class _SseStreamState:
    """Mutable metadata for a single SSE stream response."""

    run_id: str
    thread_id: str
    sequence: int = 0


class _FastApiRuntime:
    """Shared FastAPI route implementation for the server package."""

    def __init__(
        self,
        *,
        execution_service: ExecutionServiceProtocol,
        thread_store: InMemoryThreadStore,
    ) -> None:
        """Create the route runtime.

        Args:
            execution_service: Runtime service used by run routes.
            thread_store: Persistent thread metadata store.
        """
        self._execution_service = execution_service
        self._thread_store = thread_store

    async def health(self) -> dict[str, str]:
        """Return the health payload for the server."""
        return {"status": "ok"}

    async def create_thread(self, request: Request) -> JSONResponse:
        """Create a new thread record from the incoming request."""
        create_request = parse_thread_create_request(await request.body())
        thread = self._thread_store.create_thread(
            assistant_id=create_request.assistant_id,
            model=create_request.model,
        )
        return self.json_response(201, thread.to_payload())

    async def get_thread(self, thread_id: str) -> JSONResponse:
        """Return the persisted thread metadata for a thread ID."""
        thread = self._thread_store.get_thread(thread_id)
        if thread is None:
            return self.not_found_thread_response(thread_id)
        return self.json_response(200, thread.to_payload())

    async def run(self, thread_id: str, request: Request) -> JSONResponse:
        """Run a thread request to completion and return the final payload."""
        thread = self._thread_store.get_thread(thread_id)
        if thread is None:
            return self.not_found_thread_response(thread_id)

        run_request = parse_run_request(await request.body())
        effective_assistant = run_request.assistant_id or thread.assistant_id
        effective_model = run_request.model if run_request.model is not None else thread.model
        run_id = self._generate_run_id()
        result = await self._execution_service.run(
            self._build_execution_request(
                thread=thread,
                run_id=run_id,
                input_text=run_request.input,
                assistant_id=effective_assistant,
                model=effective_model,
            )
        )
        result_model = getattr(result, "model", effective_model)
        updated = self._thread_store.record_run(
            thread.thread_id,
            assistant_id=effective_assistant,
            model=result_model,
            run_id=run_id,
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
        return self.json_response(200, payload)

    async def stream(
        self,
        thread_id: str,
        request: Request,
    ) -> JSONResponse | StreamingResponse:
        """Stream a run request as SSE events."""
        thread = self._thread_store.get_thread(thread_id)
        if thread is None:
            return self.not_found_thread_response(thread_id)

        run_request = parse_run_request(await request.body())
        effective_assistant = run_request.assistant_id or thread.assistant_id
        effective_model = run_request.model if run_request.model is not None else thread.model
        run_id = self._generate_run_id()
        execution_request = self._build_execution_request(
            thread=thread,
            run_id=run_id,
            input_text=run_request.input,
            assistant_id=effective_assistant,
            model=effective_model,
        )
        return StreamingResponse(
            self._stream_response(
                thread=thread,
                run_id=run_id,
                input_text=run_request.input,
                effective_assistant=effective_assistant,
                effective_model=effective_model,
                execution_request=execution_request,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "close"},
        )

    def _build_execution_request(
        self,
        *,
        thread: ThreadRecord,
        run_id: str,
        input_text: str,
        assistant_id: str,
        model: str | None,
    ) -> ExecutionRequest:
        runtime_defaults = thread.runtime_defaults
        return ExecutionRequest(
            assistant_id=assistant_id,
            input=input_text,
            model=model,
            thread_id=thread.thread_id,
            sandbox_type=runtime_defaults.sandbox_type,
            sandbox_id=runtime_defaults.sandbox_id,
            sandbox_setup=runtime_defaults.sandbox_setup,
            checkpointer=runtime_defaults.checkpointer,
            checkpointer_backend=runtime_defaults.checkpointer_backend,
            enable_memory=runtime_defaults.enable_memory,
            enable_skills=runtime_defaults.enable_skills,
            run_id=run_id,
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

    def json_response(self, status_code: int, payload: dict[str, object]) -> JSONResponse:
        return JSONResponse(status_code=status_code, content=payload)

    def not_found_thread_response(self, thread_id: str) -> JSONResponse:
        return self.json_response(
            _NOT_FOUND_STATUS,
            {"error": "not_found", "message": f"Unknown thread_id '{thread_id}'."},
        )

    def not_found_route_response(self, path: str) -> JSONResponse:
        """Return the API payload for an unknown route."""
        return self.json_response(
            _NOT_FOUND_STATUS,
            {"error": "not_found", "message": f"Unknown route '{path}'."},
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
) -> FastAPI:
    """Create the FastAPI application for the Deep Agents server.

    Args:
        execution_service: Optional execution service override for tests.
        thread_store: Optional thread store override for tests.

    Returns:
        Configured FastAPI application.
    """
    runtime = _FastApiRuntime(
        execution_service=execution_service or ExecutionService(),
        thread_store=thread_store or InMemoryThreadStore(),
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(SchemaValidationError)
    async def handle_schema_validation_error(
        request: Request,
        exc: SchemaValidationError,
    ) -> JSONResponse:
        del request
        return runtime.json_response(exc.status_code, serialize_error(exc))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        if exc.status_code == _NOT_FOUND_STATUS:
            return runtime.not_found_route_response(request.url.path)
        return runtime.json_response(
            exc.status_code,
            {"error": "http_error", "message": str(exc.detail)},
        )

    app.add_api_route("/healthz", runtime.health, methods=["GET"])
    app.add_api_route("/v1/threads", runtime.create_thread, methods=["POST"])
    app.add_api_route("/v1/threads/{thread_id}", runtime.get_thread, methods=["GET"])
    app.add_api_route(
        "/v1/threads/{thread_id}/runs/stream",
        runtime.stream,
        methods=["POST"],
        response_model=None,
    )
    app.add_api_route("/v1/threads/{thread_id}/runs", runtime.run, methods=["POST"])
    return app
