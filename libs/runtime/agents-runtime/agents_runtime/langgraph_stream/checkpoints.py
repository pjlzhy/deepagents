"""Wrappers for `checkpoints` stream parts."""

from __future__ import annotations

from dataclasses import dataclass

from ._base import (
    PartView,
    View,
    as_object_tuple,
    as_string_mapping,
    extras_from_mapping,
    field_value,
    issue,
    string_field,
)
from .updates import InterruptView, wrap_interrupt


@dataclass(frozen=True, slots=True, kw_only=True)
class RunnableConfigStructure:
    configurable: dict[str, object] | None
    metadata: dict[str, object] | None
    tags: tuple[str, ...]
    recursion_limit: int | None
    extras: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class RunnableConfigClassification:
    thread_id: str | None
    checkpoint_id: str | None
    checkpoint_ns: str | None
    has_configurable: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RunnableConfigView(View[RunnableConfigStructure, RunnableConfigClassification]):
    """Structured view over one runnable config."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointTaskStructure:
    id: str | None
    name: str | None
    error: str | None
    result: object
    interrupts: tuple[InterruptView, ...]
    state: object


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointTaskClassification:
    has_error: bool
    has_result: bool
    has_interrupts: bool
    has_state: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointTaskView(View[CheckpointTaskStructure, CheckpointTaskClassification]):
    """Structured view over one checkpoint task entry."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointStructure:
    config: RunnableConfigView | None
    metadata: dict[str, object] | None
    values: object
    next_nodes: tuple[str, ...]
    parent_config: RunnableConfigView | None
    tasks: tuple[CheckpointTaskView, ...]
    extras: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointClassification:
    has_parent: bool
    has_tasks: bool
    task_count: int
    next_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointView(View[CheckpointStructure, CheckpointClassification]):
    """Structured view over one checkpoint payload."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointsPartStructure:
    checkpoint: CheckpointView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointsPartClassification:
    has_checkpoint: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointsPartView(PartView[CheckpointsPartStructure, CheckpointsPartClassification]):
    """Structured view over one `checkpoints` stream part."""


def wrap_checkpoints_part(
    *,
    raw_part: object,
    header: object,
    data: object,
) -> CheckpointsPartView:
    """Wrap one `checkpoints` stream payload."""

    checkpoint = wrap_checkpoint(data)
    return CheckpointsPartView(
        raw=raw_part,
        header=header,
        structure=CheckpointsPartStructure(checkpoint=checkpoint),
        classification=CheckpointsPartClassification(has_checkpoint=checkpoint.is_well_formed),
        issues=(),
    )


def wrap_checkpoint(raw: object) -> CheckpointView:
    """Wrap one checkpoint payload."""

    issues = []
    mapping = as_string_mapping(raw)
    if mapping is None:
        issues.append(
            issue(
                "checkpoint",
                "mapping",
                raw,
                "Checkpoint payload should be a mapping.",
            )
        )

    tasks_raw = field_value(raw, "tasks")
    task_items = as_object_tuple(tasks_raw)
    if tasks_raw is not None and task_items is None:
        issues.append(
            issue(
                "checkpoint.tasks",
                "sequence",
                tasks_raw,
                "Checkpoint tasks should be a sequence.",
            )
        )
    next_values = _coerce_str_sequence(field_value(raw, "next"), path="checkpoint.next", issues=issues)
    return CheckpointView(
        raw=raw,
        structure=CheckpointStructure(
            config=wrap_runnable_config(field_value(raw, "config"))
            if field_value(raw, "config") is not None
            else None,
            metadata=as_string_mapping(field_value(raw, "metadata")),
            values=field_value(raw, "values"),
            next_nodes=tuple(next_values),
            parent_config=wrap_runnable_config(field_value(raw, "parent_config"))
            if field_value(raw, "parent_config") is not None
            else None,
            tasks=tuple(wrap_checkpoint_task(item) for item in (task_items or ())),
            extras=extras_from_mapping(
                mapping,
                used_keys={"config", "metadata", "values", "next", "parent_config", "tasks"},
            ),
        ),
        classification=CheckpointClassification(
            has_parent=field_value(raw, "parent_config") is not None,
            has_tasks=bool(task_items),
            task_count=len(task_items or ()),
            next_count=len(next_values),
        ),
        issues=tuple(issues),
    )


def wrap_checkpoint_task(raw: object) -> CheckpointTaskView:
    """Wrap one checkpoint task entry."""

    issues = []
    mapping = as_string_mapping(raw)
    if mapping is None:
        issues.append(
            issue(
                "checkpoint.tasks[]",
                "mapping",
                raw,
                "Checkpoint task should be a mapping.",
            )
        )
    interrupts_raw = field_value(raw, "interrupts")
    interrupt_items = as_object_tuple(interrupts_raw)
    if interrupts_raw is not None and interrupt_items is None:
        issues.append(
            issue(
                "checkpoint.tasks[].interrupts",
                "sequence",
                interrupts_raw,
                "Checkpoint task interrupts should be a sequence.",
            )
        )
    has_result = mapping is not None and "result" in mapping
    return CheckpointTaskView(
        raw=raw,
        structure=CheckpointTaskStructure(
            id=string_field(raw, "id"),
            name=string_field(raw, "name"),
            error=string_field(raw, "error"),
            result=field_value(raw, "result"),
            interrupts=tuple(wrap_interrupt(item) for item in (interrupt_items or ())),
            state=field_value(raw, "state"),
        ),
        classification=CheckpointTaskClassification(
            has_error=string_field(raw, "error") is not None,
            has_result=has_result,
            has_interrupts=bool(interrupt_items),
            has_state=field_value(raw, "state") is not None,
        ),
        issues=tuple(issues),
    )


def wrap_runnable_config(raw: object) -> RunnableConfigView:
    """Wrap one runnable config payload."""

    issues = []
    mapping = as_string_mapping(raw)
    if mapping is None:
        issues.append(
            issue(
                "config",
                "mapping",
                raw,
                "Runnable config should be a mapping.",
            )
        )
    configurable = as_string_mapping(field_value(raw, "configurable"))
    tags = tuple(_coerce_str_sequence(field_value(raw, "tags"), path="config.tags", issues=issues))
    recursion_limit_raw = field_value(raw, "recursion_limit")
    recursion_limit = recursion_limit_raw if isinstance(recursion_limit_raw, int) and not isinstance(recursion_limit_raw, bool) else None
    return RunnableConfigView(
        raw=raw,
        structure=RunnableConfigStructure(
            configurable=configurable,
            metadata=as_string_mapping(field_value(raw, "metadata")),
            tags=tags,
            recursion_limit=recursion_limit,
            extras=extras_from_mapping(
                mapping,
                used_keys={"configurable", "metadata", "tags", "recursion_limit"},
            ),
        ),
        classification=RunnableConfigClassification(
            thread_id=_string_from_mapping(configurable, "thread_id"),
            checkpoint_id=_string_from_mapping(configurable, "checkpoint_id"),
            checkpoint_ns=_string_from_mapping(configurable, "checkpoint_ns"),
            has_configurable=configurable is not None,
        ),
        issues=tuple(issues),
    )


def _string_from_mapping(mapping: dict[str, object] | None, key: str) -> str | None:
    value = mapping.get(key) if mapping is not None else None
    return value if isinstance(value, str) else None


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
