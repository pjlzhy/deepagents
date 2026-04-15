"""Top-level LangGraph v2 stream part wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from ._base import PartHeader, PartView, as_object_tuple, as_string_mapping, issue, type_name
from .checkpoints import CheckpointsPartView, wrap_checkpoints_part
from .debug import DebugPartView, wrap_debug_part
from .messages import MessagesPartView, wrap_messages_part
from .namespace import wrap_namespace
from .tasks import TasksPartView, wrap_tasks_part
from .updates import InterruptView, UpdatesPartView, wrap_interrupt, wrap_updates_part


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuesPartStructure:
    value: object
    interrupts: tuple[InterruptView, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuesPartClassification:
    has_interrupts: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuesPartView(PartView[ValuesPartStructure, ValuesPartClassification]):
    """Structured view over one `values` stream part."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomPartStructure:
    value: object


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomPartClassification:
    value_type: str
    is_mapping: bool
    is_sequence: bool
    is_scalar: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomPartView(PartView[CustomPartStructure, CustomPartClassification]):
    """Structured view over one `custom` stream part."""


UnknownReason = Literal["not_mapping", "missing_type", "unsupported_type", "malformed_part"]


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownPartStructure:
    type_name: str | None
    data: object


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownPartClassification:
    reason: UnknownReason


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownPartView(PartView[UnknownPartStructure, UnknownPartClassification]):
    """Fallback wrapper for unsupported or malformed outer parts."""


StreamPartView: TypeAlias = (
    ValuesPartView
    | UpdatesPartView
    | MessagesPartView
    | CustomPartView
    | CheckpointsPartView
    | TasksPartView
    | DebugPartView
    | UnknownPartView
)


def wrap_stream_part(raw: object) -> StreamPartView:
    """Wrap one raw LangGraph v2 stream part into a typed view."""

    mapping = as_string_mapping(raw)
    if mapping is None:
        return UnknownPartView(
            raw=raw,
            header=PartHeader(mode="unknown", ns=wrap_namespace(())),
            structure=UnknownPartStructure(type_name=None, data=None),
            classification=UnknownPartClassification(reason="not_mapping"),
            issues=(
                issue(
                    "part",
                    "mapping",
                    raw,
                    "Stream part should be a mapping with `type`, `ns`, and `data`.",
                ),
            ),
        )

    ns = wrap_namespace(mapping.get("ns"))
    raw_mode = mapping.get("type")
    data = mapping.get("data")
    if not isinstance(raw_mode, str):
        return UnknownPartView(
            raw=raw,
            header=PartHeader(mode="unknown", ns=ns),
            structure=UnknownPartStructure(type_name=None, data=data),
            classification=UnknownPartClassification(reason="missing_type"),
            issues=(
                issue(
                    "part.type",
                    "str",
                    raw_mode,
                    "Stream part is missing a string `type` discriminator.",
                ),
            ),
        )

    header = PartHeader(mode=raw_mode, ns=ns)
    if raw_mode == "messages":
        return wrap_messages_part(raw_part=raw, header=header, data=data)
    if raw_mode == "updates":
        return wrap_updates_part(raw_part=raw, header=header, data=data)
    if raw_mode == "tasks":
        return wrap_tasks_part(raw_part=raw, header=header, data=data)
    if raw_mode == "checkpoints":
        return wrap_checkpoints_part(raw_part=raw, header=header, data=data)
    if raw_mode == "debug":
        return wrap_debug_part(raw_part=raw, header=header, data=data)
    if raw_mode == "values":
        return wrap_values_part(raw_part=raw, header=header, mapping=mapping)
    if raw_mode == "custom":
        return wrap_custom_part(raw_part=raw, header=header, data=data)
    return UnknownPartView(
        raw=raw,
        header=header,
        structure=UnknownPartStructure(type_name=raw_mode, data=data),
        classification=UnknownPartClassification(reason="unsupported_type"),
        issues=(
            issue(
                "part.type",
                "known StreamMode",
                raw_mode,
                "Unsupported stream mode.",
            ),
        ),
    )


def wrap_values_part(
    *,
    raw_part: object,
    header: PartHeader,
    mapping: dict[str, object],
) -> ValuesPartView:
    """Wrap one `values` stream part."""

    issues = []
    interrupt_items = as_object_tuple(mapping.get("interrupts"))
    if mapping.get("interrupts") is not None and interrupt_items is None:
        issues.append(
            issue(
                "part.interrupts",
                "sequence",
                mapping.get("interrupts"),
                "Values interrupts should be a sequence.",
            )
        )
    interrupts = tuple(wrap_interrupt(item) for item in (interrupt_items or ()))
    return ValuesPartView(
        raw=raw_part,
        header=header,
        structure=ValuesPartStructure(
            value=mapping.get("data"),
            interrupts=interrupts,
        ),
        classification=ValuesPartClassification(has_interrupts=bool(interrupts)),
        issues=tuple(issues),
    )


def wrap_custom_part(
    *,
    raw_part: object,
    header: PartHeader,
    data: object,
) -> CustomPartView:
    """Wrap one `custom` stream part."""

    is_mapping_value = as_string_mapping(data) is not None
    is_sequence_value = as_object_tuple(data) is not None
    return CustomPartView(
        raw=raw_part,
        header=header,
        structure=CustomPartStructure(value=data),
        classification=CustomPartClassification(
            value_type=type_name(data),
            is_mapping=is_mapping_value,
            is_sequence=is_sequence_value,
            is_scalar=not is_mapping_value and not is_sequence_value,
        ),
        issues=(),
    )
