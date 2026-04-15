"""Unit tests for LangGraph stream part wrappers."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.types import Interrupt

from agents_runtime.langgraph_stream import (
    DebugPartView,
    MessagesPartView,
    UnknownPartView,
    UpdatesPartView,
    ValuesPartView,
    wrap_stream_part,
)


def test_wrap_stream_part_messages_exposes_message_and_metadata_views() -> None:
    """Messages parts should preserve structure and derived block classification."""

    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            AIMessageChunk(
                id="resp_1",
                content=[
                    {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "thinking"}],
                        "id": "rs_1",
                    },
                    {
                        "type": "text",
                        "text": "hello",
                        "id": "msg_1",
                    },
                ],
            ),
            {
                "langgraph_node": "planner",
                "langgraph_step": 2,
                "ls_provider": "openai",
                "ls_model_name": "gpt-5.4",
            },
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.header.mode == "messages"
    assert view.header.ns.classification.tail == "task:model"
    assert view.structure.message is not None
    assert view.structure.message.structure.id == "resp_1"
    assert view.structure.metadata is not None
    assert view.structure.metadata.structure.langgraph_node == "planner"
    assert view.classification.message_kind == "ai"
    assert view.classification.message_form == "chunk"
    assert view.classification.block_kinds == ("reasoning", "text")
    assert view.classification.has_reasoning_blocks is True
    assert view.classification.has_text_blocks is True
    assert view.is_well_formed is True


def test_wrap_stream_part_messages_keeps_content_block_structure_details() -> None:
    """Messages wrappers should preserve per-block structure, order, and raw payload."""

    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            AIMessageChunk(
                id="resp_1",
                content=[
                    {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "thinking"}],
                        "id": "rs_1",
                    },
                    {
                        "type": "text",
                        "text": "hello",
                        "id": "msg_1",
                    },
                ],
            ),
            {"langgraph_node": "planner"},
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.raw == part
    assert view.structure.message is not None
    blocks = view.structure.message.structure.content_blocks
    assert len(blocks) == 2
    assert blocks[0].classification.kind == "reasoning"
    assert blocks[0].structure.id == "rs_1"
    assert blocks[0].structure.summary == (
        {"type": "summary_text", "text": "thinking"},
    )
    assert blocks[1].classification.kind == "text"
    assert blocks[1].structure.id == "msg_1"
    assert blocks[1].structure.text == "hello"
    assert view.structure.message.issues == ()
    assert blocks[0].issues == ()
    assert blocks[1].issues == ()


def test_wrap_stream_part_messages_supports_serialized_message_dicts() -> None:
    """Messages wrappers should support serialized message dictionaries."""

    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            {
                "id": "resp_2",
                "role": "assistant_chunk",
                "content": [
                    {"type": "reasoning", "summary": [{"text": "plan"}], "id": "rs_2"},
                    {"type": "text", "text": "hi", "id": "msg_2"},
                ],
                "usage_metadata": {"input_tokens": 10, "output_tokens": 4},
                "additional_kwargs": {"foo": "bar"},
            },
            {"langgraph_node": "model"},
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.structure.message is not None
    message = view.structure.message
    assert message.structure.id == "resp_2"
    assert message.classification.kind == "unknown"
    assert message.classification.form == "chunk"
    assert message.classification.has_content_blocks is True
    assert message.classification.has_usage_metadata is True
    assert message.structure.additional_kwargs == {"foo": "bar"}
    assert [block.classification.kind for block in message.structure.content_blocks] == [
        "reasoning",
        "text",
    ]


def test_wrap_stream_part_messages_metadata_exposes_full_structure_and_classification() -> None:
    """Message metadata wrappers should preserve full metadata structure."""

    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            AIMessageChunk(id="resp_1", content=[]),
            {
                "langgraph_node": "planner",
                "langgraph_step": 2,
                "langgraph_triggers": ["messages", 1],
                "langgraph_path": ("root", "model"),
                "ls_provider": "openai",
                "ls_model_name": "gpt-5.4",
                "custom_field": "kept",
            },
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.structure.metadata is not None
    metadata = view.structure.metadata
    assert metadata.structure.langgraph_node == "planner"
    assert metadata.structure.langgraph_step == 2
    assert metadata.structure.langgraph_triggers == ("messages", "1")
    assert metadata.structure.langgraph_path == ("root", "model")
    assert metadata.structure.ls_provider == "openai"
    assert metadata.structure.ls_model_name == "gpt-5.4"
    assert metadata.structure.extras == {"custom_field": "kept"}
    assert metadata.classification.has_node is True
    assert metadata.classification.has_step is True
    assert metadata.classification.has_triggers is True
    assert metadata.classification.has_model_identity is True
    assert len(metadata.issues) == 1
    assert metadata.issues[0].path == "data[1].langgraph_triggers[1]"


def test_wrap_stream_part_messages_exposes_tool_calls_and_invalid_tool_calls() -> None:
    """Messages wrappers should preserve tool call collections."""

    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            {
                "id": "resp_3",
                "type": "ai",
                "content": [],
                "tool_calls": [
                    {"id": "call_1", "name": "execute", "args": {"command": "pwd"}}
                ],
                "invalid_tool_calls": [
                    {
                        "id": "bad_call_1",
                        "name": "execute",
                        "args": "{bad json}",
                        "error": "invalid json",
                    }
                ],
            },
            {"langgraph_node": "tools"},
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.structure.message is not None
    message = view.structure.message
    assert message.classification.kind == "ai"
    assert message.classification.has_tool_calls is True
    assert len(message.structure.tool_calls) == 1
    assert message.structure.tool_calls[0].structure.id == "call_1"
    assert message.structure.tool_calls[0].structure.name == "execute"
    assert message.structure.tool_calls[0].classification.args_type == "dict"
    assert len(message.structure.invalid_tool_calls) == 1
    assert message.structure.invalid_tool_calls[0].structure.id == "bad_call_1"
    assert message.structure.invalid_tool_calls[0].structure.error == "invalid json"


def test_wrap_stream_part_messages_reports_malformed_metadata_and_content_blocks() -> None:
    """Known messages parts should keep their wrapper and record malformed subviews."""

    part = {
        "type": "messages",
        "ns": (),
        "data": (
            {
                "id": "resp_4",
                "type": "ai",
                "content": ["plain text is not a block mapping"],
            },
            "metadata should be a dict",
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.is_well_formed is True
    assert view.structure.message is not None
    assert view.structure.metadata is not None
    assert len(view.structure.message.structure.content_blocks) == 0
    assert len(view.structure.metadata.issues) == 1
    assert view.structure.metadata.issues[0].path == "data[1]"


def test_wrap_stream_part_messages_classifies_nonstandard_blocks() -> None:
    """Unknown block types should be preserved as `nonstandard` instead of dropped."""

    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            {
                "id": "resp_5",
                "type": "ai",
                "content": [
                    {
                        "type": "custom_block",
                        "id": "custom_1",
                        "foo": "bar",
                    }
                ],
            },
            {"langgraph_node": "model"},
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.structure.message is not None
    blocks = view.structure.message.structure.content_blocks
    assert len(blocks) == 1
    assert blocks[0].classification.kind == "nonstandard"
    assert blocks[0].structure.extras == {"foo": "bar"}
    assert view.classification.block_kinds == ("nonstandard",)


def test_wrap_stream_part_messages_prefers_explicit_content_blocks_field() -> None:
    """`content_blocks` should win over `content` when both are present."""

    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            {
                "id": "resp_6",
                "type": "ai",
                "content": [
                    {"type": "text", "text": "from content", "id": "msg_content"}
                ],
                "content_blocks": [
                    {"type": "reasoning", "id": "rs_content_blocks", "summary": []}
                ],
            },
            {"langgraph_node": "model"},
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.structure.message is not None
    blocks = view.structure.message.structure.content_blocks
    assert len(blocks) == 1
    assert blocks[0].classification.kind == "reasoning"
    assert blocks[0].structure.id == "rs_content_blocks"


def test_wrap_stream_part_messages_classifies_tool_messages() -> None:
    """Tool messages should be classified as tool/complete messages."""

    part = {
        "type": "messages",
        "ns": ("task:tools",),
        "data": (
            ToolMessage(
                content="command finished",
                tool_call_id="call_1",
                name="execute",
            ),
            {"langgraph_node": "tools"},
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.structure.message is not None
    assert view.classification.message_kind == "tool"
    assert view.classification.message_form == "complete"
    assert view.structure.message.structure.name == "execute"
    assert view.structure.message.structure.content == "command finished"


def test_wrap_stream_part_messages_reports_malformed_tool_calls_and_block_items() -> None:
    """Malformed nested tool-call and block payloads should surface child issues."""

    part = {
        "type": "messages",
        "ns": ("task:model",),
        "data": (
            {
                "id": "resp_7",
                "type": "ai",
                "content_blocks": ["bad block item"],
                "tool_calls": ["bad tool call"],
                "invalid_tool_calls": [123],
            },
            {"langgraph_node": "model"},
        ),
    }

    view = wrap_stream_part(part)

    assert isinstance(view, MessagesPartView)
    assert view.structure.message is not None
    message = view.structure.message
    assert message.is_well_formed is True
    assert len(message.structure.content_blocks) == 1
    assert len(message.structure.tool_calls) == 1
    assert len(message.structure.invalid_tool_calls) == 1
    assert message.structure.content_blocks[0].is_well_formed is False
    assert message.structure.tool_calls[0].is_well_formed is False
    assert message.structure.invalid_tool_calls[0].is_well_formed is False
    assert message.structure.content_blocks[0].issues[0].path == "content_block"
    assert message.structure.tool_calls[0].issues[0].path == "tool_calls[]"
    assert message.structure.invalid_tool_calls[0].issues[0].path == "invalid_tool_calls[]"


def test_wrap_stream_part_updates_keeps_writes_interrupts_and_reserved_keys() -> None:
    """Updates parts should expose the full entry set instead of interrupt-only data."""

    interrupt = SimpleNamespace(id="interrupt-1", value={"approve": True})
    part = {
        "type": "updates",
        "ns": ("task:worker",),
        "data": {
            "planner": {"todos": [{"content": "inspect repo"}]},
            "__interrupt__": [interrupt],
            "__metadata__": {"langgraph_node": "planner"},
            "__checkpoint__": {"id": "cp-1"},
        },
    }

    view = wrap_stream_part(part)

    assert isinstance(view, UpdatesPartView)
    assert view.classification.has_writes is True
    assert view.classification.has_interrupts is True
    assert view.classification.write_keys == ("planner",)
    assert view.classification.reserved_keys == ("__checkpoint__",)
    assert view.classification.metadata_entry is not None
    assert len(view.classification.interrupts) == 1
    assert view.classification.interrupts[0].structure.id == "interrupt-1"
    assert len(view.structure.entries) == 4
    assert view.is_well_formed is True


def test_wrap_stream_part_debug_task_result_reuses_task_result_wrapper() -> None:
    """Debug task results should preserve their envelope and nested task payload."""

    part = {
        "type": "debug",
        "ns": ("task:model",),
        "data": {
            "step": 4,
            "timestamp": "2026-04-09T10:51:49.183742046Z",
            "type": "task_result",
            "payload": {
                "id": "task-1",
                "name": "model",
                "interrupts": [{"id": "interrupt-1", "value": {"approve": True}}],
                "result": {"messages": {"count": 1}},
                "error": None,
            },
        },
    }

    view = wrap_stream_part(part)

    assert isinstance(view, DebugPartView)
    assert view.classification.variant == "task_result"
    assert view.structure.step == 4
    assert view.structure.event is not None
    payload = view.structure.event.structure.payload
    assert payload is not None
    assert payload.structure.id == "task-1"
    assert payload.classification.has_result is True
    assert payload.classification.has_interrupts is True


def test_wrap_stream_part_values_reads_outer_interrupts() -> None:
    """Values parts should read interrupts from the outer part envelope."""

    part = {
        "type": "values",
        "ns": (),
        "data": {"messages": []},
        "interrupts": [Interrupt(value={"approve": True}, id="interrupt-1")],
    }

    view = wrap_stream_part(part)

    assert isinstance(view, ValuesPartView)
    assert view.classification.has_interrupts is True
    assert len(view.structure.interrupts) == 1
    assert view.structure.interrupts[0].structure.id == "interrupt-1"
    assert view.structure.value == {"messages": []}


def test_wrap_stream_part_returns_unknown_for_non_mapping_input() -> None:
    """Unsupported outer payloads should degrade to `UnknownPartView`."""

    view = wrap_stream_part(["not", "a", "mapping"])

    assert isinstance(view, UnknownPartView)
    assert view.classification.reason == "not_mapping"
    assert view.is_well_formed is False


def test_wrap_stream_part_keeps_known_type_for_malformed_messages_payload() -> None:
    """Known stream modes should stay on their wrapper even when payload shape is bad."""

    view = wrap_stream_part({"type": "messages", "ns": (), "data": {"bad": "shape"}})

    assert isinstance(view, MessagesPartView)
    assert view.is_well_formed is False
    assert view.structure.message is None
    assert view.structure.metadata is None
