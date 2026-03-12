import pytest

from deepagents_runtime.approvals import (
    BatchApprovalResolution,
    build_uniform_hitl_decisions,
    normalize_batch_approval_choice,
    resolve_batch_approval_choice,
)


def test_normalize_batch_approval_choice_accepts_supported_choice() -> None:
    assert normalize_batch_approval_choice({"type": "approve"}) == "approve"
    assert normalize_batch_approval_choice({"type": "reject"}) == "reject"
    assert (
        normalize_batch_approval_choice({"type": "auto_approve_all"})
        == "auto_approve_all"
    )


def test_normalize_batch_approval_choice_rejects_invalid_payload() -> None:
    assert normalize_batch_approval_choice("approve") is None
    assert normalize_batch_approval_choice({"type": "edit"}) is None
    assert normalize_batch_approval_choice({"other": "approve"}) is None


def test_build_uniform_hitl_decisions_repeats_decision_for_each_action() -> None:
    assert build_uniform_hitl_decisions(3, "approve") == [
        {"type": "approve"},
        {"type": "approve"},
        {"type": "approve"},
    ]


def test_build_uniform_hitl_decisions_requires_positive_action_count() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        build_uniform_hitl_decisions(0, "reject")


def test_resolve_batch_approval_choice_auto_approve_session() -> None:
    resolution = resolve_batch_approval_choice(2, None, auto_approve=True)

    assert resolution == BatchApprovalResolution(
        choice="approve",
        decisions=[{"type": "approve"}, {"type": "approve"}],
        enable_auto_approve=False,
        rejected=False,
    )


def test_resolve_batch_approval_choice_enable_auto_approve() -> None:
    resolution = resolve_batch_approval_choice(2, "auto_approve_all")

    assert resolution == BatchApprovalResolution(
        choice="auto_approve_all",
        decisions=[{"type": "approve"}, {"type": "approve"}],
        enable_auto_approve=True,
        rejected=False,
    )


def test_resolve_batch_approval_choice_rejects_unknown_choice() -> None:
    resolution = resolve_batch_approval_choice(1, None)

    assert resolution == BatchApprovalResolution(
        choice=None,
        decisions=[{"type": "reject"}],
        enable_auto_approve=False,
        rejected=True,
    )
