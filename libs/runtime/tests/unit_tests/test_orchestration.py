from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from deepagents_runtime.orchestration import (
    HITLIterationLimitError,
    build_hitl_response,
    run_agent_loop,
    stream_agent,
)
from deepagents_runtime.streams import validate_hitl_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _make_hitl_request() -> object:
    return validate_hitl_request(
        {
            "action_requests": [
                {
                    "name": "execute",
                    "args": {"command": "dir"},
                    "description": "Run command",
                }
            ],
            "review_configs": [
                {
                    "action_name": "execute",
                    "allowed_decisions": ["approve", "reject"],
                }
            ],
        }
    )


class _FakeAgent:
    def __init__(self, passes: list[list[object]]) -> None:
        self._passes = passes
        self.inputs: list[object] = []

    async def astream(
        self,
        stream_input: object,
        **_: object,
    ) -> AsyncIterator[object]:
        self.inputs.append(stream_input)
        index = len(self.inputs) - 1
        for chunk in self._passes[index]:
            yield chunk


@dataclass
class _State:
    pending_interrupts: dict[str, object] = field(default_factory=dict)
    interrupt_occurred: bool = False


def test_stream_agent_forwards_all_chunks() -> None:
    async def _run() -> None:
        agent = _FakeAgent([["a", "b", "c"]])
        chunks: list[object] = []

        def on_chunk(chunk: object) -> None:
            chunks.append(chunk)

        await stream_agent(
            agent,
            {"messages": [{"role": "user", "content": "hello"}]},
            {"configurable": {"thread_id": "thread-1"}, "metadata": {}},
            on_chunk,
        )

        assert chunks == ["a", "b", "c"]
        assert len(agent.inputs) == 1

    asyncio.run(_run())


def test_build_hitl_response_maps_decisions_by_interrupt_id() -> None:
    request = _make_hitl_request()

    response = build_hitl_response(
        {"interrupt-1": request},
        lambda _interrupt_id, _request: [{"type": "approve"}],
    )

    assert response == {
        "interrupt-1": {"decisions": [{"type": "approve"}]},
    }


def test_run_agent_loop_resumes_after_interrupt() -> None:
    async def _run() -> None:
        agent = _FakeAgent([["interrupt"], ["done"]])
        state = _State()
        request = _make_hitl_request()
        handled_chunks: list[object] = []
        resume_payload = {"interrupt-1": {"decisions": [{"type": "approve"}]}}

        def on_chunk(chunk: object) -> None:
            handled_chunks.append(chunk)
            if chunk == "interrupt":
                state.pending_interrupts["interrupt-1"] = request
                state.interrupt_occurred = True

        def resolve_interrupts(
            pending_interrupts: dict[str, object],
        ) -> dict[str, dict[str, list[dict[str, str]]]]:
            assert pending_interrupts == {"interrupt-1": request}
            return resume_payload

        def resume_input_factory(
            payload: dict[str, dict[str, list[dict[str, str]]]],
        ) -> dict[str, object]:
            return {"resume": payload}

        iterations = await run_agent_loop(
            agent,
            {"messages": [{"role": "user", "content": "hello"}]},
            {"configurable": {"thread_id": "thread-1"}, "metadata": {}},
            on_chunk,
            state,
            resolve_interrupts,
            resume_input_factory,
        )

        assert iterations == 1
        assert handled_chunks == ["interrupt", "done"]
        assert agent.inputs == [
            {"messages": [{"role": "user", "content": "hello"}]},
            {"resume": resume_payload},
        ]
        assert state.pending_interrupts == {}
        assert state.interrupt_occurred is False

    asyncio.run(_run())


def test_run_agent_loop_supports_async_interrupt_resolver() -> None:
    async def _run() -> None:
        agent = _FakeAgent([["interrupt"], ["done"]])
        state = _State()
        request = _make_hitl_request()

        def on_chunk(chunk: object) -> None:
            if chunk == "interrupt":
                state.pending_interrupts["interrupt-1"] = request
                state.interrupt_occurred = True

        async def resolve_interrupts(
            pending_interrupts: dict[str, object],
        ) -> dict[str, dict[str, list[dict[str, str]]]]:
            assert pending_interrupts == {"interrupt-1": request}
            await asyncio.sleep(0)
            return {"interrupt-1": {"decisions": [{"type": "approve"}]}}

        iterations = await run_agent_loop(
            agent,
            {"messages": [{"role": "user", "content": "hello"}]},
            {"configurable": {"thread_id": "thread-1"}, "metadata": {}},
            on_chunk,
            state,
            resolve_interrupts,
            lambda payload: {"resume": payload},
        )

        assert iterations == 1

    asyncio.run(_run())


def test_run_agent_loop_raises_when_interrupt_limit_exceeded() -> None:
    async def _run() -> None:
        agent = _FakeAgent([["interrupt"], ["interrupt"], ["interrupt"]])
        state = _State()
        request = _make_hitl_request()

        def on_chunk(chunk: object) -> None:
            if chunk == "interrupt":
                state.pending_interrupts["interrupt-1"] = request
                state.interrupt_occurred = True

        with pytest.raises(
            HITLIterationLimitError,
            match="Exceeded 2 HITL interrupt",
        ):
            await run_agent_loop(
                agent,
                {"messages": [{"role": "user", "content": "hello"}]},
                {"configurable": {"thread_id": "thread-1"}, "metadata": {}},
                on_chunk,
                state,
                lambda _pending: {"interrupt-1": {"decisions": [{"type": "approve"}]}},
                lambda payload: {"resume": payload},
                max_hitl_iterations=2,
            )

    asyncio.run(_run())
