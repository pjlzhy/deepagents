import pytest
from pydantic import ValidationError

from deepagents_runtime.streams import (
    MessageChunkPayload,
    ParsedStreamChunk,
    is_main_agent_namespace,
    parse_message_chunk,
    parse_stream_chunk,
    validate_hitl_request,
)


def test_parse_stream_chunk_returns_none_for_invalid_shape() -> None:
    assert parse_stream_chunk(("messages", {})) is None


def test_parse_stream_chunk_normalizes_empty_namespace() -> None:
    parsed = parse_stream_chunk(((), "messages", {"x": 1}))

    assert parsed == ParsedStreamChunk((), "messages", {"x": 1})


def test_parse_stream_chunk_normalizes_iterable_namespace() -> None:
    parsed = parse_stream_chunk((["sub", "agent"], "updates", {}))

    assert parsed == ParsedStreamChunk(("sub", "agent"), "updates", {})


def test_is_main_agent_namespace_true_for_empty_namespace() -> None:
    assert is_main_agent_namespace(()) is True


def test_is_main_agent_namespace_false_for_nested_namespace() -> None:
    assert is_main_agent_namespace(("subagent",)) is False


def test_parse_message_chunk_returns_none_for_invalid_shape() -> None:
    assert parse_message_chunk(("message-only",)) is None


def test_parse_message_chunk_returns_none_for_non_dict_metadata() -> None:
    assert parse_message_chunk(("msg", "bad-metadata")) is None


def test_parse_message_chunk_parses_valid_payload() -> None:
    payload = parse_message_chunk(("msg", {"lc_source": "summarization"}))

    assert payload == MessageChunkPayload(
        message="msg",
        metadata={"lc_source": "summarization"},
    )


def test_validate_hitl_request_validates_payload() -> None:
    payload = {
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

    request = validate_hitl_request(payload)

    assert request["action_requests"][0]["name"] == "execute"


def test_validate_hitl_request_raises_for_invalid_payload() -> None:
    with pytest.raises(ValidationError):
        validate_hitl_request({"bad": "payload"})
