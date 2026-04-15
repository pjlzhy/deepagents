"""Namespace wrappers for LangGraph stream parts."""

from __future__ import annotations

from dataclasses import dataclass

from ._base import View, as_object_tuple, issue


@dataclass(frozen=True, slots=True, kw_only=True)
class NamespaceStructure:
    """Normalized namespace segments."""

    segments: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class NamespaceClassification:
    """Derived metadata for one namespace."""

    depth: int
    is_root: bool
    head: str | None
    tail: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class NamespaceView(View[NamespaceStructure, NamespaceClassification]):
    """Structured view over one LangGraph namespace tuple."""


def wrap_namespace(raw: object) -> NamespaceView:
    """Wrap one namespace payload into a stable immutable view."""

    issues = []
    raw_items = as_object_tuple(raw)
    segments: list[str] = []
    if raw_items is None:
        if raw is not None:
            issues.append(
                issue(
                    "ns",
                    "sequence[str]",
                    raw,
                    "Expected `ns` to be a sequence of namespace segments.",
                )
            )
    else:
        for index, item in enumerate(raw_items):
            if isinstance(item, str):
                segments.append(item)
                continue
            issues.append(
                issue(
                    f"ns[{index}]",
                    "str",
                    item,
                    "Non-string namespace segment was coerced to string.",
                )
            )
            segments.append(str(item))

    segment_tuple = tuple(segments)
    return NamespaceView(
        raw=raw,
        structure=NamespaceStructure(segments=segment_tuple),
        classification=NamespaceClassification(
            depth=len(segment_tuple),
            is_root=len(segment_tuple) == 0,
            head=segment_tuple[0] if segment_tuple else None,
            tail=segment_tuple[-1] if segment_tuple else None,
        ),
        issues=tuple(issues),
    )
