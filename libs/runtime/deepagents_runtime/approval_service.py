"""Durable approval state for HITL interrupts.

This module provides a small runtime-managed approval service that tracks
pending HITL requests keyed by `run_id` and `thread_id`.

The primary goal is to support browser refresh/reconnect semantics: when a run
is paused waiting for approval, a client can re-query the server for the
pending approval payload and then submit an approval decision.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from deepagents_runtime.approvals import (
    BatchApprovalChoice,
    resolve_batch_approval_choice,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.human_in_the_loop import HITLRequest

    from deepagents_runtime.orchestration import HITLResponsePayload


def _json_safe_value(value: object) -> Any:  # noqa: ANN401
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]
    return str(value)


def _serialize_hitl_request(request: HITLRequest) -> dict[str, Any]:
    safe_value = _json_safe_value(request)
    if isinstance(safe_value, dict):
        return safe_value
    return {"repr": str(safe_value)}


def _count_action_requests(request: HITLRequest) -> int:
    action_requests = request.get("action_requests", [])
    if isinstance(action_requests, list):
        return len(action_requests)
    return 0


@dataclass(frozen=True, slots=True)
class PendingApproval:
    """Snapshot of a pending approval request for a run."""

    run_id: str
    thread_id: str
    interrupt_ids: tuple[str, ...]
    interrupts: dict[str, dict[str, Any]]
    created_at: float


@dataclass(slots=True)
class _RunApprovalState:
    run_id: str
    thread_id: str
    interrupt_ids: tuple[str, ...]
    interrupts: dict[str, dict[str, Any]]
    action_counts: dict[str, int]
    decision: asyncio.Future[BatchApprovalChoice]
    created_at: float


class ApprovalService:
    """Runtime-managed approval state keyed by `run_id` and `thread_id`.

    This service is intentionally in-memory. For local-first web usage, the
    server process persists across browser refresh/reconnect, so keeping the
    approval state in the backend process is sufficient.

    The service also tracks per-thread auto-approve mode. When enabled, HITL
    requests are automatically approved without prompting the client.
    """

    def __init__(self) -> None:
        """Initialize the approval service with empty run and thread state."""
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunApprovalState] = {}
        self._thread_auto_approve: dict[str, bool] = {}

    async def get_thread_auto_approve(self, thread_id: str) -> bool:
        """Return whether auto-approve is enabled for the given thread."""
        async with self._lock:
            return self._thread_auto_approve.get(thread_id, False)

    async def set_thread_auto_approve(self, thread_id: str, *, enabled: bool) -> None:
        """Enable/disable auto-approve mode for the given thread."""
        async with self._lock:
            if enabled:
                self._thread_auto_approve[thread_id] = True
            else:
                self._thread_auto_approve.pop(thread_id, None)

    async def get_pending(self, run_id: str) -> PendingApproval | None:
        """Return the pending approval request for a run, if any."""
        async with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return None
            return PendingApproval(
                run_id=state.run_id,
                thread_id=state.thread_id,
                interrupt_ids=state.interrupt_ids,
                interrupts=dict(state.interrupts),
                created_at=state.created_at,
            )

    async def resolve_run(self, run_id: str, choice: BatchApprovalChoice) -> bool:
        """Resolve a pending approval request by setting the run decision.

        Args:
            run_id: Run identifier that is currently waiting for approval.
            choice: Approval decision to apply to all pending interrupts.

        Returns:
            `True` when the run was pending and is now resolved, `False` when
            there was no pending approval request for `run_id`.
        """
        async with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return False
            if state.decision.done():
                return False
            state.decision.set_result(choice)
            return True

    def create_resolver(
        self,
        *,
        run_id: str,
        thread_id: str,
        cancel_on_reject: bool = True,
    ) -> Callable[[dict[str, HITLRequest]], Awaitable[object]]:
        """Create an async approval resolver compatible with `stream_run_events`.

        The returned callable can be supplied as `AgentRunConfig.resolve_approvals`.

        Args:
            run_id: Run identifier to associate with stored approval state.
            thread_id: Thread identifier used for per-thread auto-approve mode.
            cancel_on_reject: When `True`, a `reject` decision returns an empty
                resume payload so the run service emits `run.cancelled` instead
                of resuming the agent with explicit reject decisions. This
                matches current Textual behavior.

        Returns:
            Async callable that resolves pending interrupts to a resume payload.
        """

        async def _resolver(pending_interrupts: dict[str, HITLRequest]) -> object:
            return await self.resolve_pending_interrupts(
                run_id=run_id,
                thread_id=thread_id,
                pending_interrupts=pending_interrupts,
                cancel_on_reject=cancel_on_reject,
            )

        return _resolver

    async def resolve_pending_interrupts(
        self,
        *,
        run_id: str,
        thread_id: str,
        pending_interrupts: dict[str, HITLRequest],
        cancel_on_reject: bool,
    ) -> HITLResponsePayload:
        """Resolve a batch of pending interrupts for a run.

        This method stores the pending approval request, waits for an external
        decision (via `resolve_run`), and returns a LangGraph resume payload.

        Returns:
            LangGraph resume payload keyed by interrupt ID, or `{}` when the
            caller chose to cancel the run instead of resuming after a reject.

        Raises:
            asyncio.CancelledError: If the caller cancels the run while waiting
                for an approval decision.
        """
        if await self.get_thread_auto_approve(thread_id):
            return self._build_resume_payload(
                pending_interrupts,
                choice="approve",
                auto_approve=True,
                cancel_on_reject=cancel_on_reject,
            )

        await self._register_pending(run_id, thread_id, pending_interrupts)
        try:
            choice = await self._wait_for_choice(run_id)
        except asyncio.CancelledError:
            await self._clear_run(run_id)
            raise

        if choice == "auto_approve_all":
            await self.set_thread_auto_approve(thread_id, enabled=True)

        payload = self._build_resume_payload(
            pending_interrupts,
            choice=choice,
            auto_approve=False,
            cancel_on_reject=cancel_on_reject,
        )
        await self._clear_run(run_id)
        return payload

    async def _register_pending(
        self,
        run_id: str,
        thread_id: str,
        pending_interrupts: dict[str, HITLRequest],
    ) -> None:
        interrupt_ids = tuple(sorted(pending_interrupts))
        interrupts = {
            interrupt_id: _serialize_hitl_request(hitl_request)
            for interrupt_id, hitl_request in pending_interrupts.items()
        }
        action_counts = {
            interrupt_id: _count_action_requests(hitl_request)
            for interrupt_id, hitl_request in pending_interrupts.items()
        }
        created_at = time.monotonic()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[BatchApprovalChoice] = loop.create_future()

        async with self._lock:
            existing = self._runs.get(run_id)
            if existing is not None and not existing.decision.done():
                msg = f"run {run_id} already has a pending approval request"
                raise RuntimeError(msg)
            self._runs[run_id] = _RunApprovalState(
                run_id=run_id,
                thread_id=thread_id,
                interrupt_ids=interrupt_ids,
                interrupts=interrupts,
                action_counts=action_counts,
                decision=future,
                created_at=created_at,
            )

    async def _wait_for_choice(self, run_id: str) -> BatchApprovalChoice:
        async with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                msg = f"run {run_id} has no pending approval request"
                raise RuntimeError(msg)
            future = state.decision
        return await future

    async def _clear_run(self, run_id: str) -> None:
        async with self._lock:
            self._runs.pop(run_id, None)

    @staticmethod
    def _build_resume_payload(
        pending_interrupts: dict[str, HITLRequest],
        *,
        choice: BatchApprovalChoice,
        auto_approve: bool,
        cancel_on_reject: bool,
    ) -> HITLResponsePayload:
        if choice == "reject" and cancel_on_reject and not auto_approve:
            return {}

        payload: HITLResponsePayload = {}
        any_rejected = False
        for interrupt_id, hitl_request in pending_interrupts.items():
            action_count = _count_action_requests(hitl_request)
            resolution = resolve_batch_approval_choice(
                action_count,
                choice,
                auto_approve=auto_approve,
            )
            payload[interrupt_id] = {"decisions": resolution.decisions}
            any_rejected = any_rejected or resolution.rejected

        if any_rejected and cancel_on_reject and not auto_approve:
            return {}

        return payload
