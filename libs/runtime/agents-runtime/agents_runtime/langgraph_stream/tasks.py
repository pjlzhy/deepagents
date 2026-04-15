"""Wrappers for `tasks` stream parts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from ._base import PartView, View, as_object_tuple, as_string_mapping, field_value, issue, string_field
from .updates import InterruptView, wrap_interrupt

TaskVariant = Literal["start", "result"]


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskStartStructure:
    id: str | None
    name: str | None
    input: object
    triggers: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskStartClassification:
    variant: Literal["start"]
    has_id: bool
    has_input: bool
    has_triggers: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskStartView(View[TaskStartStructure, TaskStartClassification]):
    """Structured view over one task start payload."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskResultStructure:
    id: str | None
    name: str | None
    error: str | None
    interrupts: tuple[InterruptView, ...]
    result: object


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskResultClassification:
    variant: Literal["result"]
    has_error: bool
    has_interrupts: bool
    has_result: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskResultView(View[TaskResultStructure, TaskResultClassification]):
    """Structured view over one task result payload."""


TaskEventView: TypeAlias = TaskStartView | TaskResultView


@dataclass(frozen=True, slots=True, kw_only=True)
class TasksPartStructure:
    event: TaskEventView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class TasksPartClassification:
    variant: TaskVariant | None
    task_name: str | None
    task_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class TasksPartView(PartView[TasksPartStructure, TasksPartClassification]):
    """Structured view over one `tasks` stream part."""


def wrap_tasks_part(
    *,
    raw_part: object,
    header: object,
    data: object,
) -> TasksPartView:
    """Wrap one `tasks` stream payload."""

    issues = []
    event: TaskEventView | None = None
    mapping = as_string_mapping(data)
    if mapping is None:
        issues.append(
            issue(
                "data",
                "mapping",
                data,
                "Expected `tasks.data` to be a mapping.",
            )
        )
    else:
        if is_task_result_mapping(mapping):
            event = wrap_task_result(data)
        elif is_task_start_mapping(mapping):
            event = wrap_task_start(data)
        else:
            issues.append(
                issue(
                    "data",
                    "TaskPayload or TaskResultPayload",
                    data,
                    "Task payload shape did not match start or result schemas.",
                )
            )

    return TasksPartView(
        raw=raw_part,
        header=header,
        structure=TasksPartStructure(event=event),
        classification=TasksPartClassification(
            variant=event.classification.variant if event is not None else None,
            task_name=event.structure.name if event is not None else None,
            task_id=event.structure.id if event is not None else None,
        ),
        issues=tuple(issues),
    )


def wrap_task_start(raw: object) -> TaskStartView:
    """Wrap one task start payload."""

    issues = []
    mapping = as_string_mapping(raw)
    triggers = tuple(_coerce_str_sequence(field_value(raw, "triggers"), path="triggers", issues=issues))
    if mapping is None:
        issues.append(
            issue(
                "task",
                "mapping",
                raw,
                "Task start payload should be a mapping.",
            )
        )
    return TaskStartView(
        raw=raw,
        structure=TaskStartStructure(
            id=string_field(raw, "id"),
            name=string_field(raw, "name"),
            input=field_value(raw, "input"),
            triggers=triggers,
        ),
        classification=TaskStartClassification(
            variant="start",
            has_id=string_field(raw, "id") is not None,
            has_input=("input" in mapping) if mapping is not None else field_value(raw, "input") is not None,
            has_triggers=bool(triggers),
        ),
        issues=tuple(issues),
    )


def wrap_task_result(raw: object) -> TaskResultView:
    """Wrap one task result payload."""

    issues = []
    mapping = as_string_mapping(raw)
    interrupts_raw = field_value(raw, "interrupts")
    interrupt_items = as_object_tuple(interrupts_raw)
    if interrupts_raw is not None and interrupt_items is None:
        issues.append(
            issue(
                "interrupts",
                "sequence",
                interrupts_raw,
                "Task result interrupts should be a sequence.",
            )
        )
    has_result = mapping is not None and "result" in mapping
    return TaskResultView(
        raw=raw,
        structure=TaskResultStructure(
            id=string_field(raw, "id"),
            name=string_field(raw, "name"),
            error=string_field(raw, "error"),
            interrupts=tuple(wrap_interrupt(item) for item in (interrupt_items or ())),
            result=field_value(raw, "result"),
        ),
        classification=TaskResultClassification(
            variant="result",
            has_error=string_field(raw, "error") is not None,
            has_interrupts=bool(interrupt_items),
            has_result=has_result,
        ),
        issues=tuple(issues),
    )


def is_task_start_mapping(mapping: dict[str, object]) -> bool:
    """Return whether a task payload looks like a start event."""

    return "input" in mapping or "triggers" in mapping


def is_task_result_mapping(mapping: dict[str, object]) -> bool:
    """Return whether a task payload looks like a result event."""

    return "result" in mapping or "error" in mapping or "interrupts" in mapping


def _coerce_str_sequence(
    value: object,
    *,
    path: str,
    issues: list[object],
) -> list[str]:
    items = as_object_tuple(value)
    if items is None:
        if value is not None:
            issues.append(
                issue(
                    path,
                    "sequence[str]",
                    value,
                    "Value should be a string sequence.",
                )
            )
        return []
    strings: list[str] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            strings.append(item)
            continue
        issues.append(
            issue(
                f"{path}[{index}]",
                "str",
                item,
                "Value was coerced to string.",
            )
        )
        strings.append(str(item))
    return strings
