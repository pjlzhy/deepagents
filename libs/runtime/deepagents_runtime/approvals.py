"""Shared HITL approval helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

BatchApprovalChoice: TypeAlias = Literal[
    "approve",
    "reject",
    "auto_approve_all",
]
"""Supported batch approval choices emitted by interactive clients."""

HITLDecisionPayload: TypeAlias = dict[str, str]
"""A single HITL decision payload sent back to the agent runtime."""


@dataclass(frozen=True, slots=True)
class BatchApprovalResolution:
    """Normalized result for one batch approval decision."""

    choice: BatchApprovalChoice | None
    decisions: list[HITLDecisionPayload]
    enable_auto_approve: bool = False
    rejected: bool = False


def normalize_batch_approval_choice(decision: object) -> BatchApprovalChoice | None:
    """Normalize a raw approval UI result into a supported choice.

    Args:
        decision: Raw value returned by a UI approval surface.

    Returns:
        Normalized approval choice, or `None` for malformed/unknown payloads.
    """
    if not isinstance(decision, dict):
        return None

    choice = decision.get("type")
    if choice in {"approve", "reject", "auto_approve_all"}:
        return choice
    return None


def build_uniform_hitl_decisions(
    action_count: int,
    decision_type: Literal["approve", "reject"],
) -> list[HITLDecisionPayload]:
    """Build one identical HITL decision per requested action.

    Args:
        action_count: Number of action requests in the batch.
        decision_type: Decision type to apply to each action.

    Returns:
        List of LangGraph-compatible decision payloads.

    Raises:
        ValueError: If `action_count` is less than 1.
    """
    if action_count < 1:
        msg = "action_count must be at least 1"
        raise ValueError(msg)
    return [{"type": decision_type} for _ in range(action_count)]


def resolve_batch_approval_choice(
    action_count: int,
    choice: BatchApprovalChoice | None,
    *,
    auto_approve: bool = False,
) -> BatchApprovalResolution:
    """Resolve one batch approval choice into HITL decision payloads.

    Args:
        action_count: Number of action requests in the batch.
        choice: Explicit approval choice from the UI.
        auto_approve: Whether the session is already in auto-approve mode.

    Returns:
        Normalized batch approval resolution.
    """
    if auto_approve:
        return BatchApprovalResolution(
            choice="approve",
            decisions=build_uniform_hitl_decisions(action_count, "approve"),
        )

    if choice == "approve":
        return BatchApprovalResolution(
            choice=choice,
            decisions=build_uniform_hitl_decisions(action_count, "approve"),
        )

    if choice == "auto_approve_all":
        return BatchApprovalResolution(
            choice=choice,
            decisions=build_uniform_hitl_decisions(action_count, "approve"),
            enable_auto_approve=True,
        )

    return BatchApprovalResolution(
        choice=choice,
        decisions=build_uniform_hitl_decisions(action_count, "reject"),
        rejected=True,
    )
