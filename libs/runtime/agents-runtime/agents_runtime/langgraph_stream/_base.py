"""Shared view types and parsing helpers for LangGraph stream wrappers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Literal, TypeVar, cast

if TYPE_CHECKING:
    from .namespace import NamespaceView

S = TypeVar("S")
C = TypeVar("C")

StreamMode = Literal[
    "values",
    "updates",
    "messages",
    "custom",
    "checkpoints",
    "tasks",
    "debug",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class ParseIssue:
    """Describes one non-fatal shape mismatch while wrapping a stream event."""

    path: str
    expected: str
    actual: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class View(Generic[S, C]):
    """Base immutable wrapper view."""

    raw: object
    structure: S
    classification: C
    issues: tuple[ParseIssue, ...] = ()

    @property
    def is_well_formed(self) -> bool:
        """Return `True` when no parse issues were recorded."""

        return not self.issues


@dataclass(frozen=True, slots=True, kw_only=True)
class PartHeader:
    """Metadata shared by all top-level stream parts."""

    mode: StreamMode | str
    ns: NamespaceView


@dataclass(frozen=True, slots=True, kw_only=True)
class PartView(View[S, C], Generic[S, C]):
    """Base immutable wrapper for one LangGraph stream part."""

    header: PartHeader


def issue(
    path: str,
    expected: str,
    actual_value: object,
    message: str,
) -> ParseIssue:
    """Create one parse issue with a stable `actual` description."""

    return ParseIssue(
        path=path,
        expected=expected,
        actual=type_name(actual_value),
        message=message,
    )


def type_name(value: object) -> str:
    """Return a readable runtime type name."""

    if value is None:
        return "None"
    return type(value).__name__


def is_mapping(value: object) -> bool:
    """Return whether `value` behaves like a mapping."""

    return isinstance(value, Mapping)


def as_string_mapping(value: object) -> dict[str, object] | None:
    """Return a mapping with string keys when `value` is mapping-like."""

    if not is_mapping(value):
        return None
    mapping = cast(Mapping[object, object], value)
    return {str(key): cast(object, item) for key, item in mapping.items()}


def is_sequence(value: object) -> bool:
    """Return whether `value` should be treated as a data sequence."""

    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def as_object_tuple(value: object) -> tuple[object, ...] | None:
    """Return a tuple view when `value` is sequence-like."""

    if not is_sequence(value):
        return None
    return tuple(cast(Sequence[object], value))


def field_value(raw: object, name: str) -> object | None:
    """Read a field from either a mapping payload or an object attribute."""

    mapping = as_string_mapping(raw)
    if mapping is not None and name in mapping:
        return mapping[name]
    if hasattr(raw, name):
        return cast(object, getattr(raw, name))
    return None


def has_field(raw: object, name: str) -> bool:
    """Return whether a field is present on a mapping or object."""

    mapping = as_string_mapping(raw)
    if mapping is not None and name in mapping:
        return True
    return hasattr(raw, name)


def string_field(raw: object, name: str) -> str | None:
    """Read one optional string field."""

    value = field_value(raw, name)
    return value if isinstance(value, str) else None


def int_field(raw: object, name: str) -> int | None:
    """Read one optional integer field."""

    value = field_value(raw, name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def mapping_field(raw: object, name: str) -> dict[str, object] | None:
    """Read one optional mapping field."""

    value = field_value(raw, name)
    return as_string_mapping(value)


def object_sequence_field(raw: object, name: str) -> tuple[object, ...] | None:
    """Read one optional sequence field."""

    value = field_value(raw, name)
    return as_object_tuple(value)


def extras_from_mapping(
    mapping: dict[str, object] | None,
    *,
    used_keys: set[str],
) -> dict[str, object]:
    """Return unmapped keys from a parsed mapping."""

    if mapping is None:
        return {}
    return {key: value for key, value in mapping.items() if key not in used_keys}
