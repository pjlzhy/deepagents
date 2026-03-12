"""Shared stream and HITL parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.human_in_the_loop import HITLRequest
from pydantic import TypeAdapter

if TYPE_CHECKING:
    from langgraph.types import Interrupt

_HITL_REQUEST_ADAPTER = TypeAdapter(HITLRequest)
_STREAM_CHUNK_LENGTH = 3
_MESSAGE_CHUNK_LENGTH = 2


@dataclass(frozen=True, slots=True)
class ParsedStreamChunk:
    """A normalized stream chunk emitted by LangGraph.

    Attributes:
        namespace: Hashable namespace key for the chunk.
        stream_mode: The LangGraph stream mode, such as `messages` or `updates`.
        data: Raw payload emitted for the stream mode.
    """

    namespace: tuple[Any, ...]
    stream_mode: str
    data: object


@dataclass(frozen=True, slots=True)
class MessageChunkPayload:
    """Normalized payload for a `messages` stream chunk."""

    message: object
    metadata: dict[str, Any] | None


def parse_stream_chunk(chunk: object) -> ParsedStreamChunk | None:
    """Parse a raw LangGraph stream chunk into a normalized structure.

    Args:
        chunk: Raw chunk emitted by `agent.astream`.

    Returns:
        Parsed chunk when the payload has the expected shape, otherwise `None`.
    """
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
        return None

    namespace, stream_mode, data = chunk
    if isinstance(namespace, tuple):
        normalized_namespace = namespace
    elif not namespace:
        normalized_namespace = ()
    else:
        try:
            normalized_namespace = tuple(namespace)
        except TypeError:
            return None

    return ParsedStreamChunk(
        namespace=normalized_namespace,
        stream_mode=str(stream_mode),
        data=data,
    )


def is_main_agent_namespace(namespace: tuple[Any, ...]) -> bool:
    """Return whether a normalized namespace belongs to the main agent."""
    return namespace == ()


def parse_message_chunk(data: object) -> MessageChunkPayload | None:
    """Parse the payload for a `messages` stream chunk.

    Args:
        data: Raw data field from a stream chunk.

    Returns:
        A normalized message payload when the input shape matches expectations,
        otherwise `None`.
    """
    if not isinstance(data, tuple) or len(data) != _MESSAGE_CHUNK_LENGTH:
        return None

    message, metadata = data
    if metadata is not None and not isinstance(metadata, dict):
        return None
    return MessageChunkPayload(message=message, metadata=metadata)


def validate_hitl_request(value: object) -> HITLRequest:
    """Validate a raw HITL interrupt payload.

    Args:
        value: Raw interrupt payload emitted by LangGraph.

    Returns:
        Validated `HITLRequest`.
    """
    return _HITL_REQUEST_ADAPTER.validate_python(value)


def iter_interrupt_ids(interrupts: list[Interrupt]) -> list[str]:
    """Return interrupt IDs in emission order.

    Args:
        interrupts: Raw interrupt objects emitted by LangGraph.

    Returns:
        Interrupt IDs in the same order they were received.
    """
    return [interrupt.id for interrupt in interrupts]
