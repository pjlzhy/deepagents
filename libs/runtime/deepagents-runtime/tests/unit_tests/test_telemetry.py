"""Unit tests for telemetry stream parsing and protobuf conversion."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk, ToolMessage

from deepagents_runtime.converters import telemetry_event_to_proto
from deepagents_runtime.telemetry import (
    TelemetryParserState,
    finalize_telemetry_event,
    parse_telemetry_stream_part,
    telemetry_from_runtime_event,
)
from deepagents_runtime import events


def test_parse_telemetry_stream_part_keeps_non_root_reasoning_blocks() -> None:
    """Reasoning blocks from non-root namespaces should be preserved."""

    state = TelemetryParserState(run_id="run-telemetry", agent_name="demo-agent")
    part = {
        "type": "messages",
        "ns": ("task:research",),
        "data": (
            AIMessageChunk(
                content=[
                    {
                        "type": "reasoning",
                        "summary": [
                            {"type": "summary_text", "text": "thinking..."}
                        ],
                        "id": "rs_1",
                    }
                ]
            ),
            {"langgraph_node": "planner", "langgraph_step": 2},
        ),
    }

    parsed = parse_telemetry_stream_part(part, state)

    assert parsed.interrupts == {}
    assert len(parsed.events) == 1
    event = parsed.events[0]
    assert event.stream_mode == "messages"
    assert event.event_type == "reasoning"
    assert event.ns == ("task:research",)
    assert event.metadata["langgraph_node"] == "planner"
    assert event.payload["summary"][0]["text"] == "thinking..."
    assert event.public_event is None


def test_parse_telemetry_stream_part_uses_one_model_call_id_per_ai_message() -> None:
    """All non-tool blocks from one AI message should share one model call ID."""

    state = TelemetryParserState(run_id="run-telemetry", agent_name="demo-agent")
    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            AIMessageChunk(
                id="resp_model_1",
                content=[
                    {
                        "type": "reasoning",
                        "summary": [
                            {"type": "summary_text", "text": "thinking..."}
                        ],
                        "id": "rs_1",
                    },
                    {
                        "type": "text",
                        "text": "hello",
                        "id": "msg_1",
                    },
                ],
            ),
            {"langgraph_node": "model"},
        ),
    }

    parsed = parse_telemetry_stream_part(part, state)

    assert len(parsed.events) == 2
    assert parsed.events[0].model_call_id == "resp_model_1"
    assert parsed.events[1].model_call_id == "resp_model_1"
    assert parsed.events[0].payload["model_call_id"] == "resp_model_1"
    assert parsed.events[1].payload["model_call_id"] == "resp_model_1"


def test_parse_telemetry_stream_part_emits_state_update_and_interrupt() -> None:
    """Updates parts should preserve state updates and interrupts together."""

    state = TelemetryParserState(run_id="run-updates", agent_name="demo-agent")
    interrupt = SimpleNamespace(
        id="interrupt-1",
        value={
            "action_requests": [
                {"name": "execute", "args": {"command": "pwd"}}
            ],
            "review_configs": [],
        },
    )
    part = {
        "type": "updates",
        "ns": ("task:worker",),
        "data": {
            "planner": {"todos": [{"content": "inspect repo"}]},
            "__metadata__": {"langgraph_node": "planner"},
            "__interrupt__": [interrupt],
        },
    }

    parsed = parse_telemetry_stream_part(part, state)

    assert "interrupt-1" in parsed.interrupts
    assert parsed.interrupts["interrupt-1"]["action_requests"][0]["name"] == "execute"
    assert [event.event_type for event in parsed.events] == [
        "update_metadata",
        "state_update",
        "interrupt",
    ]
    assert parsed.events[1].payload["planner"]["todos"][0]["content"] == "inspect repo"
    assert parsed.events[2].ns == ("task:worker",)


def test_parse_telemetry_stream_part_emits_tool_result_projection() -> None:
    """ToolMessage payloads should become tool_call_done and tool_result telemetry."""

    state = TelemetryParserState(
        run_id="run-tools",
        agent_name="demo-agent",
        tool_call_buffers={
            ("0",): {
                "name": "execute",
                "id": "tool-call-1",
                "args": {"command": "pwd"},
                "args_text": "",
                "started": True,
            }
        },
    )
    part = {
        "type": "messages",
        "ns": (),
        "data": (
            ToolMessage(
                content="command finished",
                artifact={"stdout": "ok"},
                tool_call_id="tool-call-1",
            ),
            {"langgraph_node": "tools"},
        ),
    }

    parsed = parse_telemetry_stream_part(part, state)

    assert [event.event_type for event in parsed.events] == [
        "tool_call_done",
        "tool_result",
    ]
    assert parsed.events[1].payload["payload"]["stdout"] == "ok"
    assert parsed.events[1].public_event is not None


def test_telemetry_event_to_proto_preserves_public_event_and_namespace() -> None:
    """Telemetry protobuf mapping should preserve namespace and embedded public event."""

    event = telemetry_from_runtime_event(
        events.run_start(
            run_id="run-proto",
            agent_name="demo-agent",
            thread_id="thread-1",
        ),
        ns=("task:root",),
    )

    proto = telemetry_event_to_proto(
        finalize_telemetry_event(event, attempt=1, seq=1)
    )

    assert list(proto.ns) == ["task:root"]
    assert proto.stream_mode == "lifecycle"
    assert proto.event_type == "run_started"
    assert proto.event_id == "run-proto:1:1"
    assert proto.attempt == 1
    assert proto.seq == 1
    assert proto.node_name == "run"
    assert proto.HasField("public_event")
    assert proto.public_event.run_started.thread_id == "thread-1"
