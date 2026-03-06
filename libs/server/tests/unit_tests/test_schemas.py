import pytest

from deepagents_server.schemas import (
    SchemaValidationError,
    ValidationIssue,
    parse_run_request,
    parse_thread_create_request,
    serialize_error,
)


def test_parse_thread_create_request_trims_fields() -> None:
    request = parse_thread_create_request(
        b'{"assistant_id": " assistant-alpha ", "model": " gpt-5 "}'
    )

    assert request.assistant_id == "assistant-alpha"
    assert request.model == "gpt-5"


def test_parse_run_request_accepts_optional_fields() -> None:
    request = parse_run_request(b'{"input": " say hello ", "model": null}')

    assert request.input == "say hello"
    assert request.assistant_id is None
    assert request.model is None


def test_parse_run_request_rejects_duplicate_fields() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        parse_run_request(b'{"input": "hello", "input": "world"}')

    error = exc_info.value
    assert str(error) == "Request body contains duplicate fields."
    assert error.issues == (
        ValidationIssue(field="input", message="Duplicate JSON fields are not allowed."),
    )


def test_parse_thread_create_request_rejects_non_object_json() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        parse_thread_create_request(b"[]")

    error = exc_info.value
    assert error.status_code == 422
    assert error.error == "validation_error"
    assert error.issues == (
        ValidationIssue(field="body", message="Top-level JSON value must be an object."),
    )


def test_parse_run_request_rejects_invalid_json_bytes() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        parse_run_request(b"\xff")

    error = exc_info.value
    assert error.status_code == 400
    assert error.error == "invalid_json"
    assert str(error) == "Request body must be valid UTF-8 JSON."


def test_serialize_error_includes_structured_details() -> None:
    error = SchemaValidationError(
        "Request body contains unknown fields.",
        issues=(ValidationIssue(field="extra", message="Unknown field is not allowed."),),
    )

    assert serialize_error(error) == {
        "error": "validation_error",
        "message": "Request body contains unknown fields.",
        "details": [{"field": "extra", "message": "Unknown field is not allowed."}],
    }
