"""Request validation helpers for the Deep Agents HTTP server."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class _JsonPairs(list[tuple[str, object]]):
    """Marker type used to distinguish JSON objects from arrays."""


@dataclass(frozen=True)
class ValidationIssue:
    """Structured issue returned for invalid request bodies.

    Args:
        field: Field name associated with the validation error.
        message: Human-readable validation detail.
    """

    field: str
    message: str


class SchemaValidationError(ValueError):
    """Raised when a request body cannot be validated."""

    def __init__(
        self,
        message: str,
        *,
        issues: tuple[ValidationIssue, ...] = (),
        status_code: int = 422,
        error: str = "validation_error",
    ) -> None:
        """Create the validation error.

        Args:
            message: Human-readable validation summary.
            issues: Structured validation issues associated with the error.
            status_code: HTTP status code to return for the error.
            error: Stable error code exposed by the API.
        """
        super().__init__(message)
        self.issues = issues
        self.status_code = status_code
        self.error = error


@dataclass(frozen=True)
class ThreadCreateRequest:
    """Validated payload for `POST /v1/threads`.

    Args:
        assistant_id: Stable assistant identifier stored on the thread.
        model: Optional default model for subsequent runs.
    """

    assistant_id: str
    model: str | None


@dataclass(frozen=True)
class RunRequest:
    """Validated payload for run creation routes.

    Args:
        input: User input sent to the runtime.
        assistant_id: Optional assistant override for the run.
        model: Optional model override for the run.
    """

    input: str
    assistant_id: str | None
    model: str | None


def parse_thread_create_request(body: bytes) -> ThreadCreateRequest:
    """Parse and validate a thread creation request.

    Args:
        body: Raw request body bytes.

    Returns:
        Validated thread creation request.

    Raises:
        SchemaValidationError: If the payload is invalid.
    """
    payload = _parse_json_object(body)
    _reject_unknown_fields(payload, {"assistant_id", "model"})
    return ThreadCreateRequest(
        assistant_id=_require_string(payload, "assistant_id"),
        model=_optional_string(payload, "model"),
    )


def parse_run_request(body: bytes) -> RunRequest:
    """Parse and validate a run request.

    Args:
        body: Raw request body bytes.

    Returns:
        Validated run request payload.

    Raises:
        SchemaValidationError: If the payload is invalid.
    """
    payload = _parse_json_object(body)
    _reject_unknown_fields(payload, {"assistant_id", "input", "model"})
    return RunRequest(
        input=_require_string(payload, "input"),
        assistant_id=_optional_string(payload, "assistant_id"),
        model=_optional_string(payload, "model"),
    )


def serialize_error(error: SchemaValidationError) -> dict[str, object]:
    """Convert a validation error into a JSON response payload.

    Args:
        error: Validation error raised while parsing a request.

    Returns:
        Error payload ready for JSON serialization.
    """
    payload: dict[str, object] = {
        "error": error.error,
        "message": str(error),
    }
    if error.issues:
        payload["details"] = [
            {"field": issue.field, "message": issue.message} for issue in error.issues
        ]
    return payload


def _parse_json_object(body: bytes) -> JsonObject:
    if not body:
        msg = "Request body must be a JSON object."
        raise SchemaValidationError(
            msg,
            issues=(ValidationIssue(field="body", message="Request body is required."),),
        )

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "Request body must be valid UTF-8 JSON."
        raise SchemaValidationError(
            msg,
            status_code=400,
            error="invalid_json",
        ) from exc

    try:
        parsed = json.loads(text, object_pairs_hook=_JsonPairs)
    except JSONDecodeError as exc:
        msg = "Request body must be valid JSON."
        raise SchemaValidationError(
            msg,
            status_code=400,
            error="invalid_json",
        ) from exc

    normalized = _normalize_json(parsed)
    if not isinstance(normalized, dict):
        msg = "Request body must be a JSON object."
        issues = (
            ValidationIssue(field="body", message="Top-level JSON value must be an object."),
        )
        raise SchemaValidationError(
            msg,
            issues=issues,
        )
    return normalized


def _normalize_json(value: object) -> JsonValue:
    if isinstance(value, _JsonPairs):
        normalized: JsonObject = {}
        for key, item in value:
            if key in normalized:
                msg = "Request body contains duplicate fields."
                raise SchemaValidationError(
                    msg,
                    issues=(
                        ValidationIssue(
                            field=key,
                            message="Duplicate JSON fields are not allowed.",
                        ),
                    ),
                )
            normalized[key] = _normalize_json(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    msg = "Request body contains unsupported JSON content."
    raise SchemaValidationError(
        msg,
        status_code=400,
        error="invalid_json",
    )


def _reject_unknown_fields(payload: JsonObject, allowed_fields: set[str]) -> None:
    unknown_fields = sorted(set(payload) - allowed_fields)
    if not unknown_fields:
        return
    issues = tuple(
        ValidationIssue(field=field, message="Unknown field is not allowed.")
        for field in unknown_fields
    )
    msg = "Request body contains unknown fields."
    raise SchemaValidationError(msg, issues=issues)


def _require_string(payload: JsonObject, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        msg = f"Field '{field}' must be a non-empty string."
        raise SchemaValidationError(
            msg,
            issues=(
                ValidationIssue(field=field, message="Expected a non-empty string value."),
            ),
        )
    return value.strip()


def _optional_string(payload: JsonObject, field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        msg = f"Field '{field}' must be a non-empty string when provided."
        raise SchemaValidationError(
            msg,
            issues=(
                ValidationIssue(field=field, message="Expected a non-empty string value."),
            ),
        )
    return value.strip()
