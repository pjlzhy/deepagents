"""Wrappers for `updates` and interrupt payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._base import (
    PartView,
    View,
    as_object_tuple,
    as_string_mapping,
    field_value,
    issue,
    string_field,
    type_name,
)

UpdateEntryKind = Literal["write", "interrupts", "metadata", "reserved"]


@dataclass(frozen=True, slots=True, kw_only=True)
class InterruptStructure:
    id: str | None
    value: object
    extras: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class InterruptClassification:
    has_id: bool
    value_type: str


@dataclass(frozen=True, slots=True, kw_only=True)
class InterruptView(View[InterruptStructure, InterruptClassification]):
    """Structured view over one interrupt payload."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateEntryStructure:
    key: str
    value: object


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateEntryClassification:
    kind: UpdateEntryKind
    is_reserved: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateEntryView(View[UpdateEntryStructure, UpdateEntryClassification]):
    """Structured view over one `updates.data` entry."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdatesPartStructure:
    entries: tuple[UpdateEntryView, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdatesPartClassification:
    writes: tuple[UpdateEntryView, ...]
    interrupts: tuple[InterruptView, ...]
    metadata_entry: UpdateEntryView | None
    reserved_entries: tuple[UpdateEntryView, ...]
    has_interrupts: bool
    has_writes: bool
    write_keys: tuple[str, ...]
    reserved_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdatesPartView(PartView[UpdatesPartStructure, UpdatesPartClassification]):
    """Structured view over one `updates` stream part."""


def wrap_updates_part(
    *,
    raw_part: object,
    header: object,
    data: object,
) -> UpdatesPartView:
    """Wrap one `updates` stream payload."""

    issues = []
    mapping = as_string_mapping(data)
    entries: tuple[UpdateEntryView, ...] = ()
    interrupts: tuple[InterruptView, ...] = ()
    if mapping is None:
        issues.append(
            issue(
                "data",
                "mapping",
                data,
                "Expected `updates.data` to be a mapping.",
            )
        )
    else:
        entries = tuple(wrap_update_entry(key, value) for key, value in mapping.items())
        interrupt_values = mapping.get("__interrupt__")
        interrupt_items = as_object_tuple(interrupt_values)
        if interrupt_values is not None and interrupt_items is None:
            issues.append(
                issue(
                    "data.__interrupt__",
                    "sequence",
                    interrupt_values,
                    "Interrupt envelope should be a sequence.",
                )
            )
        interrupts = tuple(wrap_interrupt(item) for item in (interrupt_items or ()))

    writes = tuple(
        entry for entry in entries if entry.classification.kind == "write"
    )
    metadata_entry = next(
        (entry for entry in entries if entry.classification.kind == "metadata"),
        None,
    )
    reserved_entries = tuple(
        entry for entry in entries if entry.classification.kind == "reserved"
    )
    return UpdatesPartView(
        raw=raw_part,
        header=header,
        structure=UpdatesPartStructure(entries=entries),
        classification=UpdatesPartClassification(
            writes=writes,
            interrupts=interrupts,
            metadata_entry=metadata_entry,
            reserved_entries=reserved_entries,
            has_interrupts=bool(interrupts),
            has_writes=bool(writes),
            write_keys=tuple(entry.structure.key for entry in writes),
            reserved_keys=tuple(entry.structure.key for entry in reserved_entries),
        ),
        issues=tuple(issues),
    )


def wrap_update_entry(key: str, value: object) -> UpdateEntryView:
    """Wrap one `updates.data` entry."""

    kind: UpdateEntryKind
    if key == "__interrupt__":
        kind = "interrupts"
    elif key == "__metadata__":
        kind = "metadata"
    elif key.startswith("__") and key.endswith("__"):
        kind = "reserved"
    else:
        kind = "write"
    return UpdateEntryView(
        raw={key: value},
        structure=UpdateEntryStructure(key=key, value=value),
        classification=UpdateEntryClassification(
            kind=kind,
            is_reserved=kind in {"interrupts", "metadata", "reserved"},
        ),
        issues=(),
    )


def wrap_interrupt(raw: object) -> InterruptView:
    """Wrap one interrupt object or interrupt dict."""

    issues = []
    mapping = as_string_mapping(raw)
    identifier = string_field(raw, "id")
    value = field_value(raw, "value")
    if value is None and mapping is None and identifier is None:
        value = raw
        issues.append(
            issue(
                "interrupt",
                "interrupt object or mapping",
                raw,
                "Interrupt payload does not expose `id` or `value`; raw value was preserved.",
            )
        )
    extras = {}
    if mapping is not None:
        extras = {key: item for key, item in mapping.items() if key not in {"id", "value"}}
    return InterruptView(
        raw=raw,
        structure=InterruptStructure(
            id=identifier,
            value=value,
            extras=extras,
        ),
        classification=InterruptClassification(
            has_id=identifier is not None,
            value_type=type_name(value),
        ),
        issues=tuple(issues),
    )
