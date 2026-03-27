"""Unit tests for runtime event <-> AgentEvent protocol mapping."""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk, ToolMessage

from deepagents_runtime import events
from deepagents_runtime.converters import (
    agent_event_to_runtime_event,
    runtime_event_to_agent_event,
)
from deepagents_runtime.spec import RuntimeEventType
from deepagents_runtime.streams import (
    StreamParserState,
    _parse_ai_message,
    _parse_tool_message,
    parse_stream_part,
)


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


def test_runtime_event_roundtrip_preserves_subsecond_timestamp_precision() -> None:
    """protobuf transport should preserve subsecond RuntimeEvent timestamps."""

    event = events.run_canceled(
        "user requested cancel",
        run_id="run-ts",
        agent_name="demo-agent",
    )
    precise_event = type(event)(
        type=event.type,
        data=event.data,
        timestamp=1710000000.125,
        run_id=event.run_id,
        agent_name=event.agent_name,
    )

    proto_event = runtime_event_to_agent_event(precise_event)
    roundtrip = agent_event_to_runtime_event(proto_event)

    assert proto_event.timestamp.seconds == 1710000000
    assert proto_event.timestamp.nanos == 125000000
    assert roundtrip.timestamp == 1710000000.125


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


def test_tool_call_start_roundtrip_preserves_args_when_present() -> None:
    """tool_call_start should preserve structured args through protobuf."""

    event = events.tool_call_start(
        "execute",
        "tool-1",
        args={"command": "pwd"},
        run_id="run-2a",
        agent_name="demo-agent",
    )

    proto_event = runtime_event_to_agent_event(event)
    roundtrip = agent_event_to_runtime_event(proto_event)

    assert proto_event.WhichOneof("payload") == "tool_call_start"
    assert proto_event.tool_call_start.HasField("args")
    assert roundtrip.type == RuntimeEventType.TOOL_CALL_START
    assert roundtrip.data["args"] == {"command": "pwd"}


def test_tool_call_start_roundtrip_keeps_args_unset_when_missing() -> None:
    """tool_call_start should keep args unset instead of forcing an empty object."""

    event = events.tool_call_start(
        "execute",
        "tool-2",
        run_id="run-2b",
        agent_name="demo-agent",
    )

    proto_event = runtime_event_to_agent_event(event)
    roundtrip = agent_event_to_runtime_event(proto_event)

    assert proto_event.WhichOneof("payload") == "tool_call_start"
    assert proto_event.tool_call_start.HasField("args") is False
    assert roundtrip.type == RuntimeEventType.TOOL_CALL_START
    assert "args" not in roundtrip.data


def test_tool_result_roundtrip_preserves_structured_payload() -> None:
    """tool_result should preserve the raw structured payload through protobuf."""

    payload = {"stdout": "ok", "files": ["/tmp/a.txt"]}
    event = events.tool_result(
        "tool-structured",
        json.dumps(payload, separators=(",", ":")),
        payload=payload,
        run_id="run-2c",
        agent_name="demo-agent",
    )

    proto_event = runtime_event_to_agent_event(event)
    roundtrip = agent_event_to_runtime_event(proto_event)

    assert proto_event.WhichOneof("payload") == "tool_result"
    assert proto_event.tool_result.HasField("payload")
    assert roundtrip.type == RuntimeEventType.TOOL_RESULT
    assert roundtrip.data["payload"] == payload


