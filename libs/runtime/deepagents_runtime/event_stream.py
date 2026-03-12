"""Translate LangGraph stream chunks into client-neutral runtime events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import ValidationError

from deepagents_runtime.events import RuntimeEvent, create_runtime_event
from deepagents_runtime.runs import SessionStats, is_summarization_chunk
from deepagents_runtime.streams import (
    is_main_agent_namespace,
    parse_message_chunk,
    parse_stream_chunk,
    validate_hitl_request,
)

if TYPE_CHECKING:
    from langchain.agents.middleware.human_in_the_loop import HITLRequest

NamespaceKey = tuple[Any, ...]


class MalformedInterruptError(ValueError):
    """Raised when a HITL interrupt payload cannot be validated."""

    def __init__(
        self,
        interrupt_id: str | None,
        raw_value: object,
        validation_error: ValidationError,
    ) -> None:
        """Initialize the error with interrupt context for debugging.

        Args:
            interrupt_id: Interrupt identifier when available.
            raw_value: Raw interrupt payload that failed validation.
            validation_error: Validation error raised while parsing the payload.
        """
        self.interrupt_id = interrupt_id
        self.raw_value = raw_value
        self.validation_error = validation_error
        suffix = f" {interrupt_id}" if interrupt_id is not None else ""
        super().__init__(f"Malformed HITL interrupt{suffix}")


@dataclass(slots=True)
class _ToolCallBuffer:
    """Incremental tool-call assembly state for streaming chunks."""

    name: str | None = None
    tool_call_id: str | None = None
    args: object | None = None
    args_parts: list[str] = field(default_factory=list)
    start_emitted: bool = False
    arguments_emitted: bool = False


@dataclass
class RuntimeEventStreamState:
    """Mutable state for translating one or more stream passes into events."""

    model_name: str = ""
    run_id: str | None = None
    thread_id: str | None = None
    pending_interrupts: dict[str, HITLRequest] = field(default_factory=dict)
    interrupt_occurred: bool = False
    stats: SessionStats = field(default_factory=SessionStats)
    summarization_in_progress: bool = False
    open_text_namespaces: set[NamespaceKey] = field(default_factory=set)
    tool_call_buffers: dict[int | str, _ToolCallBuffer] = field(default_factory=dict)


def _create_event(
    state: RuntimeEventStreamState,
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
) -> RuntimeEvent:
    """Create a runtime event using the stream state's run/thread identifiers.

    Returns:
        Runtime event populated with the current run and thread metadata.
    """
    return create_runtime_event(
        event_type,
        payload=payload,
        run_id=state.run_id,
        thread_id=state.thread_id,
    )


def _json_safe_value(value: object) -> Any:  # noqa: ANN401
    """Convert arbitrary values into JSON-friendly payload data.

    Returns:
        JSON-serializable representation of `value`.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]
    return str(value)


def _namespace_payload(namespace: NamespaceKey) -> list[Any]:
    """Convert a namespace tuple to a JSON-friendly list.

    Returns:
        Namespace represented as JSON-safe list elements.
    """
    return [_json_safe_value(item) for item in namespace]


def _complete_message_event(
    state: RuntimeEventStreamState,
    namespace: NamespaceKey,
) -> RuntimeEvent | None:
    """Emit a completion event for an open assistant message namespace.

    Returns:
        Completion event when the namespace has an open message, otherwise `None`.
    """
    if namespace not in state.open_text_namespaces:
        return None

    state.open_text_namespaces.remove(namespace)
    return _create_event(
        state,
        "message.assistant.completed",
        payload={"namespace": _namespace_payload(namespace)},
    )


def _parse_tool_call_args(buffer: _ToolCallBuffer) -> dict[str, Any] | None:
    """Parse the accumulated tool-call args into a JSON object.

    Returns:
        Parsed argument dict, or `None` when the tool input is still incomplete.
    """
    parsed_args = buffer.args
    if isinstance(parsed_args, str):
        if not parsed_args:
            return None
        try:
            parsed_args = json.loads(parsed_args)
        except json.JSONDecodeError:
            return None
    elif parsed_args is None:
        return None

    if not isinstance(parsed_args, dict):
        return {"value": _json_safe_value(parsed_args)}
    return {str(key): _json_safe_value(value) for key, value in parsed_args.items()}


