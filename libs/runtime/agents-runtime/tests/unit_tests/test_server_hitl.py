"""Unit tests for runtime server HITL transport hardening."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from google.protobuf import struct_pb2

from agents_runtime import events
from agents_runtime.entry.server import (
    AgentExecutorServicer,
    AgentTelemetryServicer,
    ResourceSyncServicer,
    _HITLDecisionCoordinator,
    _InvalidHITLDecisionError,
    _translate_hitl_decisions,
)
from agents_runtime.generated import runtime_pb2 as pb2
from agents_runtime.telemetry import TelemetryEvent, telemetry_from_runtime_event


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


class _FakeTelemetryManager:
    """Manager stub that emits a small telemetry stream."""

    async def invoke_telemetry(
        self,
        *,
        name: str,
        run_config: Any,
        hitl_handler: Any = None,
        cancel_event: Any = None,
        cancel_reason: str = "",
        cancel_reason_getter: Any = None,
    ):
        del hitl_handler, cancel_event, cancel_reason, cancel_reason_getter

        yield telemetry_from_runtime_event(
            events.run_start(
                run_id=run_config.run_id,
                agent_name=name,
                thread_id=run_config.thread_id,
            )
        )
        yield TelemetryEvent(
            stream_mode="messages",
            event_type="reasoning",
            payload={
                "summary": [{"type": "summary_text", "text": "thinking..."}],
            },
            ns=("task:research",),
            metadata={"langgraph_node": "planner"},
            run_id=run_config.run_id,
            agent_name=name,
        )
        yield telemetry_from_runtime_event(
            events.run_end(
                run_id=run_config.run_id,
                agent_name=name,
                stats={},
            )
        )


class _FakeGraphManager:
    """Manager stub that returns a JSON-like drawable graph."""

    async def get_agent_graph(
        self,
        name: str,
        *,
        xray_depth: int = 0,
    ) -> dict[str, Any]:
        return {
            "agent": name,
            "xray_depth": xray_depth,
            "nodes": [{"id": "model"}],
            "edges": [],
        }


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


def test_run_telemetry_emits_structured_telemetry_events() -> None:
    """RunTelemetry should stream protobuf telemetry events end-to-end."""

    async def scenario() -> None:
        manager = _FakeTelemetryManager()
        servicer = AgentTelemetryServicer(manager)
        request_iterator = _MessageIterator([])
        context = _FakeContext(
            pb2.ClientMessage(
                run_request=pb2.RunRequest(
                    agent_name="demo-agent",
                    message="hello",
                    thread_id="thread-1",
                )
            )
        )

        emitted: list[pb2.TelemetryEvent] = []
        async for event in servicer.RunTelemetry(request_iterator, context):
            emitted.append(event)

        assert [event.event_type for event in emitted] == [
            "run_started",
            "reasoning",
            "run_ended",
        ]
        assert emitted[0].HasField("public_event")
        assert emitted[0].public_event.run_started.thread_id == "thread-1"
        assert list(emitted[1].ns) == ["task:research"]
        assert emitted[1].stream_mode == "messages"
        assert emitted[1].metadata.fields["langgraph_node"].string_value == "planner"
        assert (
            emitted[1]
            .payload.struct_value.fields["summary"]
            .list_value.values[0]
            .struct_value.fields["text"]
            .string_value
            == "thinking..."
        )

    asyncio.run(scenario())


def test_resource_sync_get_agent_graph_returns_json_like_payload() -> None:
    """GetAgentGraph should return the drawable graph as a protobuf Value."""

    async def scenario() -> None:
        servicer = ResourceSyncServicer(_FakeGraphManager())
        response = await servicer.GetAgentGraph(
            pb2.GetAgentGraphRequest(agent_name="demo-agent", xray_depth=2),
            None,  # type: ignore[arg-type]
        )

        payload = response.graph.struct_value.fields
        assert payload["agent"].string_value == "demo-agent"
        assert payload["xray_depth"].number_value == 2
        assert payload["nodes"].list_value.values[0].struct_value.fields["id"].string_value == "model"

    asyncio.run(scenario())
