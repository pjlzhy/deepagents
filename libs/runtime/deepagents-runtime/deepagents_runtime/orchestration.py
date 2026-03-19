"""Core execution loop: stream agent output → RuntimeEvent.

Absorbs the execution logic from CLI non_interactive.py but yields
RuntimeEvents instead of writing to stdout.  HITL decisions are
delegated to a caller-supplied callback.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, Awaitable

from deepagents_runtime import events
from deepagents_runtime.events import RuntimeEvent
from deepagents_runtime.streams import StreamParserState, parse_stream_chunk

logger = logging.getLogger(__name__)

_MAX_HITL_ITERATIONS = 50

# Type alias for the HITL decision callback.
# Receives the validated HITLRequest dict and returns a list of decision dicts.
HITLHandler = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]


class HITLIterationLimitError(RuntimeError):
    """Raised when the HITL loop exceeds the safety cap."""


async def stream_agent(
    agent: Any,
    stream_input: dict[str, Any] | Any,
    config: dict[str, Any],
    state: StreamParserState,
    *,
    context: Any = None,
) -> AsyncIterator[RuntimeEvent]:
    """Single pass of ``agent.astream()`` → RuntimeEvent.

    Iterates over the raw LangGraph stream, parsing each chunk into
    zero or more RuntimeEvents via :func:`parse_stream_chunk`.

    Args:
        agent: Compiled LangGraph agent (``CompiledStateGraph``).
        stream_input: Input dict or ``Command(resume=...)``.
        config: ``RunnableConfig`` with ``thread_id`` in ``configurable``.
        state: Mutable parser state (accumulated across HITL rounds).
        context: Optional runtime context passed through to LangGraph.

    Yields:
        RuntimeEvent instances.
    """
    async for chunk in agent.astream(
        stream_input,
        config=config,
        context=context,
        stream_mode=["messages", "updates"],
        subgraphs=True,
    ):
        for event in parse_stream_chunk(chunk, state):
            yield event


async def run_agent_loop(
    agent: Any,
    message: str,
    *,
    config: dict[str, Any],
    context: Any = None,
    hitl_handler: HITLHandler | None = None,
    run_id: str = "",
    agent_name: str = "",
) -> AsyncIterator[RuntimeEvent]:
    """Full agent execution with HITL interrupt handling.

    This is the main entry point for running an agent to completion.
    It performs the initial stream pass, then enters a HITL loop if
    the agent emits interrupt requests.

    Args:
        agent: Compiled LangGraph agent.
        message: User message to send.
        config: ``RunnableConfig`` (must include ``configurable.thread_id``).
        context: Optional runtime context passed through to LangGraph.
        hitl_handler: Async callback that receives a HITLRequest dict and
            returns a list of decision dicts. If *None*, all interrupts
            are auto-approved.
        run_id: Unique run identifier (generated if empty).
        agent_name: Agent name for event metadata.

    Yields:
        RuntimeEvent stream covering the full execution.

    Raises:
        HITLIterationLimitError: If HITL loop exceeds safety cap.
    """
    if not run_id:
        run_id = uuid.uuid4().hex[:12]

    yield events.run_start(
        run_id=run_id,
        agent_name=agent_name,
        thread_id=config.get("configurable", {}).get("thread_id", ""),
    )

    state = StreamParserState(run_id=run_id, agent_name=agent_name)
    stream_input: dict[str, Any] | Any = {
        "messages": [{"role": "user", "content": message}],
    }

    wall_start = time.monotonic()

    # ── Initial stream pass ──
    async for evt in stream_agent(
        agent,
        stream_input,
        config,
        state,
        context=context,
    ):
        yield evt

    # ── HITL interrupt loop ──
    iteration = 0
    while state.interrupt_occurred:
        iteration += 1
        if iteration > _MAX_HITL_ITERATIONS:
            raise HITLIterationLimitError(
                f"HITL loop exceeded {_MAX_HITL_ITERATIONS} iterations"
            )

        # Collect decisions for all pending interrupts
        hitl_response: dict[str, Any] = {}
        for interrupt_id, request in state.pending_interrupts.items():
            # Emit HITL_REQUEST event (single source of truth — streams.py
            # intentionally does NOT emit this to avoid duplicates).
            action_requests = (
                request.get("action_requests", [])
                if isinstance(request, dict)
                else []
            )
            yield events.hitl_request(
                interrupt_id=interrupt_id,
                action_requests=[dict(ar) for ar in action_requests],
                run_id=run_id,
                agent_name=agent_name,
            )

            if hitl_handler is not None:
                decisions = await hitl_handler({
                    "interrupt_id": interrupt_id,
                    "action_requests": action_requests,
                })
            else:
                # Auto-approve all action requests
                decisions = [
                    {"action": ar.get("action", ""), "approved": True}
                    for ar in action_requests
                ]

            hitl_response[interrupt_id] = {"decisions": decisions}

        # Reset state for next round
        state.pending_interrupts.clear()
        state.interrupt_occurred = False

        # Resume agent with decisions
        from langgraph.types import Command

        stream_input = Command(resume=hitl_response)

        async for evt in stream_agent(
            agent,
            stream_input,
            config,
            state,
            context=context,
        ):
            yield evt

    # ── Finalize ──
    wall_time = time.monotonic() - wall_start
    state.stats.wall_time_seconds = wall_time

    full_text = "".join(state.full_response)
    if full_text:
        yield events.text_done(
            full_text, run_id=run_id, agent_name=agent_name
        )

    yield events.run_end(
        run_id=run_id,
        agent_name=agent_name,
        stats={
            "request_count": state.stats.request_count,
            "input_tokens": state.stats.input_tokens,
            "output_tokens": state.stats.output_tokens,
            "wall_time_seconds": round(wall_time, 2),
        },
    )
