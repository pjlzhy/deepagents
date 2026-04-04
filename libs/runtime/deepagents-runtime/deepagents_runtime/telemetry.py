"""Telemetry primitives and LangGraph stream parsing for monitoring flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import Any

from langchain.agents.middleware.human_in_the_loop import HITLRequest
from pydantic import TypeAdapter

from deepagents_runtime import events
from deepagents_runtime.events import RuntimeEvent, _UNSET
from deepagents_runtime.runs import SessionStats
from deepagents_runtime.spec import RuntimeEventType
from deepagents_runtime.streams import (
    _UNSUPPORTED_PAYLOAD,
    _buffer_args,
    _json_like_payload,
    _tool_result_text,
    _try_parse_tool_args,
)


@dataclass(frozen=True)
class TelemetryEvent:
    """Structured telemetry event emitted by the runtime telemetry stream.

    Args:
        stream_mode: Source stream mode such as `messages`, `updates`, `debug`,
            `custom`, or runtime-owned `lifecycle`.
        event_type: Fine-grained event type within the stream mode.
        payload: Structured payload for the event.
        ns: LangGraph namespace path. Empty means the root graph.
        metadata: Structured metadata associated with the event.
        timestamp: UNIX timestamp for the event.
        run_id: Execution run identifier.
        agent_name: Name of the producing agent.
        public_event: Optional compatibility projection into the existing
            public `RuntimeEvent` transport.
    """

    stream_mode: str
    event_type: str
    payload: Any = None
    ns: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    run_id: str = ""
    agent_name: str = ""
    public_event: RuntimeEvent | None = None


@dataclass
class TelemetryParserState:
    """Run-scoped parser state accumulated while parsing telemetry stream parts."""

    full_response: list[str] = field(default_factory=list)
    tool_call_buffers: dict[Any, dict[str, Any]] = field(default_factory=dict)
    stats: SessionStats = field(default_factory=SessionStats)
    run_id: str = ""
    agent_name: str = ""


@dataclass
class TelemetryParseResult:
    """Parser output for one telemetry stream part."""

    events: list[TelemetryEvent] = field(default_factory=list)
    interrupts: dict[str, dict[str, Any]] = field(default_factory=dict)


def telemetry_from_runtime_event(
    event: RuntimeEvent,
    *,
    ns: tuple[str, ...] = (),
    stream_mode: str = "lifecycle",
) -> TelemetryEvent:
    """Project an existing public `RuntimeEvent` into a telemetry event."""

    return TelemetryEvent(
        stream_mode=stream_mode,
        event_type=_telemetry_event_type_from_runtime_event(event.type),
        payload=_normalize_json_like(event.data),
        ns=ns,
        metadata={},
        timestamp=event.timestamp,
        run_id=event.run_id,
        agent_name=event.agent_name,
        public_event=event,
    )


def parse_telemetry_stream_part(
    part: object,
    state: TelemetryParserState,
) -> TelemetryParseResult:
    """Parse one LangGraph v2 stream part into telemetry events.

    Unlike the public runtime event parser, telemetry retains non-root
    namespaces and richer stream modes such as `debug` and `custom`.
    """

    if not isinstance(part, dict):
        return TelemetryParseResult()

    ns = tuple(
        str(item)
        for item in part.get("ns", ())
        if isinstance(item, str)
    )
    stream_mode = part.get("type")
    data = part.get("data")

    if stream_mode == "messages":
        return _parse_message_part(data, ns, state)
    if stream_mode == "updates" and isinstance(data, dict):
        return _parse_updates_part(data, ns, state)
    if stream_mode == "debug":
        return _parse_debug_part(data, ns, state)
    if stream_mode == "custom":
        return TelemetryParseResult(
            events=[
                TelemetryEvent(
                    stream_mode="custom",
                    event_type="custom",
                    payload=_normalize_json_like(data),
                    ns=ns,
                    metadata={},
                    run_id=state.run_id,
                    agent_name=state.agent_name,
                )
            ]
        )
    return TelemetryParseResult()


def _parse_message_part(
    data: Any,
    ns: tuple[str, ...],
    state: TelemetryParserState,
) -> TelemetryParseResult:
    """Parse one `messages` stream part into telemetry events."""

    if not isinstance(data, tuple) or len(data) != 2:
        return TelemetryParseResult()

    message_obj, raw_metadata = data
    metadata = _normalize_metadata(raw_metadata)

    try:
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
    except ImportError:
        return TelemetryParseResult()

    if isinstance(message_obj, (AIMessage, AIMessageChunk)):
        return TelemetryParseResult(
            events=_parse_ai_message(message_obj, ns, metadata, state)
        )
    if isinstance(message_obj, ToolMessage):
        return TelemetryParseResult(
            events=_parse_tool_message(message_obj, ns, metadata, state)
        )
    return TelemetryParseResult()


def _parse_ai_message(
    message_obj: Any,
    ns: tuple[str, ...],
    metadata: dict[str, Any],
    state: TelemetryParserState,
) -> list[TelemetryEvent]:
    """Parse one AI message into telemetry events."""

    result: list[TelemetryEvent] = []
    content_blocks = getattr(message_obj, "content_blocks", None)
    if content_blocks is None:
        return result

    usage = getattr(message_obj, "usage_metadata", None)
    if usage and isinstance(usage, dict):
        input_toks = usage.get("input_tokens", 0)
        output_toks = usage.get("output_tokens", 0)
        if input_toks or output_toks:
            state.stats.record_request("", input_toks, output_toks)

    for block in content_blocks:
        if not isinstance(block, dict):
            continue

        block_type = str(block.get("type", "message_block"))
        payload = _normalize_json_like(block)
        timestamp = time.time()
        public_event: RuntimeEvent | None = None

        if block_type == "text":
            text = str(block.get("text", ""))
            if text and not ns:
                state.full_response.append(text)
            if text and not ns:
                public_event = events.text_delta(
                    text,
                    run_id=state.run_id,
                    agent_name=state.agent_name,
                )

        elif block_type in {"tool_call_chunk", "tool_call"}:
            result.append(
                TelemetryEvent(
                    stream_mode="messages",
                    event_type=block_type,
                    payload=payload,
                    ns=ns,
                    metadata=metadata,
                    timestamp=timestamp,
                    run_id=state.run_id,
                    agent_name=state.agent_name,
                )
            )
            result.extend(
                _maybe_emit_tool_call_start(
                    block=block,
                    ns=ns,
                    metadata=metadata,
                    timestamp=timestamp,
                    state=state,
                )
            )
            continue

        result.append(
            TelemetryEvent(
                stream_mode="messages",
                event_type=block_type,
                payload=payload,
                ns=ns,
                metadata=metadata,
                timestamp=timestamp,
                run_id=state.run_id,
                agent_name=state.agent_name,
                public_event=public_event,
            )
        )

    return result


def _maybe_emit_tool_call_start(
    *,
    block: dict[str, Any],
    ns: tuple[str, ...],
    metadata: dict[str, Any],
    timestamp: float,
    state: TelemetryParserState,
) -> list[TelemetryEvent]:
    """Emit a derived `tool_call_start` telemetry event when args are stable."""

    chunk_name = block.get("name")
    chunk_id = block.get("id")
    chunk_index = block.get("index")
    chunk_args = block.get("args")

    buffer_key: int | str = (
        (*ns, str(chunk_index))
        if chunk_index is not None
        else (
            (*ns, str(chunk_id))
            if chunk_id is not None
            else (*ns, f"unknown-{len(state.tool_call_buffers)}")
        )
    )

    buffer = state.tool_call_buffers.setdefault(
        buffer_key,
        {
            "name": None,
            "id": None,
            "args": None,
            "args_text": "",
            "started": False,
        },
    )
    if chunk_id:
        buffer["id"] = str(chunk_id)
    if chunk_name:
        buffer["name"] = str(chunk_name)

    if isinstance(chunk_args, dict):
        buffer["args"] = chunk_args
    elif isinstance(chunk_args, str) and chunk_args:
        buffer["args_text"] += chunk_args
        parsed_args = _try_parse_tool_args(buffer["args_text"])
        if parsed_args is not None:
            buffer["args"] = parsed_args

    if (
        buffer["started"]
        or not chunk_name
        or (
            block.get("type") != "tool_call"
            and not isinstance(buffer.get("args"), dict)
        )
    ):
        return []

    buffer["started"] = True
    tool_call_id = str(buffer["id"] or buffer_key)
    args = _buffer_args(buffer)
    public_event = events.tool_call_start(
        tool_name=str(chunk_name),
        tool_call_id=tool_call_id,
        args=args,
        run_id=state.run_id,
        agent_name=state.agent_name,
    ) if not ns else None
    return [
        TelemetryEvent(
            stream_mode="messages",
            event_type="tool_call_start",
            payload=_normalize_json_like(
                {
                    "tool_name": str(chunk_name),
                    "tool_call_id": tool_call_id,
                    "args": args,
                }
            ),
            ns=ns,
            metadata=metadata,
            timestamp=timestamp,
            run_id=state.run_id,
            agent_name=state.agent_name,
            public_event=public_event,
        )
    ]


def _parse_tool_message(
    message_obj: Any,
    ns: tuple[str, ...],
    metadata: dict[str, Any],
    state: TelemetryParserState,
) -> list[TelemetryEvent]:
    """Parse one tool message into telemetry events."""

    tool_call_id = str(getattr(message_obj, "tool_call_id", ""))
    raw_content = message_obj.content
    is_error = getattr(message_obj, "status", "") == "error"
    timestamp = time.time()

    tool_name = ""
    start_events: list[TelemetryEvent] = []
    for buf in state.tool_call_buffers.values():
        if buf.get("id") != tool_call_id:
            continue
        tool_name = str(buf.get("name", "") or "")
        if not buf.get("started"):
            buf["started"] = True
            args = _buffer_args(buf)
            public_start = (
                events.tool_call_start(
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    args=args,
                    run_id=state.run_id,
                    agent_name=state.agent_name,
                )
                if not ns
                else None
            )
            start_events.append(
                TelemetryEvent(
                    stream_mode="messages",
                    event_type="tool_call_start",
                    payload=_normalize_json_like(
                        {
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                            "args": args,
                        }
                    ),
                    ns=ns,
                    metadata=metadata,
                    timestamp=timestamp,
                    run_id=state.run_id,
                    agent_name=state.agent_name,
                    public_event=public_start,
                )
            )
        break

    raw_payload = getattr(message_obj, "artifact", _UNSUPPORTED_PAYLOAD)
    payload = (
        _json_like_payload(raw_payload)
        if raw_payload is not _UNSUPPORTED_PAYLOAD
        else _json_like_payload(raw_content)
    )
    content = _tool_result_text(raw_content, payload)

    public_done = (
        events.tool_call_done(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            run_id=state.run_id,
            agent_name=state.agent_name,
        )
        if not ns
        else None
    )
    public_result = (
        events.tool_result(
            tool_call_id,
            content,
            payload=payload if payload is not _UNSUPPORTED_PAYLOAD else _UNSET,
            is_error=is_error,
            run_id=state.run_id,
            agent_name=state.agent_name,
        )
        if not ns
        else None
    )

    result_payload: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "content": content,
        "is_error": is_error,
    }
    if payload is not _UNSUPPORTED_PAYLOAD:
        result_payload["payload"] = payload

    return [
        *start_events,
        TelemetryEvent(
            stream_mode="messages",
            event_type="tool_call_done",
            payload=_normalize_json_like(
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                }
            ),
            ns=ns,
            metadata=metadata,
            timestamp=timestamp,
            run_id=state.run_id,
            agent_name=state.agent_name,
            public_event=public_done,
        ),
        TelemetryEvent(
            stream_mode="messages",
            event_type="tool_result",
            payload=_normalize_json_like(result_payload),
            ns=ns,
            metadata=metadata,
            timestamp=timestamp,
            run_id=state.run_id,
            agent_name=state.agent_name,
            public_event=public_result,
        ),
    ]


def _parse_updates_part(
    data: dict[str, Any],
    ns: tuple[str, ...],
    state: TelemetryParserState,
) -> TelemetryParseResult:
    """Parse one `updates` stream part into telemetry events and interrupts."""

    result = TelemetryParseResult()
    timestamp = time.time()
    update_metadata = data.get("__metadata__")
    if isinstance(update_metadata, dict):
        result.events.append(
            TelemetryEvent(
                stream_mode="updates",
                event_type="update_metadata",
                payload=_normalize_json_like(update_metadata),
                ns=ns,
                metadata={},
                timestamp=timestamp,
                run_id=state.run_id,
                agent_name=state.agent_name,
            )
        )

    state_update = {
        key: value
        for key, value in data.items()
        if key not in {"__interrupt__", "__metadata__"}
    }
    if state_update:
        result.events.append(
            TelemetryEvent(
                stream_mode="updates",
                event_type="state_update",
                payload=_normalize_json_like(state_update),
                ns=ns,
                metadata={},
                timestamp=timestamp,
                run_id=state.run_id,
                agent_name=state.agent_name,
            )
        )

    if "__interrupt__" not in data:
        return result

    adapter = TypeAdapter(HITLRequest)
    for interrupt_obj in data.get("__interrupt__", []):
        interrupt_id = str(getattr(interrupt_obj, "id", str(id(interrupt_obj))))
        interrupt_value = getattr(interrupt_obj, "value", interrupt_obj)
        try:
            validated = adapter.validate_python(interrupt_value)
            normalized = adapter.dump_python(validated, mode="json")
        except Exception:
            result.events.append(
                telemetry_from_runtime_event(
                    events.error_event(
                        f"Malformed HITL interrupt: {interrupt_id}",
                        run_id=state.run_id,
                        agent_name=state.agent_name,
                    ),
                    ns=ns,
                )
            )
            continue

        request = (
            normalized
            if isinstance(normalized, dict)
            else {"value": _normalize_json_like(normalized)}
        )
        request["interrupt_id"] = interrupt_id
        result.interrupts[interrupt_id] = request
        result.events.append(
            TelemetryEvent(
                stream_mode="updates",
                event_type="interrupt",
                payload=_normalize_json_like(request),
                ns=ns,
                metadata={},
                timestamp=timestamp,
                run_id=state.run_id,
                agent_name=state.agent_name,
            )
        )

    return result


def _parse_debug_part(
    data: Any,
    ns: tuple[str, ...],
    state: TelemetryParserState,
) -> TelemetryParseResult:
    """Parse one `debug` stream part into telemetry events."""

    if not isinstance(data, dict):
        return TelemetryParseResult()

    event_type = str(data.get("type", "debug"))
    payload = data.get("payload")
    metadata: dict[str, Any] = {}
    if "step" in data:
        metadata["step"] = _normalize_json_like(data["step"])
    timestamp = _timestamp_from_debug(data.get("timestamp")) or time.time()

    return TelemetryParseResult(
        events=[
            TelemetryEvent(
                stream_mode="debug",
                event_type=event_type,
                payload=_normalize_json_like(payload),
                ns=ns,
                metadata=metadata,
                timestamp=timestamp,
                run_id=state.run_id,
                agent_name=state.agent_name,
            )
        ]
    )


def _telemetry_event_type_from_runtime_event(
    event_type: RuntimeEventType,
) -> str:
    """Map a public runtime event type into a telemetry event type."""

    mapping = {
        RuntimeEventType.RUN_START: "run_started",
        RuntimeEventType.TEXT_DELTA: "text",
        RuntimeEventType.TEXT_DONE: "text_done",
        RuntimeEventType.TOOL_CALL_START: "tool_call_start",
        RuntimeEventType.TOOL_CALL_DONE: "tool_call_done",
        RuntimeEventType.TOOL_RESULT: "tool_result",
        RuntimeEventType.HITL_REQUEST: "hitl_request",
        RuntimeEventType.RUN_END: "run_ended",
        RuntimeEventType.RUN_CANCELED: "run_canceled",
        RuntimeEventType.ERROR: "error",
    }
    return mapping[event_type]


def _normalize_metadata(value: Any) -> dict[str, Any]:
    """Normalize arbitrary metadata into a JSON-like dict."""

    if not isinstance(value, dict):
        return {}
    return {
        str(key): _normalize_json_like(item)
        for key, item in value.items()
    }


def _normalize_json_like(value: Any) -> Any:
    """Best-effort normalize values into protobuf-encodable JSON-like data."""

    if isinstance(value, tuple):
        return [_normalize_json_like(item) for item in value]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _normalize_json_like(value.model_dump(mode="json"))
        except Exception:
            return str(value)

    normalized = _json_like_payload(value)
    if normalized is not _UNSUPPORTED_PAYLOAD:
        return normalized

    if isinstance(value, list):
        return [_normalize_json_like(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_json_like(item)
            for key, item in value.items()
        }
    return str(value)


def _timestamp_from_debug(value: Any) -> float | None:
    """Parse a debug wrapper timestamp into UNIX seconds when possible."""

    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
