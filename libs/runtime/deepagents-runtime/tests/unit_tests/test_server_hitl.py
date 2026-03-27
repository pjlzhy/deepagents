"""Unit tests for runtime server HITL transport hardening."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from google.protobuf import struct_pb2

from deepagents_runtime import events
from deepagents_runtime.entry.server import (
    AgentExecutorServicer,
    _HITLDecisionCoordinator,
    _InvalidHITLDecisionError,
    _translate_hitl_decisions,
)
from deepagents_runtime.generated import runtime_pb2 as pb2


class _FakeContext:
    """Minimal stream context stub for AgentExecutor.Run tests."""

    def __init__(self, first_message: pb2.ClientMessage) -> None:
        self._first_message = first_message

    async def read(self) -> pb2.ClientMessage:
        return self._first_message

    def time_remaining(self) -> None:
        return None


class _MessageIterator:
    """Async iterator yielding follow-up client stream messages."""

    def __init__(
        self,
        messages: list[pb2.ClientMessage],
        *,
        ready_event: asyncio.Event | None = None,
    ) -> None:
        self._messages = list(messages)
        self._ready_event = ready_event

    def __aiter__(self) -> _MessageIterator:
        return self

    async def __anext__(self) -> pb2.ClientMessage:
        if not self._messages:
            raise StopAsyncIteration
        if self._ready_event is not None:
            await self._ready_event.wait()
            self._ready_event = None
        await asyncio.sleep(0)
        return self._messages.pop(0)


class _FakeManager:
    """Manager stub that emits one HITL interrupt then waits for a decision."""

    def __init__(self) -> None:
        self.interrupt_ready = asyncio.Event()

    async def invoke(
        self,
        *,
        name: str,
        run_config: Any,
        hitl_handler: Any = None,
        cancel_event: Any = None,
        cancel_reason: str = "",
        cancel_reason_getter: Any = None,
    ):
        del cancel_event, cancel_reason, cancel_reason_getter

        yield events.run_start(
            run_id=run_config.run_id,
            agent_name=name,
            thread_id=run_config.thread_id,
        )
        yield events.hitl_request(
            interrupt_id="interrupt-1",
            action_requests=[{"name": "execute"}],
            run_id=run_config.run_id,
            agent_name=name,
        )
        self.interrupt_ready.set()
        if hitl_handler is not None:
            await hitl_handler(
                {
                    "interrupt_id": "interrupt-1",
                    "action_requests": [{"name": "execute"}],
                }
            )
        yield events.run_end(
            run_id=run_config.run_id,
            agent_name=name,
            stats={},
        )


def test_translate_hitl_decisions_maps_approve_and_reject() -> None:
    """Transport HITL decisions should become LangChain-compatible decisions."""

    decision = pb2.HITLDecision(
        interrupt_id="interrupt-1",
        decisions=[
            pb2.Decision(type="approve"),
            pb2.Decision(type="reject", message="unsafe command"),
        ],
    )

    translated = _translate_hitl_decisions(decision)

    assert translated == [
        {"type": "approve"},
        {"type": "reject", "message": "unsafe command"},
    ]


def test_translate_hitl_decisions_maps_edit() -> None:
    """Edit decisions should preserve the edited action payload."""

    decision = pb2.HITLDecision(
        interrupt_id="interrupt-1",
        decisions=[
            pb2.Decision(
                type="edit",
                edited_action=pb2.Action(
                    name="execute",
                    args=struct_pb2.Struct(
                        fields={
                            "command": struct_pb2.Value(string_value="pwd"),
                        }
                    ),
                ),
            )
        ],
    )

    translated = _translate_hitl_decisions(decision)

    assert translated == [
        {
            "type": "edit",
            "edited_action": {
                "name": "execute",
                "args": {"command": "pwd"},
            },
        }
    ]


def test_hitl_coordinator_routes_decision_by_interrupt_id() -> None:
    """Coordinator should resolve the waiter for the matching interrupt."""

    async def scenario() -> None:
        coordinator = _HITLDecisionCoordinator()
        wait_task = asyncio.create_task(
            coordinator.wait_for_decision(
                {
                    "interrupt_id": "interrupt-1",
                    "action_requests": [{"action": "execute"}, {"action": "write_file"}],
                }
            )
        )
        await asyncio.sleep(0)

        await coordinator.submit(
            pb2.HITLDecision(
                interrupt_id="interrupt-1",
                decisions=[
                    pb2.Decision(type="approve"),
                    pb2.Decision(type="reject", message="unsafe"),
                ],
            )
        )

        decision = await wait_task

        assert decision.interrupt_id == "interrupt-1"
        assert len(decision.decisions) == 2

    asyncio.run(scenario())


def test_hitl_coordinator_rejects_unknown_interrupt() -> None:
    """Unknown interrupt IDs should become transport-level HITL errors."""

    async def scenario() -> None:
        coordinator = _HITLDecisionCoordinator()

        await coordinator.submit(
            pb2.HITLDecision(
                interrupt_id="missing",
                decisions=[],
            )
        )

        error = await coordinator.transport_error

        assert isinstance(error, _InvalidHITLDecisionError)
        assert str(error) == "unknown interrupt_id: missing"

    asyncio.run(scenario())


def test_hitl_coordinator_rejects_closed_interrupt() -> None:
    """A second decision for the same interrupt should fail transport validation."""

    async def scenario() -> None:
        coordinator = _HITLDecisionCoordinator()
        wait_task = asyncio.create_task(
            coordinator.wait_for_decision(
                {
                    "interrupt_id": "interrupt-1",
                    "action_requests": [{"action": "execute"}],
                }
            )
        )
        await asyncio.sleep(0)

        await coordinator.submit(
            pb2.HITLDecision(
                interrupt_id="interrupt-1",
                decisions=[pb2.Decision(type="approve")],
            )
        )
        await wait_task

        await coordinator.submit(
            pb2.HITLDecision(
                interrupt_id="interrupt-1",
                decisions=[pb2.Decision(type="approve")],
            )
        )

        error = await coordinator.transport_error

        assert isinstance(error, _InvalidHITLDecisionError)
        assert str(error) == "interrupt_id interrupt-1 is no longer pending"

    asyncio.run(scenario())


def test_hitl_coordinator_rejects_decision_count_mismatch() -> None:
    """Decision count must match the interrupt action count before routing."""

    async def scenario() -> None:
        coordinator = _HITLDecisionCoordinator()
        wait_task = asyncio.create_task(
            coordinator.wait_for_decision(
                {
                    "interrupt_id": "interrupt-1",
                    "action_requests": [{"action": "execute"}, {"action": "write_file"}],
                }
            )
        )
        await asyncio.sleep(0)

        await coordinator.submit(
            pb2.HITLDecision(
                interrupt_id="interrupt-1",
                decisions=[pb2.Decision(type="approve")],
            )
        )

        error = await coordinator.transport_error

        assert isinstance(error, _InvalidHITLDecisionError)
        assert (
            str(error)
            == "decision count mismatch for interrupt interrupt-1: expected 2, got 1"
        )
        wait_task.cancel()
        with suppress(asyncio.CancelledError):
            await wait_task

    asyncio.run(scenario())


def test_run_emits_invalid_hitl_decision_error_event() -> None:
    """Run should end with a transport-specific error for invalid HITL input."""

    async def scenario() -> None:
        manager = _FakeManager()
        servicer = AgentExecutorServicer(manager)
        request_iterator = _MessageIterator(
            [
                pb2.ClientMessage(
                    hitl_decision=pb2.HITLDecision(
                        interrupt_id="interrupt-1",
                        decisions=[],
                    )
                )
            ],
            ready_event=manager.interrupt_ready,
        )
        context = _FakeContext(
            pb2.ClientMessage(
                run_request=pb2.RunRequest(
                    agent_name="demo-agent",
                    message="hello",
                    thread_id="thread-1",
                )
            )
        )

        emitted: list[pb2.AgentEvent] = []
        async for event in servicer.Run(request_iterator, context):
            emitted.append(event)

        assert [event.WhichOneof("payload") for event in emitted] == [
            "run_started",
            "hitl_request",
            "error",
        ]
        assert emitted[-1].error.error_type == "invalid_hitl_decision"
        assert (
            emitted[-1].error.message
            == "decision count mismatch for interrupt interrupt-1: expected 1, got 0"
        )

    asyncio.run(scenario())
