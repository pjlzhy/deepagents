"""Parse LangGraph stream output into RuntimeEvents.

Bridge between SDK-level `agent.astream()` output and the runtime's
universal `RuntimeEvent` system.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from pydantic import TypeAdapter

from langchain.agents.middleware.human_in_the_loop import HITLRequest
from deepagents_runtime import events
from deepagents_runtime.events import RuntimeEvent
from deepagents_runtime.runs import SessionStats

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LENGTH = 3
_MESSAGE_DATA_LENGTH = 2


@dataclass
class StreamParserState:
    """Run-scoped state accumulated while parsing stream output."""

    full_response: list[str] = field(default_factory=list)
    tool_call_buffers: dict[int | str, dict[str, str | None]] = field(
        default_factory=dict
    )
    stats: SessionStats = field(default_factory=SessionStats)
    run_id: str = ""
    agent_name: str = ""


@dataclass
class StreamParseResult:
    """Parser output for one stream part."""

    events: list[RuntimeEvent] = field(default_factory=list)
    interrupts: dict[str, Any] = field(default_factory=dict)


def parse_stream_part(
    part: object,
    state: StreamParserState,
) -> StreamParseResult:
    """Parse one v2 StreamPart into RuntimeEvents.

    Only root-agent parts (`ns == ()`) are processed.

    Args:
        part: Raw element from `agent.astream(version="v2")`. Expected to be
            a dict with `type`, `ns`, and `data`.
        state: Mutable parser state.

    Returns:
        Parsed runtime events and validated interrupts from this part.
    """
    if not isinstance(part, dict):
        return StreamParseResult()

    namespace = part.get("ns", ())
    stream_mode = part.get("type")
    data = part.get("data")

    if namespace:  # skip sub-agent parts
        return StreamParseResult()

    if (
        stream_mode == "updates"
        and isinstance(data, dict)
        and "__interrupt__" in data
    ):
        return _parse_interrupts(data, state)
    if stream_mode == "messages":
        return StreamParseResult(events=_parse_message_chunk(data, state))

    return StreamParseResult()


def parse_stream_chunk(
    chunk: object,
    state: StreamParserState,
) -> StreamParseResult:
    """Compatibility wrapper for callers still handing in v1 tuple chunks."""
    if isinstance(chunk, dict):
        return parse_stream_part(chunk, state)

    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
        return StreamParseResult()

    namespace, stream_mode, data = chunk
    return parse_stream_part(
        {
            "type": stream_mode,
            "ns": namespace,
            "data": data,
        },
        state,
    )


def _parse_interrupts(
    data: dict[str, Any],
    state: StreamParserState,
) -> StreamParseResult:
    """Extract HITL interrupts from an updates chunk.

    Returns validated interrupts separately from event emission so the
    outer runtime loop can own HITL control flow.
    """
    result = StreamParseResult()

    for interrupt_obj in data.get("__interrupt__", []):
        interrupt_id = getattr(interrupt_obj, "id", str(id(interrupt_obj)))
        interrupt_value = getattr(interrupt_obj, "value", interrupt_obj)

        # Validate as HITLRequest
        try:
            adapter = TypeAdapter(HITLRequest)
            validated = adapter.validate_python(interrupt_value)
        except Exception:
            logger.warning("Rejecting malformed HITL interrupt %s", interrupt_id)
            result.events.append(
                events.error_event(
                    f"Malformed HITL interrupt: {interrupt_id}",
                    run_id=state.run_id,
                    agent_name=state.agent_name,
                )
            )
            continue

        result.interrupts[interrupt_id] = validated
    return result


def _parse_message_chunk(
    data: Any,
    state: StreamParserState,
) -> list[RuntimeEvent]:
    """Parse a messages-mode chunk into RuntimeEvents."""
    if not isinstance(data, tuple) or len(data) != _MESSAGE_DATA_LENGTH:
        return []

    message_obj, metadata = data

    # Filter out summarization middleware synthetic messages
    if metadata and isinstance(metadata, dict):
        if metadata.get("lc_source") == "summarization":
            return []

    # Lazy import to avoid hard SDK dependency at module load
    try:
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
    except ImportError:
        return []

    if isinstance(message_obj, (AIMessage, AIMessageChunk)):
        return _parse_ai_message(message_obj, state)
    elif isinstance(message_obj, ToolMessage):
        return _parse_tool_message(message_obj, state)

    return []


def _parse_ai_message(
    message_obj: Any,
    state: StreamParserState,
) -> list[RuntimeEvent]:
    """Extract text deltas and tool call starts from an AI message."""
    result: list[RuntimeEvent] = []

    # Record token usage
    usage = getattr(message_obj, "usage_metadata", None)
    if usage and isinstance(usage, dict):
        input_toks = usage.get("input_tokens", 0)
        output_toks = usage.get("output_tokens", 0)
        if input_toks or output_toks:
            state.stats.record_request("", input_toks, output_toks)

    content_blocks = getattr(message_obj, "content_blocks", None)
    if content_blocks is None:
        return result

    for block in content_blocks:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")

        if block_type == "text":
            text = block.get("text", "")
            if text:
                state.full_response.append(text)
                result.append(
                    events.text_delta(
                        text,
                        run_id=state.run_id,
                        agent_name=state.agent_name,
                    )
                )

        elif block_type in {"tool_call_chunk", "tool_call"}:
            chunk_name = block.get("name")
            chunk_id = block.get("id")
            chunk_index = block.get("index")

            buffer_key: int | str = (
                chunk_index
                if chunk_index is not None
                else (
                    chunk_id
                    if chunk_id is not None
                    else f"unknown-{len(state.tool_call_buffers)}"
                )
            )

            if buffer_key not in state.tool_call_buffers:
                state.tool_call_buffers[buffer_key] = {"name": None, "id": None}
            if chunk_id:
                state.tool_call_buffers[buffer_key]["id"] = str(chunk_id)
            if chunk_name:
                state.tool_call_buffers[buffer_key]["name"] = chunk_name
                result.append(
                    events.tool_call_start(
                        tool_name=chunk_name,
                        tool_call_id=str(chunk_id or buffer_key),
                        run_id=state.run_id,
                        agent_name=state.agent_name,
                    )
                )

    return result


def _parse_tool_message(
    message_obj: Any,
    state: StreamParserState,
) -> list[RuntimeEvent]:
    """Parse a ToolMessage into tool_call_done + tool_result events.

    Emits ``tool_call_done`` first (signalling the tool invocation finished),
    then ``tool_result`` with the output content.
    """
    tool_call_id = getattr(message_obj, "tool_call_id", "")
    content = message_obj.content
    if not isinstance(content, str):
        content = str(content)
    is_error = getattr(message_obj, "status", "") == "error"

    # Resolve tool name from buffered tool calls
    tool_name = ""
    for buf in state.tool_call_buffers.values():
        if buf.get("id") == tool_call_id:
            tool_name = buf.get("name", "") or ""
            break

    return [
        events.tool_call_done(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            run_id=state.run_id,
            agent_name=state.agent_name,
        ),
        events.tool_result(
            tool_call_id=tool_call_id,
            content=content,
            is_error=is_error,
            run_id=state.run_id,
            agent_name=state.agent_name,
        ),
    ]
