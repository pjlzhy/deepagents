from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deepagents_runtime.event_stream import (
    MalformedInterruptError,
    RuntimeEventStreamState,
    finalize_runtime_stream_pass,
    process_runtime_stream_chunk,
)


def _make_hitl_request() -> dict[str, object]:
    return {
        "action_requests": [
            {
                "name": "execute",
                "args": {"command": "dir"},
                "description": "Run command",
            }
        ],
        "review_configs": [
            {
                "action_name": "execute",
                "allowed_decisions": ["approve", "reject"],
            }
        ],
    }


def test_process_runtime_stream_chunk_emits_text_delta_and_completion() -> None:
    state = RuntimeEventStreamState(thread_id="thread-1")

    events = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                SimpleNamespace(
                    content_blocks=[{"type": "text", "text": "hello"}],
                    chunk_position="last",
                ),
                {},
            ),
        ),
        state,
    )

    assert [event.type for event in events] == [
        "message.assistant.delta",
        "message.assistant.completed",
    ]
    assert events[0].thread_id == "thread-1"
    assert events[0].payload["text"] == "hello"
    assert events[0].payload["namespace"] == []
    assert state.open_text_namespaces == set()


def test_process_runtime_stream_chunk_flushes_text_before_tool_call() -> None:
    state = RuntimeEventStreamState()

    text_events = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                SimpleNamespace(
                    content_blocks=[{"type": "text", "text": "Need a tool"}],
                ),
                {},
            ),
        ),
        state,
    )
    tool_events = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                SimpleNamespace(
                    content_blocks=[
                        {
                            "type": "tool_call",
                            "name": "execute",
                            "args": {"command": "dir"},
                            "id": "call-1",
                        }
                    ]
                ),
                {},
            ),
        ),
        state,
    )

    assert [event.type for event in text_events] == ["message.assistant.delta"]
    assert [event.type for event in tool_events] == [
        "message.assistant.completed",
        "tool.call.started",
    ]
    assert tool_events[1].payload == {
        "namespace": [],
        "tool_call_id": "call-1",
        "tool_name": "execute",
        "args": {"command": "dir"},
    }
    assert state.open_text_namespaces == set()


def test_process_runtime_stream_chunk_emits_tool_arguments_after_early_start() -> None:
    state = RuntimeEventStreamState()

    started = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                SimpleNamespace(
                    content_blocks=[
                        {
                            "type": "tool_call_chunk",
                            "name": "read_file",
                            "id": "call-1",
                            "index": 0,
                        }
                    ]
                ),
                {},
            ),
        ),
        state,
    )
    arguments = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                SimpleNamespace(
                    content_blocks=[
                        {
                            "type": "tool_call_chunk",
                            "id": "call-1",
                            "index": 0,
                            "args": '{"path":"README.md"}',
                        }
                    ]
                ),
                {},
            ),
        ),
        state,
    )

    assert [event.type for event in started] == ["tool.call.started"]
    assert started[0].payload == {
        "namespace": [],
        "tool_call_id": "call-1",
        "tool_name": "read_file",
        "args": {},
    }
    assert [event.type for event in arguments] == ["tool.call.arguments"]
    assert arguments[0].payload == {
        "namespace": [],
        "tool_call_id": "call-1",
        "tool_name": "read_file",
        "args": {"path": "README.md"},
    }


def test_process_runtime_stream_chunk_emits_interrupt_event_and_updates_state() -> None:
    state = RuntimeEventStreamState()

    events = process_runtime_stream_chunk(
        (
            (),
            "updates",
            {
                "__interrupt__": [
                    SimpleNamespace(id="interrupt-1", value=_make_hitl_request())
                ]
            },
        ),
        state,
    )

    assert [event.type for event in events] == ["run.interrupt"]
    assert events[0].payload["interrupt_id"] == "interrupt-1"
    assert state.interrupt_occurred is True
    assert "interrupt-1" in state.pending_interrupts


def test_process_runtime_stream_chunk_raises_for_malformed_interrupt() -> None:
    state = RuntimeEventStreamState()

    with pytest.raises(MalformedInterruptError) as exc_info:
        process_runtime_stream_chunk(
            (
                (),
                "updates",
                {
                    "__interrupt__": [
                        SimpleNamespace(id="interrupt-1", value={"bad": "payload"})
                    ]
                },
            ),
            state,
        )

    assert exc_info.value.interrupt_id == "interrupt-1"
    assert exc_info.value.raw_value == {"bad": "payload"}


def test_process_runtime_stream_chunk_emits_usage_and_tool_completion() -> None:
    state = RuntimeEventStreamState(model_name="gpt-test")

    usage_events = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                SimpleNamespace(
                    usage_metadata={
                        "input_tokens": 12,
                        "output_tokens": 5,
                        "total_tokens": 17,
                    },
                    content_blocks=[],
                ),
                {},
            ),
        ),
        state,
    )
    tool_events = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                ToolMessage(
                    content="done",
                    tool_call_id="call-1",
                    name="execute",
                    status="success",
                ),
                {},
            ),
        ),
        state,
    )

    assert [event.type for event in usage_events] == ["run.usage"]
    assert usage_events[0].payload["model_name"] == "gpt-test"
    assert usage_events[0].payload["session_input_tokens"] == 12
    assert usage_events[0].payload["session_output_tokens"] == 5
    assert state.stats.request_count == 1
    assert [event.type for event in tool_events] == ["tool.call.completed"]
    assert tool_events[0].payload["tool_call_id"] == "call-1"
    assert tool_events[0].payload["content"] == "done"


def test_finalize_runtime_stream_pass_emits_pending_completion_events() -> None:
    state = RuntimeEventStreamState()

    started = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (AIMessage(content="summary chunk"), {"lc_source": "summarization"}),
        ),
        state,
    )
    text_events = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                SimpleNamespace(content_blocks=[{"type": "text", "text": "hello"}]),
                {},
            ),
        ),
        state,
    )
    finalized = finalize_runtime_stream_pass(state)

    assert [event.type for event in started] == ["run.summarization.started"]
    assert [event.type for event in text_events] == [
        "run.summarization.completed",
        "message.assistant.delta",
    ]
    assert [event.type for event in finalized] == ["message.assistant.completed"]
    assert state.summarization_in_progress is False
    assert state.open_text_namespaces == set()


def test_human_message_ends_open_assistant_message() -> None:
    state = RuntimeEventStreamState()

    process_runtime_stream_chunk(
        (
            (),
            "messages",
            (
                SimpleNamespace(content_blocks=[{"type": "text", "text": "hello"}]),
                {},
            ),
        ),
        state,
    )
    events = process_runtime_stream_chunk(
        (
            (),
            "messages",
            (HumanMessage(content="ack"), {}),
        ),
        state,
    )

    assert [event.type for event in events] == ["message.assistant.completed"]
    assert state.open_text_namespaces == set()
