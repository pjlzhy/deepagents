"""Unit tests for telemetry stream parsing and protobuf conversion."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk, ToolMessage

from agents_runtime.converters import telemetry_event_to_proto
from agents_runtime.generated import runtime_pb2 as pb2
from agents_runtime.telemetry import (
    TelemetryParserState,
    TELEMETRY_RETENTION_DURABLE,
    TELEMETRY_RETENTION_STREAM_ONLY,
    finalize_telemetry_event,
    parse_telemetry_stream_part,
    telemetry_from_runtime_event,
)
from agents_runtime import events


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
                        "summary": [{"type": "summary_text", "text": "thinking..."}],
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
    assert event.namespace == ("task:research",)
    assert event.retention == TELEMETRY_RETENTION_STREAM_ONLY
    assert event.metadata["langgraph_node"] == "planner"
    assert event.payload["summary"][0]["text"] == "thinking..."


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
                        "summary": [{"type": "summary_text", "text": "thinking..."}],
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


def test_finalize_telemetry_event_compacts_message_metadata_and_payload() -> None:
    """Finalized telemetry should move correlation ids to the envelope."""

    state = TelemetryParserState(run_id="run-telemetry", agent_name="demo-agent")
    part = {
        "type": "messages",
        "ns": ("task:research",),
        "data": (
            AIMessageChunk(
                id="resp_model_1",
                content=[
                    {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "thinking..."}],
                        "id": "rs_1",
                        "extras": {"encrypted_content": "secret"},
                    }
                ],
            ),
            {
                "langgraph_node": "planner",
                "langgraph_step": 2,
                "updated_at": "2026-04-14T00:00:00+00:00",
            },
        ),
    }

    parsed = parse_telemetry_stream_part(part, state)
    finalized = finalize_telemetry_event(parsed.events[0], attempt=1, seq=1)

    assert finalized.node_name == "planner"
    assert finalized.model_call_id == "resp_model_1"
    assert finalized.message_id == "rs_1"
    assert finalized.metadata == {"langgraph_step": 2}
    assert finalized.payload == {"summary": [{"text": "thinking..."}]}


def test_parse_telemetry_stream_part_emits_interrupt_only_for_updates() -> None:
    """Updates parts should only surface interrupts in telemetry mode."""

    state = TelemetryParserState(run_id="run-updates", agent_name="demo-agent")
    interrupt = SimpleNamespace(
        id="interrupt-1",
        value={
            "action_requests": [{"name": "execute", "args": {"command": "pwd"}}],
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
    assert [event.event_type for event in parsed.events] == ["interrupt"]
    assert parsed.events[0].namespace == ("task:worker",)
    assert parsed.events[0].retention == TELEMETRY_RETENTION_STREAM_ONLY


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
    assert parsed.events[0].retention == TELEMETRY_RETENTION_STREAM_ONLY
    assert parsed.events[1].retention == TELEMETRY_RETENTION_DURABLE
    assert parsed.events[1].payload["payload"]["stdout"] == "ok"


def test_finalize_telemetry_event_compacts_tool_payloads() -> None:
    """Finalized tool telemetry should keep only event-specific payload fields."""

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
    done = finalize_telemetry_event(parsed.events[0], attempt=1, seq=1)
    result = finalize_telemetry_event(parsed.events[1], attempt=1, seq=2)

    assert done.tool_call_id == "tool-call-1"
    assert done.node_name == "execute"
    assert done.payload == {}
    assert result.tool_call_id == "tool-call-1"
    assert result.node_name == "execute"
    assert result.payload == {
        "content": "command finished",
        "is_error": False,
        "data": {"stdout": "ok"},
    }


def test_parse_telemetry_stream_part_tracks_checkpoint_bounds_without_emitting() -> (
    None
):
    """Debug checkpoints should update run bounds without producing raw events."""

    state = TelemetryParserState(run_id="run-debug", agent_name="demo-agent")
    part = {
        "type": "debug",
        "ns": (),
        "data": {
            "type": "checkpoint",
            "payload": {
                "config": {"configurable": {"checkpoint_id": "cp-002"}},
                "parent_config": {"configurable": {"checkpoint_id": "cp-001"}},
            },
        },
    }

    parsed = parse_telemetry_stream_part(part, state)

    assert parsed.events == []
    assert state.start_checkpoint_id == "cp-001"
    assert state.end_checkpoint_id == "cp-002"


def test_parse_telemetry_stream_part_deduplicates_debug_tasks_and_compacts_state() -> (
    None
):
    """Repeated debug task starts should collapse to one compact task event."""

    state = TelemetryParserState(run_id="run-debug", agent_name="demo-agent")
    part = {
        "type": "debug",
        "ns": ("task:worker",),
        "data": {
            "type": "task",
            "payload": {
                "id": "task-1",
                "name": "worker",
                "input": {
                    "messages": [{"role": "user", "content": "hello"}],
                    "memory_contents": {".runtime/memory/AGENTS.md": "content"},
                    "skills_metadata": [{"name": "pcap-analyzer"}],
                },
                "triggers": ["messages"],
            },
        },
    }

    first = parse_telemetry_stream_part(part, state)
    second = parse_telemetry_stream_part(part, state)

    assert len(first.events) == 1
    assert second.events == []
    event = first.events[0]
    assert event.event_type == "task"
    assert event.payload["input"]["messages"]["count"] == 1
    assert event.payload["input"]["memory_contents"]["count"] == 1
    assert event.payload["input"]["skills_metadata"]["count"] == 1


def test_telemetry_event_to_proto_preserves_audit_fields() -> None:
    """Telemetry protobuf mapping should preserve namespace and audit metadata."""

    event = telemetry_from_runtime_event(
        events.run_start(
            run_id="run-proto",
            agent_name="demo-agent",
            thread_id="thread-1",
        ),
        namespace=("task:root",),
    )

    proto = telemetry_event_to_proto(finalize_telemetry_event(event, attempt=1, seq=1))

    assert proto.thread_id == "thread-1"
    assert proto.schema_version == 1
    assert proto.retention == pb2.TELEMETRY_RETENTION_DURABLE
    assert list(proto.namespace) == ["task:root"]
    assert proto.stream_mode == "lifecycle"
    assert proto.event_type == "run_started"
    assert proto.event_id == "run-proto:1:1"
    assert proto.attempt == 1
    assert proto.seq == 1
    assert proto.node_name == "run"
