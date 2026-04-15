"""Telemetry primitives and LangGraph stream parsing for monitoring flows."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import time
from typing import Any

from langchain.agents.middleware.human_in_the_loop import HITLRequest
from pydantic import TypeAdapter

from agents_runtime import events
from agents_runtime.events import RuntimeEvent
from agents_runtime.langgraph_stream import (
    CheckpointView,
    CustomPartView,
    DebugPartView,
    MessageMetadataView,
    MessageObjectView,
    MessagesPartView,
    TaskResultView,
    TaskStartView,
    UpdatesPartView,
    wrap_stream_part,
)
from agents_runtime.runs import SessionStats
from agents_runtime.spec import RuntimeEventType
from agents_runtime.streams import (
    _UNSUPPORTED_PAYLOAD,
    _buffer_args,
    _json_like_payload,
    _tool_result_text,
    _try_parse_tool_args,
)

AUDIT_SCHEMA_VERSION = 1
TELEMETRY_RETENTION_DURABLE = "durable"
TELEMETRY_RETENTION_STREAM_ONLY = "stream_only"

_TELEMETRY_METADATA_DROP_KEYS = frozenset(
    {
        "agent_name",
        "checkpoint_ns",
        "langgraph_checkpoint_ns",
        "langgraph_node",
        "langgraph_path",
        "ls_model_type",
        "ls_temperature",
        "run_id",
        "thread_id",
        "updated_at",
    }
)
_GENERIC_TELEMETRY_PAYLOAD_DROP_KEYS = frozenset(
    {
        "agent_name",
        "attempt",
        "event_id",
        "id",
        "index",
        "interrupt_id",
        "message_id",
        "model_call_id",
        "run_id",
        "seq",
        "thread_id",
        "tool_call_id",
        "tool_name",
        "type",
    }
)


@dataclass(frozen=True)
class TelemetryEvent:
    """Structured audit event emitted by the runtime telemetry stream.

    Args:
        stream_mode: Source stream mode such as `messages`, `updates`, `debug`,
            `custom`, or runtime-owned `lifecycle`.
        event_type: Fine-grained event type within the stream mode.
        payload: Structured payload for the event.
        namespace: LangGraph namespace path. Empty means the root graph.
        metadata: Structured metadata associated with the event.
        timestamp: UNIX timestamp for the event.
        run_id: Execution run identifier.
        thread_id: Conversation thread identifier associated with the run.
        agent_name: Name of the producing agent.
        schema_version: Stable audit event schema version.
        retention: Whether this event should be persisted or streamed only.
    """

    stream_mode: str
    event_type: str
    payload: Any = None
    namespace: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    run_id: str = ""
    thread_id: str = ""
    agent_name: str = ""
    schema_version: int = AUDIT_SCHEMA_VERSION
    retention: str = TELEMETRY_RETENTION_DURABLE
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
    thread_id: str = ""
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
    namespace: tuple[str, ...] = (),
    stream_mode: str = "lifecycle",
    thread_id: str = "",
) -> TelemetryEvent:
    """Project a public `RuntimeEvent` into one audit event."""

    resolved_thread_id = thread_id
    if not resolved_thread_id:
        raw_thread_id = event.data.get("thread_id")
        resolved_thread_id = raw_thread_id if isinstance(raw_thread_id, str) else ""

    return TelemetryEvent(
        stream_mode=stream_mode,
        event_type=_telemetry_event_type_from_runtime_event(event.type),
        payload=_normalize_json_like(event.data),
        namespace=namespace,
        metadata={},
        timestamp=event.timestamp,
        run_id=event.run_id,
        thread_id=resolved_thread_id,
        agent_name=event.agent_name,
        retention=_retention_for_runtime_event_type(event.type),
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
    thread_id = event.thread_id or _telemetry_string(payload.get("thread_id"))

    resolved = replace(
        event,
        event_id=event_id,
        attempt=attempt,
        seq=seq,
        thread_id=thread_id,
        node_name=node_name,
        task_id=task_id,
        model_call_id=model_call_id,
        tool_call_id=tool_call_id,
        interrupt_id=interrupt_id,
        message_id=message_id,
    )
    return replace(
        resolved,
        metadata=_compact_telemetry_metadata(resolved),
        payload=_compact_telemetry_payload(resolved),
    )


def parse_telemetry_stream_part(
    part: object,
    state: TelemetryParserState,
) -> TelemetryParseResult:
    """Parse one LangGraph v2 stream part into telemetry events.

    Unlike the public runtime event parser, telemetry retains non-root
    namespaces and richer stream modes such as `debug` and `custom`.
    """

    part_view = wrap_stream_part(part)

    if isinstance(part_view, MessagesPartView):
        return _parse_message_part_view(part_view, state)
    if isinstance(part_view, UpdatesPartView):
        return _parse_updates_part_view(part_view, state)
    if isinstance(part_view, DebugPartView):
        return _parse_debug_part_view(part_view, state)
    if isinstance(part_view, CustomPartView):
        return TelemetryParseResult(
            events=[
                TelemetryEvent(
                    stream_mode="custom",
                    event_type="custom",
                    payload=_normalize_json_like(part_view.structure.value),
                    namespace=part_view.header.ns.structure.segments,
                    metadata={},
                    run_id=state.run_id,
                    thread_id=state.thread_id,
                    agent_name=state.agent_name,
                    retention=TELEMETRY_RETENTION_DURABLE,
                )
            ]
        )
    return TelemetryParseResult()


def _parse_message_part_view(
    part_view: MessagesPartView,
    state: TelemetryParserState,
) -> TelemetryParseResult:
    """Parse one wrapped `messages` stream part into telemetry events."""

    message_view = part_view.structure.message
    if message_view is None:
        return TelemetryParseResult()
    namespace = part_view.header.ns.structure.segments
    metadata = _metadata_from_message_view(part_view.structure.metadata)

    if message_view.classification.kind == "ai":
        return TelemetryParseResult(
            events=_parse_ai_message_view(message_view, namespace, metadata, state)
        )
    if message_view.classification.kind == "tool":
        return TelemetryParseResult(
            events=_parse_tool_message_view(message_view, namespace, metadata, state)
        )
    return TelemetryParseResult()


def _parse_ai_message_view(
    message_view: MessageObjectView,
    namespace: tuple[str, ...],
    metadata: dict[str, Any],
    state: TelemetryParserState,
) -> list[TelemetryEvent]:
    """Parse one wrapped AI message into telemetry events."""

    result: list[TelemetryEvent] = []
    content_blocks = message_view.structure.content_blocks
    usage = message_view.structure.usage_metadata
    if usage and isinstance(usage, dict):
        input_toks = usage.get("input_tokens", 0)
        output_toks = usage.get("output_tokens", 0)
        if input_toks or output_toks:
            state.stats.record_request("", input_toks, output_toks)

    model_call_id = _stable_model_call_id_from_view(message_view)

    for block_view in content_blocks:
        payload = _normalize_json_like(block_view.raw)
        if not isinstance(payload, dict):
            continue

        block_type = block_view.structure.type_name or "message_block"
        if model_call_id and block_type not in {"tool_call", "tool_call_chunk"}:
            payload["model_call_id"] = model_call_id
        timestamp = time.time()

        if block_type == "text":
            text = block_view.structure.text or ""
            if text and not namespace:
                state.full_response.append(text)
        elif block_type in {"tool_call_chunk", "tool_call"}:
            result.append(
                TelemetryEvent(
                    stream_mode="messages",
                    event_type=block_type,
                    payload=payload,
                    namespace=namespace,
                    metadata=metadata,
                    timestamp=timestamp,
                    run_id=state.run_id,
                    thread_id=state.thread_id,
                    agent_name=state.agent_name,
                    model_call_id=model_call_id,
                    retention=TELEMETRY_RETENTION_STREAM_ONLY,
                )
            )
            result.extend(
                _maybe_emit_tool_call_start(
                    block=payload,
                    namespace=namespace,
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
                namespace=namespace,
                metadata=metadata,
                timestamp=timestamp,
                run_id=state.run_id,
                thread_id=state.thread_id,
                agent_name=state.agent_name,
                model_call_id=model_call_id,
                retention=TELEMETRY_RETENTION_STREAM_ONLY,
            )
        )

    return result


def _maybe_emit_tool_call_start(
    *,
    block: dict[str, Any],
    namespace: tuple[str, ...],
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
        (*namespace, str(chunk_index))
        if chunk_index is not None
        else (
            (*namespace, str(chunk_id))
            if chunk_id is not None
            else (*namespace, f"unknown-{len(state.tool_call_buffers)}")
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
            namespace=namespace,
            metadata=metadata,
            timestamp=timestamp,
            run_id=state.run_id,
            thread_id=state.thread_id,
            agent_name=state.agent_name,
            retention=TELEMETRY_RETENTION_DURABLE,
        )
    ]


def _parse_tool_message_view(
    message_view: MessageObjectView,
    namespace: tuple[str, ...],
    metadata: dict[str, Any],
    state: TelemetryParserState,
) -> list[TelemetryEvent]:
    """Parse one wrapped tool message into telemetry events."""

    tool_call_id = message_view.structure.tool_call_id or ""
    raw_content = message_view.structure.content
    is_error = message_view.structure.status == "error"
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
                    namespace=namespace,
                    metadata=metadata,
                    timestamp=timestamp,
                    run_id=state.run_id,
                    thread_id=state.thread_id,
                    agent_name=state.agent_name,
                    retention=TELEMETRY_RETENTION_DURABLE,
                )
            )
        break

    raw_payload = (
        message_view.structure.artifact
        if message_view.structure.has_artifact
        else _UNSUPPORTED_PAYLOAD
    )
    payload = (
        _json_like_payload(raw_payload)
        if raw_payload is not _UNSUPPORTED_PAYLOAD
        else _json_like_payload(raw_content)
    )
    content = _tool_result_text(raw_content, payload)

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
            namespace=namespace,
            metadata=metadata,
            timestamp=timestamp,
            run_id=state.run_id,
            thread_id=state.thread_id,
            agent_name=state.agent_name,
            retention=TELEMETRY_RETENTION_STREAM_ONLY,
        ),
        TelemetryEvent(
            stream_mode="messages",
            event_type="tool_result",
            payload=_normalize_json_like(result_payload),
            namespace=namespace,
            metadata=metadata,
            timestamp=timestamp,
            run_id=state.run_id,
            thread_id=state.thread_id,
            agent_name=state.agent_name,
            retention=TELEMETRY_RETENTION_DURABLE,
        ),
    ]


def _parse_updates_part_view(
    part_view: UpdatesPartView,
    state: TelemetryParserState,
) -> TelemetryParseResult:
    """Parse one wrapped `updates` stream part and retain only interrupt semantics."""

    result = TelemetryParseResult()
    timestamp = time.time()
    namespace = part_view.header.ns.structure.segments
    if not part_view.classification.interrupts:
        return result

    adapter = TypeAdapter(HITLRequest)
    for interrupt_view in part_view.classification.interrupts:
        interrupt_id = interrupt_view.structure.id or str(id(interrupt_view.raw))
        interrupt_value = (
            interrupt_view.structure.value
            if interrupt_view.structure.value is not None
            else interrupt_view.raw
        )
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
                    namespace=namespace,
                    thread_id=state.thread_id,
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
                namespace=namespace,
                metadata={},
                timestamp=timestamp,
                run_id=state.run_id,
                thread_id=state.thread_id,
                agent_name=state.agent_name,
                retention=TELEMETRY_RETENTION_STREAM_ONLY,
            )
        )

    return result


def _parse_debug_part_view(
    part_view: DebugPartView,
    state: TelemetryParserState,
) -> TelemetryParseResult:
    """Parse one wrapped `debug` stream part into telemetry events."""

    namespace = part_view.header.ns.structure.segments
    event_type = part_view.classification.variant
    metadata: dict[str, Any] = {}
    if part_view.structure.step is not None:
        metadata["step"] = _normalize_json_like(part_view.structure.step)
    timestamp = _timestamp_from_debug(part_view.structure.timestamp) or time.time()

    if event_type == "checkpoint":
        checkpoint_view = (
            part_view.structure.event.structure.payload
            if part_view.structure.event is not None
            else None
        )
        _update_checkpoint_bounds_from_view(checkpoint_view, state)
        return TelemetryParseResult()

    if event_type == "task":
        task_view = (
            part_view.structure.event.structure.payload
            if part_view.structure.event is not None
            else None
        )
        task_id = task_view.structure.id if task_view is not None else ""
        if task_id:
            task_key = (namespace, task_id)
            if task_key in state.emitted_task_keys:
                return TelemetryParseResult()
            state.emitted_task_keys.add(task_key)
        payload = _compact_debug_task_payload_view(task_view)
    elif event_type == "task_result":
        task_result_view = (
            part_view.structure.event.structure.payload
            if part_view.structure.event is not None
            else None
        )
        payload = _compact_debug_task_result_payload_view(task_result_view)
    else:
        return TelemetryParseResult()

    return TelemetryParseResult(
        events=[
            TelemetryEvent(
                stream_mode="debug",
                event_type=event_type,
                payload=_normalize_json_like(payload),
                namespace=namespace,
                metadata=metadata,
                timestamp=timestamp,
                run_id=state.run_id,
                thread_id=state.thread_id,
                agent_name=state.agent_name,
                retention=TELEMETRY_RETENTION_STREAM_ONLY,
            )
        ]
    )


def _metadata_from_message_view(
    metadata_view: MessageMetadataView | None,
) -> dict[str, Any]:
    """Convert one wrapped message metadata object into telemetry metadata."""

    if metadata_view is None:
        return {}

    metadata: dict[str, Any] = {
        key: _normalize_json_like(value)
        for key, value in metadata_view.structure.extras.items()
    }
    if metadata_view.structure.langgraph_node is not None:
        metadata["langgraph_node"] = metadata_view.structure.langgraph_node
    if metadata_view.structure.langgraph_step is not None:
        metadata["langgraph_step"] = metadata_view.structure.langgraph_step
    if metadata_view.structure.langgraph_triggers:
        metadata["langgraph_triggers"] = list(metadata_view.structure.langgraph_triggers)
    if metadata_view.structure.langgraph_path:
        metadata["langgraph_path"] = _normalize_json_like(
            metadata_view.structure.langgraph_path
        )
    if metadata_view.structure.ls_provider is not None:
        metadata["ls_provider"] = metadata_view.structure.ls_provider
    if metadata_view.structure.ls_model_name is not None:
        metadata["ls_model_name"] = metadata_view.structure.ls_model_name
    return metadata


def _compact_telemetry_metadata(event: TelemetryEvent) -> dict[str, Any]:
    """Drop envelope duplicates and noisy framework internals from metadata."""

    if not isinstance(event.metadata, dict):
        return {}

    compact: dict[str, Any] = {}
    for key, value in event.metadata.items():
        if key in _TELEMETRY_METADATA_DROP_KEYS:
            continue
        if key == "lc_agent_name" and value == event.agent_name:
            continue
        if _telemetry_value_is_empty(value):
            continue
        compact[key] = value
    return compact


def _compact_telemetry_payload(event: TelemetryEvent) -> Any:
    """Shrink one telemetry payload down to event-specific semantics only."""

    if event.event_type == "custom":
        return event.payload
    if not isinstance(event.payload, dict):
        return event.payload

    payload = event.payload
    event_type = event.event_type
    if event_type == "run_started":
        return {}
    if event_type in {"text", "text_done"}:
        return _compact_text_payload(payload)
    if event_type == "reasoning":
        return _compact_reasoning_payload(payload)
    if event_type in {"tool_call", "tool_call_chunk"}:
        return _compact_tool_call_chunk_payload(payload)
    if event_type == "tool_call_start":
        return _compact_tool_call_start_payload(payload)
    if event_type == "tool_call_done":
        return {}
    if event_type == "tool_result":
        return _compact_tool_result_payload(payload)
    if event_type in {"interrupt", "hitl_request"}:
        return _compact_interrupt_payload(payload)
    if event_type == "task":
        return _compact_task_payload(event, payload)
    if event_type == "task_result":
        return _compact_task_result_payload(payload)
    if event_type == "run_ended":
        return _compact_run_ended_payload(payload)
    if event_type == "run_canceled":
        return _compact_run_canceled_payload(payload)
    if event_type == "error":
        return _compact_error_payload(payload)
    return _compact_generic_payload(payload)


def _compact_text_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text")
    if isinstance(text, str) and text:
        return {"text": text}
    return {}


def _compact_reasoning_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    summary = _compact_reasoning_summary(payload.get("summary"))
    if summary:
        compact["summary"] = summary

    text = payload.get("reasoning")
    if not isinstance(text, str):
        text = payload.get("text")
    if isinstance(text, str) and text:
        compact["text"] = text
    return compact


def _compact_reasoning_summary(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []

    summary: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text:
                summary.append({"text": text})
                continue
            compact_item = {
                key: part
                for key, part in item.items()
                if key != "type" and not _telemetry_value_is_empty(part)
            }
            if compact_item:
                summary.append(compact_item)
            continue

        normalized = _normalize_json_like(item)
        if not _telemetry_value_is_empty(normalized):
            summary.append(normalized)
    return summary


def _compact_tool_call_chunk_payload(payload: dict[str, Any]) -> dict[str, Any]:
    args = payload.get("args")
    if isinstance(args, dict) and args:
        return {"args": args}
    if isinstance(args, str) and args:
        return {"args_text": args}
    return {}


def _compact_tool_call_start_payload(payload: dict[str, Any]) -> dict[str, Any]:
    args = payload.get("args")
    if _telemetry_value_is_empty(args):
        return {}
    return {"args": args}


def _compact_tool_result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}

    content = payload.get("content")
    if isinstance(content, str) and content:
        compact["content"] = content

    is_error = payload.get("is_error")
    if isinstance(is_error, bool):
        compact["is_error"] = is_error

    data = payload.get("payload")
    if data is None:
        data = payload.get("data")
    if data is not None and not _telemetry_value_is_empty(data):
        compact["data"] = data
    return compact


def _compact_interrupt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    action_requests = payload.get("action_requests")
    if isinstance(action_requests, list) and action_requests:
        compact["action_requests"] = action_requests

    review_configs = payload.get("review_configs")
    if isinstance(review_configs, list) and review_configs:
        compact["review_configs"] = review_configs
    return compact


def _compact_task_payload(
    event: TelemetryEvent,
    payload: dict[str, Any],
) -> dict[str, Any]:
    compact: dict[str, Any] = {}

    name = payload.get("name")
    if isinstance(name, str) and name and name != event.node_name:
        compact["name"] = name

    triggers = payload.get("triggers")
    if isinstance(triggers, list) and triggers:
        compact["triggers"] = triggers

    task_input = payload.get("input")
    if not _telemetry_value_is_empty(task_input):
        compact["input"] = task_input
    return compact


def _compact_task_result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    error = payload.get("error")
    if isinstance(error, str) and error:
        compact["error"] = error

    interrupts = payload.get("interrupts")
    if isinstance(interrupts, list) and interrupts:
        compact["interrupts"] = interrupts

    result = payload.get("result")
    if not _telemetry_value_is_empty(result):
        compact["result"] = result
    return compact


def _compact_run_ended_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stats = payload.get("stats")
    if isinstance(stats, dict) and stats:
        return {"stats": stats}
    return {}


def _compact_run_canceled_payload(payload: dict[str, Any]) -> dict[str, Any]:
    reason = payload.get("reason")
    if isinstance(reason, str) and reason:
        return {"reason": reason}
    return {}


def _compact_error_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    message = payload.get("message")
    if isinstance(message, str) and message:
        compact["message"] = message

    error_type = payload.get("error_type")
    if isinstance(error_type, str) and error_type:
        compact["error_type"] = error_type
    return compact


def _compact_generic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in _GENERIC_TELEMETRY_PAYLOAD_DROP_KEYS
        and not _telemetry_value_is_empty(value)
    }


def _stable_model_call_id_from_view(message_view: MessageObjectView) -> str:
    """Return the stable model call ID for one wrapped message."""

    identifier = message_view.structure.id
    if isinstance(identifier, str) and identifier.strip():
        return identifier
    response_metadata = message_view.structure.response_metadata or {}
    response_id = response_metadata.get("id")
    if isinstance(response_id, str) and response_id.strip():
        return response_id
    return ""


def _update_checkpoint_bounds_from_view(
    checkpoint_view: CheckpointView | None,
    state: TelemetryParserState,
) -> None:
    """Track checkpoint boundaries from one wrapped checkpoint payload."""

    if checkpoint_view is None:
        return

    parent_config = checkpoint_view.structure.parent_config
    checkpoint_config = checkpoint_view.structure.config
    parent_checkpoint_id = (
        parent_config.classification.checkpoint_id if parent_config is not None else ""
    )
    checkpoint_id = (
        checkpoint_config.classification.checkpoint_id
        if checkpoint_config is not None
        else ""
    )

    if not state.start_checkpoint_id and parent_checkpoint_id:
        state.start_checkpoint_id = parent_checkpoint_id
    if checkpoint_id:
        state.end_checkpoint_id = checkpoint_id


def _compact_debug_task_payload_view(task_view: TaskStartView | None) -> dict[str, Any]:
    """Drop repeated thread-state blobs from one wrapped debug task payload."""

    if task_view is None:
        return {}

    compact: dict[str, Any] = {}
    if task_view.structure.id is not None:
        compact["id"] = task_view.structure.id
    if task_view.structure.name is not None:
        compact["name"] = task_view.structure.name
    if task_view.structure.triggers:
        compact["triggers"] = list(task_view.structure.triggers)
    if task_view.classification.has_input:
        compact["input"] = _compact_debug_state(task_view.structure.input)
    return compact


def _compact_debug_task_result_payload_view(
    task_result_view: TaskResultView | None,
) -> dict[str, Any]:
    """Drop repeated thread-state blobs from one wrapped debug task_result payload."""

    if task_result_view is None:
        return {}

    compact: dict[str, Any] = {}
    if task_result_view.structure.id is not None:
        compact["id"] = task_result_view.structure.id
    if task_result_view.structure.error is not None:
        compact["error"] = task_result_view.structure.error
    if task_result_view.structure.interrupts:
        compact["interrupts"] = _normalize_json_like(
            [interrupt.raw for interrupt in task_result_view.structure.interrupts]
        )
    if task_result_view.classification.has_result:
        compact["result"] = _compact_debug_state(task_result_view.structure.result)
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


def _retention_for_runtime_event_type(event_type: RuntimeEventType) -> str:
    """Return the default retention policy for one public runtime event."""

    mapping = {
        RuntimeEventType.RUN_START: TELEMETRY_RETENTION_DURABLE,
        RuntimeEventType.TEXT_DELTA: TELEMETRY_RETENTION_STREAM_ONLY,
        RuntimeEventType.TEXT_DONE: TELEMETRY_RETENTION_DURABLE,
        RuntimeEventType.TOOL_CALL_START: TELEMETRY_RETENTION_DURABLE,
        RuntimeEventType.TOOL_CALL_DONE: TELEMETRY_RETENTION_STREAM_ONLY,
        RuntimeEventType.TOOL_RESULT: TELEMETRY_RETENTION_DURABLE,
        RuntimeEventType.HITL_REQUEST: TELEMETRY_RETENTION_DURABLE,
        RuntimeEventType.RUN_END: TELEMETRY_RETENTION_DURABLE,
        RuntimeEventType.RUN_CANCELED: TELEMETRY_RETENTION_DURABLE,
        RuntimeEventType.ERROR: TELEMETRY_RETENTION_DURABLE,
    }
    return mapping[event_type]


def _derive_node_name(
    event: TelemetryEvent,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    if event.stream_mode == "lifecycle":
        return "run"

    payload_name = _telemetry_string(payload.get("name"))
    if payload_name:
        return payload_name

    payload_tool_name = _telemetry_string(payload.get("tool_name"))
    if payload_tool_name:
        return payload_tool_name

    metadata_node = _telemetry_string(metadata.get("langgraph_node"))
    if metadata_node:
        return metadata_node

    if event.namespace:
        raw = event.namespace[-1]
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
    return ""


def _derive_interrupt_id(event: TelemetryEvent, payload: dict[str, Any]) -> str:
    interrupt_id = _telemetry_string(payload.get("interrupt_id"))
    if interrupt_id:
        return interrupt_id
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


def _telemetry_string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _telemetry_value_is_empty(value: Any) -> bool:
    return value is None or value == "" or (
        isinstance(value, (dict, list, tuple)) and not value
    )


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
