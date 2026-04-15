"""Wrappers for `messages` LangGraph stream parts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._base import (
    PartView,
    View,
    as_object_tuple,
    as_string_mapping,
    extras_from_mapping,
    field_value,
    has_field,
    issue,
    mapping_field,
    object_sequence_field,
    string_field,
)

MessageKind = Literal["ai", "tool", "human", "system", "unknown"]
MessageForm = Literal["chunk", "complete", "unknown"]
BlockKind = Literal[
    "text",
    "reasoning",
    "tool_call",
    "tool_call_chunk",
    "server_tool_call",
    "server_tool_result",
    "nonstandard",
    "unknown",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCallStructure:
    id: str | None
    name: str | None
    args: object
    extras: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCallClassification:
    has_id: bool
    has_name: bool
    args_type: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCallView(View[ToolCallStructure, ToolCallClassification]):
    """Structured view over one message tool call payload."""


@dataclass(frozen=True, slots=True, kw_only=True)
class InvalidToolCallStructure:
    id: str | None
    name: str | None
    args: object
    error: str | None
    extras: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class InvalidToolCallClassification:
    has_id: bool
    has_name: bool
    has_error: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class InvalidToolCallView(View[InvalidToolCallStructure, InvalidToolCallClassification]):
    """Structured view over one invalid tool call payload."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentBlockStructure:
    type_name: str | None
    index: int | None
    id: str | None
    text: str | None
    args: object
    call_id: str | None
    summary: tuple[object, ...]
    encrypted_content: str | None
    extras: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentBlockClassification:
    kind: BlockKind
    is_text: bool
    is_reasoning: bool
    is_tool_call: bool
    is_tool_result: bool
    is_chunk: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentBlockView(View[ContentBlockStructure, ContentBlockClassification]):
    """Structured view over one message content block."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageMetadataStructure:
    langgraph_node: str | None
    langgraph_step: int | None
    langgraph_triggers: tuple[str, ...]
    langgraph_path: tuple[object, ...]
    ls_provider: str | None
    ls_model_name: str | None
    extras: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageMetadataClassification:
    has_node: bool
    has_step: bool
    has_triggers: bool
    has_model_identity: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageMetadataView(View[MessageMetadataStructure, MessageMetadataClassification]):
    """Structured view over LangGraph message metadata."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageObjectStructure:
    id: str | None
    type_name: str | None
    role: str | None
    name: str | None
    tool_call_id: str | None
    status: str | None
    content: object
    content_blocks: tuple[ContentBlockView, ...]
    tool_calls: tuple[ToolCallView, ...]
    invalid_tool_calls: tuple[InvalidToolCallView, ...]
    artifact: object
    has_artifact: bool
    usage_metadata: dict[str, object] | None
    response_metadata: dict[str, object] | None
    additional_kwargs: dict[str, object] | None
    extras: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageObjectClassification:
    kind: MessageKind
    form: MessageForm
    has_content_blocks: bool
    has_tool_calls: bool
    has_artifact: bool
    has_usage_metadata: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageObjectView(View[MessageObjectStructure, MessageObjectClassification]):
    """Structured view over one message object or message dict."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MessagesPartStructure:
    message: MessageObjectView | None
    metadata: MessageMetadataView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MessagesPartClassification:
    message_kind: MessageKind
    message_form: MessageForm
    block_kinds: tuple[BlockKind, ...]
    has_text_blocks: bool
    has_reasoning_blocks: bool
    has_tool_call_blocks: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class MessagesPartView(PartView[MessagesPartStructure, MessagesPartClassification]):
    """Structured view over one `messages` stream part."""


def wrap_messages_part(
    *,
    raw_part: object,
    header: object,
    data: object,
) -> MessagesPartView:
    """Wrap one `messages` stream payload."""

    issues = []
    data_items = as_object_tuple(data)
    message_view: MessageObjectView | None = None
    metadata_view: MessageMetadataView | None = None

    if data_items is None or len(data_items) != 2:
        issues.append(
            issue(
                "data",
                "tuple[message, metadata]",
                data,
                "Expected `messages.data` to be a 2-item tuple of `(message, metadata)`.",
            )
        )
    else:
        message_view = wrap_message_object(data_items[0])
        metadata_view = wrap_message_metadata(data_items[1])

    block_kinds = ()
    has_text_blocks = False
    has_reasoning_blocks = False
    has_tool_call_blocks = False
    if message_view is not None:
        block_kinds = tuple(
            block.classification.kind for block in message_view.structure.content_blocks
        )
        has_text_blocks = any(
            block.classification.is_text
            for block in message_view.structure.content_blocks
        )
        has_reasoning_blocks = any(
            block.classification.is_reasoning
            for block in message_view.structure.content_blocks
        )
        has_tool_call_blocks = any(
            block.classification.is_tool_call
            for block in message_view.structure.content_blocks
        )

    return MessagesPartView(
        raw=raw_part,
        header=header,
        structure=MessagesPartStructure(
            message=message_view,
            metadata=metadata_view,
        ),
        classification=MessagesPartClassification(
            message_kind=(
                message_view.classification.kind if message_view is not None else "unknown"
            ),
            message_form=(
                message_view.classification.form if message_view is not None else "unknown"
            ),
            block_kinds=block_kinds,
            has_text_blocks=has_text_blocks,
            has_reasoning_blocks=has_reasoning_blocks,
            has_tool_call_blocks=has_tool_call_blocks,
        ),
        issues=tuple(issues),
    )


def wrap_message_object(raw: object) -> MessageObjectView:
    """Wrap one message object or message dictionary."""

    issues = []
    raw_mapping = as_string_mapping(raw)
    content = field_value(raw, "content")
    content_blocks_value = object_sequence_field(raw, "content_blocks")
    if content_blocks_value is None:
        content_sequence = as_object_tuple(content)
        if content_sequence and all(as_string_mapping(item) is not None for item in content_sequence):
            content_blocks_value = content_sequence

    content_blocks = tuple(
        wrap_content_block(item) for item in (content_blocks_value or ())
    )
    tool_calls = tuple(
        wrap_tool_call(item) for item in (object_sequence_field(raw, "tool_calls") or ())
    )
    invalid_tool_calls = tuple(
        wrap_invalid_tool_call(item)
        for item in (object_sequence_field(raw, "invalid_tool_calls") or ())
    )

    type_name = string_field(raw, "type")
    role = string_field(raw, "role")
    name = string_field(raw, "name")
    identifier = string_field(raw, "id")
    usage_metadata = mapping_field(raw, "usage_metadata")
    response_metadata = mapping_field(raw, "response_metadata")
    additional_kwargs = mapping_field(raw, "additional_kwargs")
    has_artifact = has_field(raw, "artifact")

    if raw_mapping is None and not hasattr(raw, "__dict__"):
        issues.append(
            issue(
                "data[0]",
                "message object or mapping",
                raw,
                "Message payload is neither a mapping nor an object with accessible attributes.",
            )
        )

    kind = classify_message_kind(raw=raw, type_name=type_name, role=role)
    form = classify_message_form(raw=raw, type_name=type_name, role=role)

    return MessageObjectView(
        raw=raw,
        structure=MessageObjectStructure(
            id=identifier,
            type_name=type_name,
            role=role,
            name=name,
            tool_call_id=string_field(raw, "tool_call_id"),
            status=string_field(raw, "status"),
            content=content,
            content_blocks=content_blocks,
            tool_calls=tool_calls,
            invalid_tool_calls=invalid_tool_calls,
            artifact=field_value(raw, "artifact"),
            has_artifact=has_artifact,
            usage_metadata=usage_metadata,
            response_metadata=response_metadata,
            additional_kwargs=additional_kwargs,
            extras=extras_from_mapping(
                raw_mapping,
                used_keys={
                    "id",
                    "type",
                    "role",
                    "name",
                    "tool_call_id",
                    "status",
                    "content",
                    "content_blocks",
                    "tool_calls",
                    "invalid_tool_calls",
                    "artifact",
                    "usage_metadata",
                    "response_metadata",
                    "additional_kwargs",
                },
            ),
        ),
        classification=MessageObjectClassification(
            kind=kind,
            form=form,
            has_content_blocks=bool(content_blocks),
            has_tool_calls=bool(tool_calls or invalid_tool_calls),
            has_artifact=has_artifact,
            has_usage_metadata=usage_metadata is not None,
        ),
        issues=tuple(issues),
    )


def wrap_message_metadata(raw: object) -> MessageMetadataView:
    """Wrap one messages metadata mapping."""

    issues = []
    mapping = as_string_mapping(raw)
    triggers_value = field_value(raw, "langgraph_triggers")
    path_value = field_value(raw, "langgraph_path")

    if mapping is None:
        issues.append(
            issue(
                "data[1]",
                "mapping",
                raw,
                "Message metadata should be a mapping.",
            )
        )

    trigger_items = as_object_tuple(triggers_value) or ()
    path_items = as_object_tuple(path_value) or ()
    trigger_strings: list[str] = []
    for index, item in enumerate(trigger_items):
        if isinstance(item, str):
            trigger_strings.append(item)
            continue
        issues.append(
            issue(
                f"data[1].langgraph_triggers[{index}]",
                "str",
                item,
                "Trigger value was coerced to string.",
            )
        )
        trigger_strings.append(str(item))

    return MessageMetadataView(
        raw=raw,
        structure=MessageMetadataStructure(
            langgraph_node=string_field(raw, "langgraph_node"),
            langgraph_step=field_value(raw, "langgraph_step")
            if isinstance(field_value(raw, "langgraph_step"), int)
            and not isinstance(field_value(raw, "langgraph_step"), bool)
            else None,
            langgraph_triggers=tuple(trigger_strings),
            langgraph_path=tuple(path_items),
            ls_provider=string_field(raw, "ls_provider"),
            ls_model_name=string_field(raw, "ls_model_name"),
            extras=extras_from_mapping(
                mapping,
                used_keys={
                    "langgraph_node",
                    "langgraph_step",
                    "langgraph_triggers",
                    "langgraph_path",
                    "ls_provider",
                    "ls_model_name",
                },
            ),
        ),
        classification=MessageMetadataClassification(
            has_node=string_field(raw, "langgraph_node") is not None,
            has_step=isinstance(field_value(raw, "langgraph_step"), int)
            and not isinstance(field_value(raw, "langgraph_step"), bool),
            has_triggers=bool(trigger_strings),
            has_model_identity=bool(
                string_field(raw, "ls_provider") or string_field(raw, "ls_model_name")
            ),
        ),
        issues=tuple(issues),
    )


def wrap_content_block(raw: object) -> ContentBlockView:
    """Wrap one content block dictionary."""

    issues = []
    mapping = as_string_mapping(raw)
    if mapping is None:
        issues.append(
            issue(
                "content_block",
                "mapping",
                raw,
                "Content block should be a mapping.",
            )
        )
    type_name = string_field(raw, "type")
    block_kind = classify_block_kind(type_name)
    index_value = field_value(raw, "index")
    summary_items = as_object_tuple(field_value(raw, "summary")) or ()

    return ContentBlockView(
        raw=raw,
        structure=ContentBlockStructure(
            type_name=type_name,
            index=index_value if isinstance(index_value, int) and not isinstance(index_value, bool) else None,
            id=string_field(raw, "id"),
            text=string_field(raw, "text"),
            args=field_value(raw, "args"),
            call_id=string_field(raw, "call_id"),
            summary=tuple(summary_items),
            encrypted_content=string_field(raw, "encrypted_content"),
            extras=extras_from_mapping(
                mapping,
                used_keys={
                    "type",
                    "index",
                    "id",
                    "text",
                    "args",
                    "call_id",
                    "summary",
                    "encrypted_content",
                },
            ),
        ),
        classification=ContentBlockClassification(
            kind=block_kind,
            is_text=block_kind == "text",
            is_reasoning=block_kind == "reasoning",
            is_tool_call=block_kind in {"tool_call", "tool_call_chunk", "server_tool_call"},
            is_tool_result=block_kind == "server_tool_result",
            is_chunk=block_kind == "tool_call_chunk",
        ),
        issues=tuple(issues),
    )


def wrap_tool_call(raw: object) -> ToolCallView:
    """Wrap one valid tool call payload."""

    issues = []
    mapping = as_string_mapping(raw)
    if mapping is None:
        issues.append(
            issue(
                "tool_calls[]",
                "mapping",
                raw,
                "Tool call should be a mapping.",
            )
        )

    return ToolCallView(
        raw=raw,
        structure=ToolCallStructure(
            id=string_field(raw, "id"),
            name=string_field(raw, "name"),
            args=field_value(raw, "args"),
            extras=extras_from_mapping(mapping, used_keys={"id", "name", "args"}),
        ),
        classification=ToolCallClassification(
            has_id=string_field(raw, "id") is not None,
            has_name=string_field(raw, "name") is not None,
            args_type=type(field_value(raw, "args")).__name__,
        ),
        issues=tuple(issues),
    )


def wrap_invalid_tool_call(raw: object) -> InvalidToolCallView:
    """Wrap one invalid tool call payload."""

    issues = []
    mapping = as_string_mapping(raw)
    if mapping is None:
        issues.append(
            issue(
                "invalid_tool_calls[]",
                "mapping",
                raw,
                "Invalid tool call should be a mapping.",
            )
        )

    return InvalidToolCallView(
        raw=raw,
        structure=InvalidToolCallStructure(
            id=string_field(raw, "id"),
            name=string_field(raw, "name"),
            args=field_value(raw, "args"),
            error=string_field(raw, "error"),
            extras=extras_from_mapping(
                mapping,
                used_keys={"id", "name", "args", "error"},
            ),
        ),
        classification=InvalidToolCallClassification(
            has_id=string_field(raw, "id") is not None,
            has_name=string_field(raw, "name") is not None,
            has_error=string_field(raw, "error") is not None,
        ),
        issues=tuple(issues),
    )


def classify_message_kind(*, raw: object, type_name: str | None, role: str | None) -> MessageKind:
    """Classify a message into a stable high-level kind."""

    token = " ".join(
        item
        for item in (
            type_name,
            role,
            type(raw).__name__,
        )
        if item
    ).lower()
    if "tool" in token:
        return "tool"
    if "human" in token:
        return "human"
    if "system" in token:
        return "system"
    if "ai" in token:
        return "ai"
    return "unknown"


def classify_message_form(*, raw: object, type_name: str | None, role: str | None) -> MessageForm:
    """Classify whether a message is chunked or complete."""

    token = " ".join(
        item
        for item in (
            type_name,
            role,
            type(raw).__name__,
        )
        if item
    ).lower()
    if "chunk" in token:
        return "chunk"
    if token:
        return "complete"
    return "unknown"


def classify_block_kind(type_name: str | None) -> BlockKind:
    """Classify one content block kind from its raw block type."""

    if type_name is None:
        return "unknown"
    if type_name in {
        "text",
        "reasoning",
        "tool_call",
        "tool_call_chunk",
        "server_tool_call",
        "server_tool_result",
    }:
        return type_name
    return "nonstandard"
