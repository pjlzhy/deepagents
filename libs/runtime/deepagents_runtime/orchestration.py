"""Shared run-loop orchestration helpers."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Protocol, TypeAlias

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from langchain.agents.middleware.human_in_the_loop import HITLRequest


class StreamingAgent(Protocol):
    """Protocol for agent objects that expose `astream()`."""

    def astream(
        self,
        stream_input: object,
        *,
        stream_mode: list[str],
        subgraphs: bool,
        config: object,
        durability: str,
    ) -> AsyncIterator[object]:
        """Stream raw chunks for a single agent pass."""


class HITLState(Protocol):
    """Mutable interrupt-tracking state consumed by the run loop."""

    pending_interrupts: dict[str, HITLRequest]
    interrupt_occurred: bool


HITLDecisionPayload: TypeAlias = dict[str, str]
"""A single HITL decision payload sent back to the agent runtime."""

HITLResponsePayload: TypeAlias = dict[str, dict[str, list[HITLDecisionPayload]]]
"""Resume payload keyed by interrupt ID."""


class HITLIterationLimitError(RuntimeError):
    """Raised when the HITL loop exceeds the configured resume limit."""


async def stream_agent(
    agent: StreamingAgent,
    stream_input: object,
    config: object,
    on_chunk: Callable[[object], Awaitable[None] | None],
) -> None:
    """Consume one full agent stream pass.

    Args:
        agent: LangGraph agent-like object with an `astream()` method.
        stream_input: Initial input or resume command for the stream pass.
        config: LangGraph runnable config.
        on_chunk: Callback invoked for each emitted chunk.
    """
    async for chunk in agent.astream(
        stream_input,
        stream_mode=["messages", "updates"],
        subgraphs=True,
        config=config,
        durability="exit",
    ):
        maybe_result = on_chunk(chunk)
        if inspect.isawaitable(maybe_result):
            await maybe_result


def build_hitl_response(
    pending_interrupts: dict[str, HITLRequest],
    decision_builder: Callable[[str, HITLRequest], list[HITLDecisionPayload]],
) -> HITLResponsePayload:
    """Build a LangGraph resume payload for pending HITL interrupts.

    Args:
        pending_interrupts: Pending interrupt requests keyed by interrupt ID.
        decision_builder: Callback that returns decisions for one interrupt.

    Returns:
        Resume payload keyed by interrupt ID.
    """
    response: HITLResponsePayload = {}
    for interrupt_id, hitl_request in pending_interrupts.items():
        response[interrupt_id] = {
            "decisions": decision_builder(interrupt_id, hitl_request)
        }
    return response


async def run_agent_loop(
    agent: StreamingAgent,
    initial_input: object,
    config: object,
    on_chunk: Callable[[object], Awaitable[None] | None],
    hitl_state: HITLState,
    resolve_interrupts: Callable[
        [dict[str, HITLRequest]],
        Awaitable[HITLResponsePayload] | HITLResponsePayload,
    ],
    resume_input_factory: Callable[[HITLResponsePayload], object],
    *,
    max_hitl_iterations: int = 50,
) -> int:
    """Run an agent until completion, resuming through HITL interrupts.

    Args:
        agent: LangGraph agent-like object with an `astream()` method.
        initial_input: Input used for the initial stream pass.
        config: LangGraph runnable config.
        on_chunk: Callback invoked for every stream chunk.
        hitl_state: Mutable state with pending interrupt tracking.
        resolve_interrupts: Callback that turns pending interrupts into a
            LangGraph resume payload.
        resume_input_factory: Callback that wraps a resume payload into the
            next `astream()` input object.
        max_hitl_iterations: Maximum number of HITL resume round-trips.

    Returns:
        Number of resume iterations performed after the initial stream.

    Raises:
        HITLIterationLimitError: If the interrupt loop exceeds the limit.
    """
    await stream_agent(agent, initial_input, config, on_chunk)

    iterations = 0
    while hitl_state.interrupt_occurred:
        iterations += 1
        if iterations > max_hitl_iterations:
            msg = (
                f"Exceeded {max_hitl_iterations} HITL interrupt rounds. "
                "The agent may be stuck retrying rejected commands."
            )
            raise HITLIterationLimitError(msg)

        hitl_state.interrupt_occurred = False
        pending_interrupts = dict(hitl_state.pending_interrupts)
        hitl_state.pending_interrupts.clear()

        maybe_response = resolve_interrupts(pending_interrupts)
        if inspect.isawaitable(maybe_response):
            hitl_response = await maybe_response
        else:
            hitl_response = maybe_response

        if not hitl_response:
            break

        await stream_agent(
            agent,
            resume_input_factory(hitl_response),
            config,
            on_chunk,
        )

    return iterations