def test_parse_tool_message_marks_error_results() -> None:
    """ToolMessage status=error should become tool_result.is_error=True."""

    state = StreamParserState(
        tool_call_buffers={
            0: {
                "name": "execute",
                "id": "tool-call-1",
                "args": None,
                "args_text": "",
                "started": True,
            }
        },
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


def test_parse_ai_message_emits_tool_call_start_with_structured_args() -> None:
    """Structured tool_call blocks should emit args on tool_call_start."""

    state = StreamParserState(run_id="run-3a", agent_name="demo-agent")
    message = SimpleNamespace(
        usage_metadata=None,
        content_blocks=[
            {
                "type": "tool_call",
                "name": "execute",
                "id": "tool-call-structured",
                "args": {"command": "pwd"},
            }
        ],
    )

    parsed_events = _parse_ai_message(message, state)

    assert len(parsed_events) == 1
    assert parsed_events[0].type == RuntimeEventType.TOOL_CALL_START
    assert parsed_events[0].data["args"] == {"command": "pwd"}


def test_parse_ai_message_aggregates_tool_call_chunks_and_starts_once() -> None:
    """Chunked tool args should be buffered until parsable and emit one start."""

    state = StreamParserState(run_id="run-3b", agent_name="demo-agent")
    first_chunk = SimpleNamespace(
        usage_metadata=None,
        content_blocks=[
            {
                "type": "tool_call_chunk",
                "name": "execute",
                "id": "tool-call-chunked",
                "index": 0,
                "args": '{"command":"pw',
            }
        ],
    )
    second_chunk = SimpleNamespace(
        usage_metadata=None,
        content_blocks=[
            {
                "type": "tool_call_chunk",
                "name": "execute",
                "id": "tool-call-chunked",
                "index": 0,
                "args": 'd"}',
            }
        ],
    )
    third_chunk = SimpleNamespace(
        usage_metadata=None,
        content_blocks=[
            {
                "type": "tool_call_chunk",
                "name": "execute",
                "id": "tool-call-chunked",
                "index": 0,
                "args": "",
            }
        ],
    )

    first_events = _parse_ai_message(first_chunk, state)
    second_events = _parse_ai_message(second_chunk, state)
    third_events = _parse_ai_message(third_chunk, state)

    assert first_events == []
    assert len(second_events) == 1
    assert second_events[0].type == RuntimeEventType.TOOL_CALL_START
    assert second_events[0].data["args"] == {"command": "pwd"}
    assert third_events == []


def test_parse_tool_message_preserves_structured_payload() -> None:
    """Structured ToolMessage content should become tool_result.payload."""

    state = StreamParserState(
        tool_call_buffers={
            0: {
                "name": "execute",
                "id": "tool-call-structured-result",
                "args": {"command": "pwd"},
                "args_text": "",
                "started": True,
            }
        },
        run_id="run-3c",
        agent_name="demo-agent",
    )
    payload = {"stdout": "ok", "files": ["/tmp/a.txt"]}
    message = ToolMessage(
        content="tool finished",
        artifact=payload,
        tool_call_id="tool-call-structured-result",
    )

    parsed_events = _parse_tool_message(message, state)

    assert len(parsed_events) == 2
    assert parsed_events[1].type == RuntimeEventType.TOOL_RESULT
    assert parsed_events[1].data["payload"] == payload
    assert parsed_events[1].data["content"] == "tool finished"


def test_parse_tool_message_emits_late_start_when_args_never_parse() -> None:
    """Tool results should backfill tool_call_start if streamed args never parsed."""

    state = StreamParserState(
        tool_call_buffers={
            0: {
                "name": "execute",
                "id": "tool-call-late-start",
                "args": None,
                "args_text": '{"command":"pw',
                "started": False,
            }
        },
        run_id="run-3d",
        agent_name="demo-agent",
    )
    message = ToolMessage(
        content="done",
        tool_call_id="tool-call-late-start",
    )

    parsed_events = _parse_tool_message(message, state)

    assert [event.type for event in parsed_events] == [
        RuntimeEventType.TOOL_CALL_START,
        RuntimeEventType.TOOL_CALL_DONE,
        RuntimeEventType.TOOL_RESULT,
    ]
    assert "args" not in parsed_events[0].data


def test_parse_stream_part_reads_v2_message_parts() -> None:
    """v2 message parts should be converted into runtime text events."""

    state = StreamParserState(run_id="run-4", agent_name="demo-agent")
    part = {
        "type": "messages",
        "ns": (),
        "data": (
            AIMessageChunk(content="hello v2"),
            {"langgraph_node": "model"},
        ),
    }

    parsed = parse_stream_part(part, state)

    assert len(parsed.events) == 1
    assert parsed.interrupts == {}
    assert parsed.events[0].type == RuntimeEventType.TEXT_DELTA
    assert parsed.events[0].data["text"] == "hello v2"
    assert state.full_response == ["hello v2"]


def test_parse_stream_part_buffers_v2_interrupts() -> None:
    """v2 updates parts should buffer validated HITL interrupts."""

    state = StreamParserState(run_id="run-5", agent_name="demo-agent")
    interrupt = SimpleNamespace(
        id="interrupt-1",
        value={
            "action_requests": [
                {
                    "name": "execute",
                    "args": {"command": "pwd"},
                    "description": "Run pwd",
                }
            ],
            "review_configs": [
                {
                    "action_name": "execute",
                    "allowed_decisions": ["approve", "reject"],
                }
            ],
        },
    )

    parsed = parse_stream_part(
        {
            "type": "updates",
            "ns": (),
            "data": {"__interrupt__": [interrupt]},
        },
        state,
    )

    assert parsed.events == []
    assert "interrupt-1" in parsed.interrupts
    assert parsed.interrupts["interrupt-1"]["action_requests"][0]["name"] == "execute"


def test_hitl_request_roundtrip_uses_action_request_name() -> None:
    """HITL requests should preserve LangChain action names over protobuf."""

    event = events.hitl_request(
        interrupt_id="interrupt-2",
        action_requests=[
            {
                "name": "execute",
                "args": {"command": "pwd"},
                "description": "Run pwd",
            }
        ],
        review_configs=[
            {
                "action_name": "execute",
                "allowed_decisions": ["approve", "reject"],
            }
        ],
        run_id="run-6",
        agent_name="demo-agent",
    )

    proto_event = runtime_event_to_agent_event(event)
    roundtrip = agent_event_to_runtime_event(proto_event)

    assert proto_event.hitl_request.interrupt_id == "interrupt-2"
    assert proto_event.hitl_request.action_requests[0].name == "execute"
    assert proto_event.hitl_request.action_requests[0].description == "Run pwd"
    assert proto_event.hitl_request.review_configs[0].action_name == "execute"
    assert roundtrip.type == RuntimeEventType.HITL_REQUEST
    assert roundtrip.data["action_requests"][0]["name"] == "execute"
    assert roundtrip.data["action_requests"][0]["description"] == "Run pwd"
    assert roundtrip.data["review_configs"][0]["allowed_decisions"] == [
        "approve",
        "reject",
    ]
