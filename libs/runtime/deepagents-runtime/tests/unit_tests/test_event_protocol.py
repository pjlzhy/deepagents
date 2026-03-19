"""Unit tests for runtime event <-> AgentEvent protocol mapping."""

from __future__ import annotations

from langchain_core.messages import ToolMessage

from deepagents_runtime import events
from deepagents_runtime.converters import (
    agent_event_to_runtime_event,
    runtime_event_to_agent_event,
)
from deepagents_runtime.spec import RuntimeEventType
from deepagents_runtime.streams import StreamParserState, _parse_tool_message


def test_run_canceled_roundtrip() -> None:
    """run_canceled should survive the protobuf transport boundary."""

    event = events.run_canceled(
        "user requested cancel",
        run_id="run-1",
        agent_name="demo-agent",
    )

    proto_event = runtime_event_to_agent_event(event)
    roundtrip = agent_event_to_runtime_event(proto_event)

    assert proto_event.WhichOneof("payload") == "run_canceled"
    assert proto_event.run_canceled.reason == "user requested cancel"
    assert roundtrip.type == RuntimeEventType.RUN_CANCELED
    assert roundtrip.data == {"reason": "user requested cancel"}
    assert roundtrip.run_id == "run-1"
    assert roundtrip.agent_name == "demo-agent"


def test_tool_result_roundtrip_preserves_is_error() -> None:
    """tool_result should preserve the is_error bit through protobuf."""

    event = events.tool_result(
        "tool-1",
        "command failed",
        is_error=True,
        run_id="run-2",
        agent_name="demo-agent",
    )

    proto_event = runtime_event_to_agent_event(event)
    roundtrip = agent_event_to_runtime_event(proto_event)

    assert proto_event.WhichOneof("payload") == "tool_result"
    assert proto_event.tool_result.is_error is True
    assert roundtrip.type == RuntimeEventType.TOOL_RESULT
    assert roundtrip.data["is_error"] is True


def test_parse_tool_message_marks_error_results() -> None:
    """ToolMessage status=error should become tool_result.is_error=True."""

    state = StreamParserState(
        tool_call_buffers={0: {"name": "execute", "id": "tool-call-1"}},
        run_id="run-3",
        agent_name="demo-agent",
    )
    message = ToolMessage(
        content="non-zero exit",
        tool_call_id="tool-call-1",
        status="error",
    )

    parsed_events = _parse_tool_message(message, state)

    assert len(parsed_events) == 2
    assert parsed_events[0].type == RuntimeEventType.TOOL_CALL_DONE
    assert parsed_events[1].type == RuntimeEventType.TOOL_RESULT
    assert parsed_events[1].data["content"] == "non-zero exit"
    assert parsed_events[1].data["is_error"] is True