def _tool_buffer_key(
    chunk_index: object,
    chunk_id: object,
    existing_count: int,
) -> int | str:
    """Choose a stable buffer key for an incremental tool call.

    Returns:
        Stable key that can be reused across partial tool-call chunks.
    """
    if isinstance(chunk_index, int):
        return chunk_index
    if isinstance(chunk_id, str):
        return chunk_id
    return f"unknown-{existing_count}"


def _usage_events(
    state: RuntimeEventStreamState,
    usage: object,
) -> list[RuntimeEvent]:
    """Update stats and emit a usage event when usage metadata is present.

    Returns:
        Usage event list for the current chunk, or an empty list when absent.
    """
    if not isinstance(usage, dict):
        return []

    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", 0) or 0)

    if input_tokens or output_tokens:
        state.stats.record_request(state.model_name, input_tokens, output_tokens)
    elif total_tokens:
        state.stats.record_request(state.model_name, total_tokens, 0)
    else:
        return []

    effective_total = total_tokens or (input_tokens + output_tokens)
    return [
        _create_event(
            state,
            "run.usage",
            payload={
                "model_name": state.model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": effective_total,
                "request_count": state.stats.request_count,
                "session_input_tokens": state.stats.input_tokens,
                "session_output_tokens": state.stats.output_tokens,
            },
        )
    ]


def _updates_to_events(
    state: RuntimeEventStreamState,
    namespace: NamespaceKey,
    data: dict[str, Any],
) -> list[RuntimeEvent]:
    """Translate an `updates` chunk into runtime events.

    Returns:
        Runtime events derived from the update payload.

    Raises:
        MalformedInterruptError: Raised when a HITL interrupt payload is invalid.
    """
    events: list[RuntimeEvent] = []

    interrupts = data.get("__interrupt__")
    if isinstance(interrupts, list):
        for interrupt_obj in interrupts:
            interrupt_id = getattr(interrupt_obj, "id", None)
            raw_value = getattr(interrupt_obj, "value", None)
            interrupt_key = str(interrupt_id) if interrupt_id is not None else None
            try:
                request = validate_hitl_request(raw_value)
            except ValidationError as exc:
                raise MalformedInterruptError(
                    interrupt_key,
                    raw_value,
                    exc,
                ) from exc

            if interrupt_key is None:
                continue

            state.pending_interrupts[interrupt_key] = request
            state.interrupt_occurred = True
            events.append(
                _create_event(
                    state,
                    "run.interrupt",
                    payload={
                        "namespace": _namespace_payload(namespace),
                        "interrupt_id": interrupt_key,
                        "request": _json_safe_value(request),
                    },
                )
            )

    chunk_data = next(iter(data.values())) if data else None
    if isinstance(chunk_data, dict) and "todos" in chunk_data:
        events.append(
            _create_event(
                state,
                "run.todos.updated",
                payload={
                    "namespace": _namespace_payload(namespace),
                    "todos": _json_safe_value(chunk_data["todos"]),
                },
            )
        )

    return events


