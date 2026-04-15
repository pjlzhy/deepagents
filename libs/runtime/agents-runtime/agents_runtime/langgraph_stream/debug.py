"""Wrappers for `debug` stream parts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from ._base import PartView, View, as_string_mapping, field_value, issue, string_field
from .checkpoints import CheckpointView, wrap_checkpoint
from .tasks import TaskResultView, TaskStartView, wrap_task_result, wrap_task_start

DebugVariant = Literal["checkpoint", "task", "task_result"]


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugCheckpointStructure:
    payload: CheckpointView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugCheckpointClassification:
    variant: Literal["checkpoint"]


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugCheckpointView(View[DebugCheckpointStructure, DebugCheckpointClassification]):
    """Structured view over a debug checkpoint event."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugTaskStructure:
    payload: TaskStartView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugTaskClassification:
    variant: Literal["task"]


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugTaskView(View[DebugTaskStructure, DebugTaskClassification]):
    """Structured view over a debug task event."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugTaskResultStructure:
    payload: TaskResultView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugTaskResultClassification:
    variant: Literal["task_result"]


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugTaskResultView(View[DebugTaskResultStructure, DebugTaskResultClassification]):
    """Structured view over a debug task result event."""


DebugEventView: TypeAlias = DebugCheckpointView | DebugTaskView | DebugTaskResultView


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugPartStructure:
    step: int | None
    timestamp: str | None
    event: DebugEventView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugPartClassification:
    variant: DebugVariant | None
    has_step: bool
    has_timestamp: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugPartView(PartView[DebugPartStructure, DebugPartClassification]):
    """Structured view over one `debug` stream part."""


def wrap_debug_part(
    *,
    raw_part: object,
    header: object,
    data: object,
) -> DebugPartView:
    """Wrap one `debug` stream payload."""

    issues = []
    mapping = as_string_mapping(data)
    step = None
    timestamp = None
    event: DebugEventView | None = None
    variant: DebugVariant | None = None
    if mapping is None:
        issues.append(
            issue(
                "data",
                "mapping",
                data,
                "Expected `debug.data` to be a mapping.",
            )
        )
    else:
        step_value = field_value(data, "step")
        if isinstance(step_value, int) and not isinstance(step_value, bool):
            step = step_value
        elif step_value is not None:
            issues.append(
                issue(
                    "data.step",
                    "int",
                    step_value,
                    "Debug `step` should be an integer.",
                )
            )

        timestamp = string_field(data, "timestamp")
        if field_value(data, "timestamp") is not None and timestamp is None:
            issues.append(
                issue(
                    "data.timestamp",
                    "str",
                    field_value(data, "timestamp"),
                    "Debug `timestamp` should be a string.",
                )
            )

        raw_variant = string_field(data, "type")
        payload = field_value(data, "payload")
        if raw_variant == "checkpoint":
            variant = "checkpoint"
            event = wrap_debug_checkpoint(payload)
        elif raw_variant == "task":
            variant = "task"
            event = wrap_debug_task(payload)
        elif raw_variant == "task_result":
            variant = "task_result"
            event = wrap_debug_task_result(payload)
        else:
            issues.append(
                issue(
                    "data.type",
                    "checkpoint | task | task_result",
                    raw_variant,
                    "Unsupported debug event type.",
                )
            )

    return DebugPartView(
        raw=raw_part,
        header=header,
        structure=DebugPartStructure(
            step=step,
            timestamp=timestamp,
            event=event,
        ),
        classification=DebugPartClassification(
            variant=variant,
            has_step=step is not None,
            has_timestamp=timestamp is not None,
        ),
        issues=tuple(issues),
    )


def wrap_debug_checkpoint(raw: object) -> DebugCheckpointView:
    """Wrap a debug checkpoint payload."""

    checkpoint = wrap_checkpoint(raw) if raw is not None else None
    return DebugCheckpointView(
        raw=raw,
        structure=DebugCheckpointStructure(payload=checkpoint),
        classification=DebugCheckpointClassification(variant="checkpoint"),
        issues=(),
    )


def wrap_debug_task(raw: object) -> DebugTaskView:
    """Wrap a debug task payload."""

    payload = wrap_task_start(raw) if raw is not None else None
    return DebugTaskView(
        raw=raw,
        structure=DebugTaskStructure(payload=payload),
        classification=DebugTaskClassification(variant="task"),
        issues=(),
    )


def wrap_debug_task_result(raw: object) -> DebugTaskResultView:
    """Wrap a debug task result payload."""

    payload = wrap_task_result(raw) if raw is not None else None
    return DebugTaskResultView(
        raw=raw,
        structure=DebugTaskResultStructure(payload=payload),
        classification=DebugTaskResultClassification(variant="task_result"),
        issues=(),
    )
