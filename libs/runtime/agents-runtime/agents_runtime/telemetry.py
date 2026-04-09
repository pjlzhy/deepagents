"""Telemetry primitives and LangGraph stream parsing for monitoring flows."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import time
from typing import Any

from langchain.agents.middleware.human_in_the_loop import HITLRequest
from pydantic import TypeAdapter

from agents_runtime import events
from agents_runtime.events import RuntimeEvent, _UNSET
from agents_runtime.runs import SessionStats
from agents_runtime.spec import RuntimeEventType
from agents_runtime.streams import (
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
    event_id: str = ""
    attempt: int = 0
    seq: int = 0
    node_name: str = ""
    task_id: str = ""
    model_call_id: str = ""
    tool_call_id: str = ""
    interrupt_id: str = ""
    message_id: str = ""


@dataclass
class TelemetryParserState:
    """Run-scoped parser state accumulated while parsing telemetry stream parts."""

    full_response: list[str] = field(default_factory=list)
    tool_call_buffers: dict[Any, dict[str, Any]] = field(default_factory=dict)
    stats: SessionStats = field(default_factory=SessionStats)
    run_id: str = ""
    agent_name: str = ""
    start_checkpoint_id: str = ""
    end_checkpoint_id: str = ""
    emitted_task_keys: set[tuple[tuple[str, ...], str]] = field(default_factory=set)


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


def finalize_telemetry_event(
    event: TelemetryEvent,
    *,
    attempt: int,
    seq: int,
) -> TelemetryEvent:
    """Attach stable run-local identifiers and derived correlation keys."""

    payload = event.payload if isinstance(event.payload, dict) else {}
    metadata = event.metadata if isinstance(event.metadata, dict) else {}

    node_name = event.node_name or _derive_node_name(event, payload, metadata)
    task_id = event.task_id
    if not task_id and event.event_type in {"task", "task_result"}:
        task_id = _telemetry_string(payload.get("id"))
    tool_call_id = event.tool_call_id or _derive_tool_call_id(event, payload)
    interrupt_id = event.interrupt_id or _derive_interrupt_id(event, payload)
    message_id = event.message_id or _derive_message_id(event, payload)
    model_call_id = event.model_call_id or _derive_model_call_id(
        event,
        message_id,
        tool_call_id,
    )
    event_id = event.event_id or f"{event.run_id}:{attempt}:{seq}"

    return replace(
        event,
        event_id=event_id,
        attempt=attempt,
        seq=seq,
        node_name=node_name,
        task_id=task_id,
        model_call_id=model_call_id,
        tool_call_id=tool_call_id,
        interrupt_id=interrupt_id,
        message_id=message_id,
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

    ns = tuple(str(item) for item in part.get("ns", ()) if isinstance(item, str))
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

    model_call_id = _stable_model_call_id(message_obj)

    for block in content_blocks:
        if not isinstance(block, dict):
            continue

        block_type = str(block.get("type", "message_block"))
        payload = _normalize_json_like(block)
        if (
            isinstance(payload, dict)
            and model_call_id
            and block_type not in {"tool_call", "tool_call_chunk"}
        ):
            payload["model_call_id"] = model_call_id
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
                    model_call_id=model_call_id,
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
                model_call_id=model_call_id,
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
    public_event = (
        events.tool_call_start(
            tool_name=str(chunk_name),
            tool_call_id=tool_call_id,
            args=args,
            run_id=state.run_id,
            agent_name=state.agent_name,
        )
        if not ns
        else None
    )
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
    """Parse one `updates` stream part and retain only interrupt semantics."""

    result = TelemetryParseResult()
    timestamp = time.time()

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

    if event_type == "checkpoint":
        _update_checkpoint_bounds(payload, state)
        return TelemetryParseResult()

    if event_type == "task":
        payload_dict = payload if isinstance(payload, dict) else {}
        task_id = _telemetry_string(payload_dict.get("id"))
        if task_id:
            task_key = (ns, task_id)
            if task_key in state.emitted_task_keys:
                return TelemetryParseResult()
            state.emitted_task_keys.add(task_key)
        payload = _compact_debug_task_payload(payload_dict)
    elif event_type == "task_result":
        payload = _compact_debug_task_result_payload(payload)
    else:
        return TelemetryParseResult()

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


def _update_checkpoint_bounds(payload: Any, state: TelemetryParserState) -> None:
    """Track checkpoint boundaries without emitting raw checkpoint events."""

    if not isinstance(payload, dict):
        return

    parent_checkpoint_id = _nested_checkpoint_id(payload.get("parent_config"))
    checkpoint_id = _nested_checkpoint_id(payload.get("config"))

    if not state.start_checkpoint_id and parent_checkpoint_id:
        state.start_checkpoint_id = parent_checkpoint_id
    if checkpoint_id:
        state.end_checkpoint_id = checkpoint_id


def _nested_checkpoint_id(config_value: Any) -> str:
    """Read one checkpoint ID from a LangGraph debug checkpoint config blob."""

    if not isinstance(config_value, dict):
        return ""
    configurable = config_value.get("configurable")
    if not isinstance(configurable, dict):
        return ""
    return _telemetry_string(configurable.get("checkpoint_id"))


def _compact_debug_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop repeated thread-state blobs from one debug task payload."""

    compact: dict[str, Any] = {}
    for key in ("id", "name", "triggers"):
        if key in payload:
            compact[key] = _normalize_json_like(payload[key])
    if "input" in payload:
        compact["input"] = _compact_debug_state(payload["input"])
    return compact