def _messages_to_events(
    state: RuntimeEventStreamState,
    namespace: NamespaceKey,
    data: object,
) -> list[RuntimeEvent]:
    """Translate a `messages` chunk into runtime events.

    Returns:
        Runtime events derived from the message payload.
    """
    payload = parse_message_chunk(data)
    if payload is None:
        return []

    events: list[RuntimeEvent] = []
    message = payload.message
    metadata = payload.metadata

    if is_summarization_chunk(metadata):
        if not state.summarization_in_progress:
            state.summarization_in_progress = True
            events.append(_create_event(state, "run.summarization.started"))
        return events

    if state.summarization_in_progress:
        state.summarization_in_progress = False
        events.append(_create_event(state, "run.summarization.completed"))

    if isinstance(message, HumanMessage):
        completion = _complete_message_event(state, namespace)
        if completion is not None:
            events.append(completion)
        return events

    events.extend(_usage_events(state, getattr(message, "usage_metadata", None)))

    if isinstance(message, ToolMessage):
        events.append(
            _create_event(
                state,
                "tool.call.completed",
                payload={
                    "namespace": _namespace_payload(namespace),
                    "tool_call_id": _json_safe_value(
                        getattr(message, "tool_call_id", None)
                    ),
                    "tool_name": _json_safe_value(getattr(message, "name", None)),
                    "status": _json_safe_value(getattr(message, "status", "success")),
                    "content": _json_safe_value(message.content),
                },
            )
        )
        return events

    if not hasattr(message, "content_blocks"):
        return events

    for block in message.content_blocks:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            if not text:
                continue

            state.open_text_namespaces.add(namespace)
            events.append(
                _create_event(
                    state,
                    "message.assistant.delta",
                    payload={
                        "namespace": _namespace_payload(namespace),
                        "text": str(text),
                    },
                )
            )
            continue

        if block_type not in {"tool_call_chunk", "tool_call"}:
            continue

        chunk_name = block.get("name")
        chunk_args = block.get("args")
        chunk_id = block.get("id")
        chunk_index = block.get("index")
        buffer_key = _tool_buffer_key(
            chunk_index,
            chunk_id,
            len(state.tool_call_buffers),
        )

        buffer = state.tool_call_buffers.setdefault(buffer_key, _ToolCallBuffer())
        if isinstance(chunk_name, str) and chunk_name:
            buffer.name = chunk_name
        if isinstance(chunk_id, str) and chunk_id:
            buffer.tool_call_id = chunk_id

        if isinstance(chunk_args, dict):
            buffer.args = chunk_args
            buffer.args_parts.clear()
        elif isinstance(chunk_args, str):
            if chunk_args:
                if not buffer.args_parts or chunk_args != buffer.args_parts[-1]:
                    buffer.args_parts.append(chunk_args)
                buffer.args = "".join(buffer.args_parts)
        elif chunk_args is not None:
            buffer.args = chunk_args

        parsed_args = _parse_tool_call_args(buffer)
        if buffer.name is None or buffer.tool_call_id is None or parsed_args is None:
            missing_identity = buffer.name is None or buffer.tool_call_id is None
            if missing_identity or buffer.start_emitted:
                continue

            completion = _complete_message_event(state, namespace)
            if completion is not None:
                events.append(completion)

            events.append(
                _create_event(
                    state,
                    "tool.call.started",
                    payload={
                        "namespace": _namespace_payload(namespace),
                        "tool_call_id": buffer.tool_call_id,
                        "tool_name": buffer.name,
                        "args": {},
                    },
                )
            )
            buffer.start_emitted = True
            continue

        if not buffer.start_emitted:
            completion = _complete_message_event(state, namespace)
            if completion is not None:
                events.append(completion)

            events.append(
                _create_event(
                    state,
                    "tool.call.started",
                    payload={
                        "namespace": _namespace_payload(namespace),
                        "tool_call_id": buffer.tool_call_id,
                        "tool_name": buffer.name,
                        "args": parsed_args,
                    },
                )
            )
            buffer.start_emitted = True
            buffer.arguments_emitted = True
            continue

        if buffer.arguments_emitted:
            continue

        events.append(
            _create_event(
                state,
                "tool.call.arguments",
                payload={
                    "namespace": _namespace_payload(namespace),
                    "tool_call_id": buffer.tool_call_id,
                    "tool_name": buffer.name,
                    "args": parsed_args,
                },
            )
        )
        buffer.arguments_emitted = True

    if getattr(message, "chunk_position", None) == "last":
        completion = _complete_message_event(state, namespace)
        if completion is not None:
            events.append(completion)

    return events


def process_runtime_stream_chunk(
    chunk: object,
    state: RuntimeEventStreamState,
) -> list[RuntimeEvent]:
    """Translate one raw LangGraph stream chunk into runtime events.

    Returns:
        Client-neutral runtime events derived from `chunk`.
    """
    parsed = parse_stream_chunk(chunk)
    if parsed is None:
        return []

    if not is_main_agent_namespace(parsed.namespace):
        return []

    if parsed.stream_mode == "updates" and isinstance(parsed.data, dict):
        return _updates_to_events(state, parsed.namespace, parsed.data)

    if parsed.stream_mode != "messages":
        return []

    return _messages_to_events(state, parsed.namespace, parsed.data)


def finalize_runtime_stream_pass(
    state: RuntimeEventStreamState,
) -> list[RuntimeEvent]:
    """Flush runtime events that should occur when a stream pass ends.

    Returns:
        Deferred completion events that must be emitted at pass boundaries.
    """
    events: list[RuntimeEvent] = []

    if state.summarization_in_progress:
        state.summarization_in_progress = False
        events.append(_create_event(state, "run.summarization.completed"))

    for namespace in sorted(state.open_text_namespaces, key=repr):
        completion = _complete_message_event(state, namespace)
        if completion is not None:
            events.append(completion)

    state.tool_call_buffers.clear()
    return events