def _compact_debug_task_result_payload(payload: Any) -> dict[str, Any]:
    """Drop repeated thread-state blobs from one debug task_result payload."""

    if not isinstance(payload, dict):
        return {}

    compact: dict[str, Any] = {}
    for key in ("id", "error", "interrupts"):
        if key in payload:
            compact[key] = _normalize_json_like(payload[key])
    if "result" in payload:
        compact["result"] = _compact_debug_state(payload["result"])
    return compact


def _compact_debug_state(value: Any) -> Any:
    """Summarize bulky checkpoint-backed state carried inside debug task payloads."""

    normalized = _normalize_json_like(value)
    if not isinstance(normalized, dict):
        return normalized

    compact: dict[str, Any] = {}
    for key, item in normalized.items():
        if key == "messages" and isinstance(item, list):
            compact[key] = {"count": len(item)}
            continue
        if key == "memory_contents" and isinstance(item, dict):
            compact[key] = {"count": len(item)}
            continue
        if key == "skills_metadata" and isinstance(item, list):
            compact[key] = {"count": len(item)}
            continue
        if isinstance(item, dict):
            compact[key] = _compact_debug_state(item)
            continue
        compact[key] = item
    return compact


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


def _derive_node_name(
    event: TelemetryEvent,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    if event.stream_mode == "lifecycle":
        return "run"

    metadata_node = _telemetry_string(metadata.get("langgraph_node"))
    if metadata_node:
        return metadata_node

    payload_name = _telemetry_string(payload.get("name"))
    if payload_name:
        return payload_name

    if event.public_event is not None:
        tool_name = _telemetry_string(event.public_event.data.get("tool_name"))
        if tool_name:
            return tool_name

    if event.ns:
        raw = event.ns[-1]
        if ":" in raw:
            _, tail = raw.split(":", 1)
            if tail:
                return tail
        if raw:
            return raw

    return "root"


def _derive_tool_call_id(event: TelemetryEvent, payload: dict[str, Any]) -> str:
    tool_call_id = _telemetry_string(payload.get("tool_call_id"))
    if tool_call_id:
        return tool_call_id
    if event.event_type in {"tool_call", "tool_call_chunk"}:
        block_id = _telemetry_string(payload.get("id"))
        if block_id:
            return block_id
    if event.public_event is not None:
        return _telemetry_string(event.public_event.data.get("tool_call_id"))
    return ""


def _derive_interrupt_id(event: TelemetryEvent, payload: dict[str, Any]) -> str:
    interrupt_id = _telemetry_string(payload.get("interrupt_id"))
    if interrupt_id:
        return interrupt_id
    if event.public_event is not None:
        return _telemetry_string(event.public_event.data.get("interrupt_id"))
    return ""


def _derive_message_id(event: TelemetryEvent, payload: dict[str, Any]) -> str:
    message_id = _telemetry_string(payload.get("message_id"))
    if message_id:
        return message_id
    if event.stream_mode == "messages":
        return _telemetry_string(payload.get("id"))
    return ""


def _derive_model_call_id(
    event: TelemetryEvent,
    message_id: str,
    tool_call_id: str,
) -> str:
    if event.model_call_id:
        return event.model_call_id
    if tool_call_id:
        return ""
    if event.stream_mode != "messages":
        return ""
    if event.event_type in {
        "tool_call",
        "tool_call_chunk",
        "tool_call_start",
        "tool_call_done",
        "tool_result",
    }:
        return ""
    return message_id


def _stable_model_call_id(message_obj: Any) -> str:
    identifier = getattr(message_obj, "id", None)
    if isinstance(identifier, str) and identifier.strip():
        return identifier
    response_metadata = getattr(message_obj, "response_metadata", None)
    if isinstance(response_metadata, dict):
        response_id = response_metadata.get("id")
        if isinstance(response_id, str) and response_id.strip():
            return response_id
    return ""


def _telemetry_string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _normalize_metadata(value: Any) -> dict[str, Any]:
    """Normalize arbitrary metadata into a JSON-like dict."""

    if not isinstance(value, dict):
        return {}
    return {str(key): _normalize_json_like(item) for key, item in value.items()}


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
        return {str(key): _normalize_json_like(item) for key, item in value.items()}
    return str(value)


def _timestamp_from_debug(value: Any) -> float | None:
    """Parse a debug wrapper timestamp into UNIX seconds when possible."""

    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
