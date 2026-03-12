"""Client-neutral run orchestration for Deep Agents runtime.

This module provides a thin, UI-agnostic "run service" layer that can power
Textual, a future FastAPI server, and a browser client.

The core contract is an async iterator of `RuntimeEvent` objects.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

from deepagents_runtime.events import RuntimeEvent, create_runtime_event
from deepagents_runtime.runs import SessionStats, build_stream_config
from deepagents_runtime.shell import format_shell_output, terminate_shell_process

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from deepagents_runtime.inputs import InputEnvelope
    from deepagents_runtime.orchestration import StreamingAgent


ApprovalResolver: TypeAlias = Callable[
    [dict[str, object]],
    Awaitable[dict[str, object]] | dict[str, object],
]
"""Callback that resolves HITL interrupts into a LangGraph resume payload."""


def generate_run_id() -> str:
    """Generate a stable run ID for correlating events.

    Returns:
        Run identifier string, for example `run_abc123`.
    """
    return f"run_{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class AgentRunConfig:
    """Configuration for `mode=normal` agent runs."""

    assistant_id: str | None = None
    model_name: str = ""
    resolve_approvals: ApprovalResolver | None = None
    max_hitl_iterations: int = 50


@dataclass(frozen=True, slots=True)
class CommandRunConfig:
    """Configuration for `mode=command` slash-command runs."""

    docs_url: str
    client_label: str = "deepagents-cli"
    client_version: str | None = None
    current_context: int = 0
    model_name: str | None = None
    context_limit: int | None = None
    conversation_line: str | None = None


@dataclass(frozen=True, slots=True)
class BashRunConfig:
    """Configuration for `mode=bash` direct shell command execution."""

    cwd: Path | None = None
    timeout_seconds: float = 60.0


def _run_event(
    event_type: str,
    *,
    run_id: str,
    thread_id: str | None,
    payload: dict[str, Any] | None = None,
) -> RuntimeEvent:
    """Create a run-scoped `RuntimeEvent` with consistent defaults.

    Args:
        event_type: Stable event type identifier.
        run_id: Run identifier to attach to the event.
        thread_id: Thread identifier to attach to the event.
        payload: Optional JSON-serializable event payload.

    Returns:
        Newly created runtime event.
    """
    return create_runtime_event(
        event_type,
        payload=payload or {},
        run_id=run_id,
        thread_id=thread_id,
    )


async def _maybe_await(value: object) -> object:
    """Await a value when it is awaitable (otherwise return it).

    Args:
        value: Value that may be awaitable.

    Returns:
        Awaited result when `value` is awaitable, otherwise `value` unchanged.
    """
    if inspect.isawaitable(value):
        return await value
    return value


def _namespace_key(value: object) -> tuple[str, ...]:
    """Build a stable hashable key for a namespace payload.

    Args:
        value: Namespace payload value (typically a JSON-like list).

    Returns:
        Hashable namespace key suitable for use in sets and dicts.
    """
    if isinstance(value, list):
        return tuple(repr(item) for item in value)
    return (repr(value),)


def _format_file_attachments_section(file_attachments: list[tuple[str, bool]]) -> str:
    if not file_attachments:
        return ""

    lines = ["## Attachments"]
    for path, inject in file_attachments:
        suffix = " (inject=True)" if inject else ""
        lines.append(f"- {path}{suffix}")
    return "\n".join(lines)


def _build_agent_input_from_envelope(
    envelope: InputEnvelope, *, user_message_content: object | None
) -> object:
    if user_message_content is not None:
        return user_message_content

    if not envelope.attachments:
        return envelope.text

    file_attachments: list[tuple[str, bool]] = []
    image_urls: list[str] = []
    for attachment in envelope.attachments:
        if not isinstance(attachment, dict):
            continue
        kind = attachment.get("kind")
        if kind == "image":
            data_url = attachment.get("data_url")
            if isinstance(data_url, str) and data_url:
                image_urls.append(data_url)
        elif kind == "file":
            path = attachment.get("path")
            if isinstance(path, str) and path:
                raw_inject = attachment.get("inject", False)
                inject = raw_inject if isinstance(raw_inject, bool) else False
                file_attachments.append((path, inject))

    message_text = envelope.text
    file_section = _format_file_attachments_section(file_attachments)
    if file_section:
        if message_text.strip():
            message_text = f"{message_text.rstrip()}\n\n{file_section}"
        else:
            message_text = file_section

    if not image_urls:
        return message_text

    blocks: list[dict[str, object]] = []
    if message_text.strip():
        blocks.append({"type": "text", "text": message_text})
    blocks.extend(
        {"type": "image_url", "image_url": {"url": url}} for url in image_urls
    )
    return blocks


def _serialize_hitl_request(request: object) -> dict[str, Any]:
    """Serialize a HITL request into JSON-friendly payload data.

    Args:
        request: Validated HITL request object.

    Returns:
        JSON-friendly representation of the request.
    """
    if isinstance(request, dict):
        return {str(key): _json_safe_value(value) for key, value in request.items()}

    model_dump = getattr(request, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict):
            return {str(key): _json_safe_value(value) for key, value in dumped.items()}
    as_dict = getattr(request, "dict", None)
    if callable(as_dict):
        dumped = as_dict()
        if isinstance(dumped, dict):
            return {str(key): _json_safe_value(value) for key, value in dumped.items()}
    return {"repr": repr(request)}


def _json_safe_value(value: object) -> Any:  # noqa: ANN401
    """Convert arbitrary values into JSON-friendly payload data.

    Returns:
        JSON-serializable representation of `value`.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]
    return str(value)


async def _stream_agent_pass(
    agent: StreamingAgent,
    stream_input: object,
    config: object,
    state: object,
    *,
    run_id: str,
    thread_id: str,
    assistant_started_namespaces: set[tuple[Any, ...]],
) -> AsyncIterator[RuntimeEvent]:
    """Stream one agent pass and translate chunks into runtime events.

    Yields:
        Runtime events derived from the underlying agent stream.
    """
    from deepagents_runtime.event_stream import (
        MalformedInterruptError,
        finalize_runtime_stream_pass,
        process_runtime_stream_chunk,
    )

    async for chunk in agent.astream(
        stream_input,
        stream_mode=["messages", "updates"],
        subgraphs=True,
        config=config,
        durability="exit",
    ):
        try:
            events = process_runtime_stream_chunk(chunk, state)  # type: ignore[arg-type]
        except MalformedInterruptError as error:
            payload = {
                "error_type": "MalformedInterruptError",
                "interrupt_id": error.interrupt_id,
                "message": str(error),
            }
            yield _run_event(
                "run.failed",
                run_id=run_id,
                thread_id=thread_id,
                payload=payload,
            )
            return

        for event in events:
            for expanded_event in _expand_runtime_event(
                event,
                run_id=run_id,
                thread_id=thread_id,
                assistant_started_namespaces=assistant_started_namespaces,
            ):
                yield expanded_event

    for event in finalize_runtime_stream_pass(state):  # type: ignore[arg-type]
        for expanded_event in _expand_runtime_event(
            event,
            run_id=run_id,
            thread_id=thread_id,
            assistant_started_namespaces=assistant_started_namespaces,
        ):
            yield expanded_event


def _expand_runtime_event(
    event: RuntimeEvent,
    *,
    run_id: str,
    thread_id: str,
    assistant_started_namespaces: set[tuple[Any, ...]],
) -> list[RuntimeEvent]:
    """Expand low-level runtime events into required protocol events.

    This keeps backward-compatible event names emitted by `event_stream` while
    also emitting higher-level protocol events documented in the architecture
    spec (for example `message.assistant.started`).

    Returns:
        Event list containing the original event and any derived protocol events.
    """
    expanded: list[RuntimeEvent] = []

    payload = event.payload

    if event.type == "message.assistant.delta":
        namespace = payload.get("namespace", [])
        namespace_key = _namespace_key(namespace)
        if namespace_key not in assistant_started_namespaces:
            assistant_started_namespaces.add(namespace_key)
            expanded.append(
                _run_event(
                    "message.assistant.started",
                    run_id=run_id,
                    thread_id=thread_id,
                    payload={
                        "namespace": namespace if isinstance(namespace, list) else [],
                    },
                )
            )
        expanded.append(event)
        return expanded

    if event.type == "message.assistant.completed":
        namespace = payload.get("namespace", [])
        namespace_key = _namespace_key(namespace)
        assistant_started_namespaces.discard(namespace_key)
        expanded.append(event)
        return expanded

    if event.type == "run.usage":
        expanded.extend(
            [
                event,
                _run_event(
                    "usage.updated",
                    run_id=run_id,
                    thread_id=thread_id,
                    payload=dict(payload),
                ),
            ]
        )
        return expanded

    if event.type == "tool.call.started":
        expanded.extend(
            [
                _run_event(
                    "tool.started",
                    run_id=run_id,
                    thread_id=thread_id,
                    payload={
                        "namespace": payload.get("namespace"),
                        "tool_call_id": payload.get("tool_call_id"),
                        "tool_name": payload.get("tool_name"),
                        "args": payload.get("args"),
                    },
                ),
                event,
            ]
        )
        return expanded

    if event.type == "tool.call.completed":
        tool_payload = {
            "namespace": payload.get("namespace"),
            "tool_call_id": payload.get("tool_call_id"),
            "tool_name": payload.get("tool_name"),
            "status": payload.get("status"),
            "content": payload.get("content"),
        }
        status = str(payload.get("status") or "success")
        expanded.extend(
            [
                _run_event(
                    "tool.output",
                    run_id=run_id,
                    thread_id=thread_id,
                    payload=tool_payload,
                ),
                _run_event(
                    "tool.completed" if status == "success" else "tool.failed",
                    run_id=run_id,
                    thread_id=thread_id,
                    payload={
                        "namespace": payload.get("namespace"),
                        "tool_call_id": payload.get("tool_call_id"),
                        "tool_name": payload.get("tool_name"),
                        "status": payload.get("status"),
                    },
                ),
                event,
            ]
        )
        return expanded

    expanded.append(event)
    return expanded


async def _stream_agent_turn(
    agent: StreamingAgent,
    message: object,
    *,
    run_id: str,
    thread_id: str,
    assistant_id: str | None,
    model_name: str,
    resolve_approvals: ApprovalResolver | None,
    max_hitl_iterations: int,
    stats: SessionStats,
) -> AsyncIterator[RuntimeEvent]:
    """Run one user message through the agent, handling HITL resumes.

    Yields:
        Runtime events produced by the agent pass, tool calls, and approval
        lifecycle.

    Raises:
        HITLIterationLimitError: If the interrupt loop exceeds the configured
            resume limit.
    """
    from deepagents_runtime.event_stream import RuntimeEventStreamState
    from deepagents_runtime.orchestration import HITLIterationLimitError

    config = build_stream_config(thread_id, assistant_id)
    state = RuntimeEventStreamState(
        model_name=model_name,
        run_id=run_id,
        thread_id=thread_id,
        stats=stats,
    )

    assistant_started_namespaces: set[tuple[Any, ...]] = set()

    initial_input = {"messages": [{"role": "user", "content": message}]}
    for_event = _stream_agent_pass(  # Keep explicit loop for readability
        agent,
        initial_input,
        config,
        state,
        run_id=run_id,
        thread_id=thread_id,
        assistant_started_namespaces=assistant_started_namespaces,
    )
    async for event in for_event:
        yield event

    iterations = 0
    while state.interrupt_occurred:
        iterations += 1
        if iterations > max_hitl_iterations:
            msg = (
                f"Exceeded {max_hitl_iterations} HITL interrupt rounds. "
                "The agent may be stuck retrying rejected commands."
            )
            raise HITLIterationLimitError(msg)

        state.interrupt_occurred = False
        pending_interrupts = dict(state.pending_interrupts)
        state.pending_interrupts.clear()

        serialized_interrupts = {
            interrupt_id: _serialize_hitl_request(hitl_request)
            for interrupt_id, hitl_request in pending_interrupts.items()
        }
        yield _run_event(
            "approval.requested",
            run_id=run_id,
            thread_id=thread_id,
            payload={
                "interrupt_ids": sorted(serialized_interrupts),
                "interrupts": serialized_interrupts,
            },
        )

        if resolve_approvals is None:
            yield _run_event(
                "run.failed",
                run_id=run_id,
                thread_id=thread_id,
                payload={
                    "error_type": "MissingApprovalResolver",
                    "message": "No approval resolver configured for HITL interrupts.",
                },
            )
            return

        raw_response = await _maybe_await(resolve_approvals(pending_interrupts))
        if not isinstance(raw_response, dict):
            yield _run_event(
                "run.failed",
                run_id=run_id,
                thread_id=thread_id,
                payload={
                    "error_type": "InvalidApprovalResponse",
                    "message": "Approval resolver returned a non-dict payload.",
                },
            )
            return

        hitl_response: dict[str, object] = raw_response
        yield _run_event(
            "approval.resolved",
            run_id=run_id,
            thread_id=thread_id,
            payload={
                "interrupt_ids": sorted(pending_interrupts),
                "decision_payload": hitl_response,
            },
        )

        if not hitl_response:
            yield _run_event(
                "run.cancelled",
                run_id=run_id,
                thread_id=thread_id,
                payload={"reason": "approval_rejected"},
            )
            return

        from langgraph.types import Command

        for_event = _stream_agent_pass(
            agent,
            Command(resume=hitl_response),
            config,
            state,
            run_id=run_id,
            thread_id=thread_id,
            assistant_started_namespaces=assistant_started_namespaces,
        )
        async for event in for_event:
            yield event


async def _stream_command_events(
    envelope: InputEnvelope,
    *,
    agent: StreamingAgent | None,
    run_id: str,
    agent_config: AgentRunConfig | None,
    command_config: CommandRunConfig,
    start_time: float,
) -> AsyncIterator[RuntimeEvent]:
    from deepagents_runtime.commands import (
        ClearConversationAction,
        ClearDefaultModelAction,
        CompactThreadAction,
        ExitAction,
        OpenUrlAction,
        SetDefaultModelAction,
        SetThreadAction,
        ShowMessageAction,
        ShowModelSelectorAction,
        ShowThreadSelectorAction,
        SubmitUserMessageAction,
        SwitchModelAction,
        execute_parsed_slash_command_async,
        parse_slash_command,
    )

    stats = SessionStats()
    thread_id = envelope.thread_id

    yield _run_event(
        "run.started",
        run_id=run_id,
        thread_id=thread_id,
        payload={"mode": "command"},
    )

    parsed = parse_slash_command(envelope.text)
    execution = await execute_parsed_slash_command_async(
        parsed,
        docs_url=command_config.docs_url,
        thread_id=thread_id,
        client_label=command_config.client_label,
        client_version=command_config.client_version,
        current_context=command_config.current_context,
        model_name=command_config.model_name,
        context_limit=command_config.context_limit,
        conversation_line=command_config.conversation_line,
    )

    if execution is None:
        yield _run_event(
            "command.result",
            run_id=run_id,
            thread_id=thread_id,
            payload={
                "message": f"Unhandled command: {parsed.normalized}",
                "style": None,
            },
        )
        yield _run_event(
            "run.completed",
            run_id=run_id,
            thread_id=thread_id,
            payload={"mode": "command"},
        )
        return

    if execution.echo_command:
        yield _run_event(
            "message.user.created",
            run_id=run_id,
            thread_id=thread_id,
            payload={"text": parsed.command, "attachment_count": 0},
        )

    current_thread_id = thread_id
    cleared = False

    for action in execution.actions:
        if isinstance(action, ExitAction):
            yield _run_event(
                "run.completed",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"mode": "command", "exit": True},
            )
            return

        if isinstance(action, ClearConversationAction):
            cleared = True
            yield _run_event(
                "thread.updated",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"cleared": True},
            )
            continue

        if isinstance(action, SetThreadAction):
            current_thread_id = action.thread_id
            if cleared:
                cleared = False
                yield _run_event(
                    "thread.created",
                    run_id=run_id,
                    thread_id=current_thread_id,
                    payload={"thread_id": current_thread_id},
                )
            yield _run_event(
                "thread.switched",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"thread_id": current_thread_id},
            )
            continue

        if isinstance(action, OpenUrlAction):
            yield _run_event(
                "command.open_url",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"url": action.url},
            )
            continue

        if isinstance(action, ShowMessageAction):
            yield _run_event(
                "command.result",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={
                    "message": action.message,
                    "style": action.style,
                    "link_url": action.link_url,
                },
            )
            continue

        if isinstance(action, ShowThreadSelectorAction):
            yield _run_event(
                "command.result",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"action": "show_thread_selector"},
            )
            continue

        if isinstance(action, ShowModelSelectorAction):
            yield _run_event(
                "command.result",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"action": "show_model_selector"},
            )
            continue

        if isinstance(action, CompactThreadAction):
            yield _run_event(
                "command.result",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"action": "compact_thread"},
            )
            continue

        if isinstance(action, SwitchModelAction):
            yield _run_event(
                "command.result",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"action": "switch_model", "model_spec": action.model_spec},
            )
            continue

        if isinstance(action, SetDefaultModelAction):
            yield _run_event(
                "command.result",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={
                    "action": "set_default_model",
                    "model_spec": action.model_spec,
                },
            )
            continue

        if isinstance(action, ClearDefaultModelAction):
            yield _run_event(
                "command.result",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"action": "clear_default_model"},
            )
            continue

        if isinstance(action, SubmitUserMessageAction):
            if agent is None or agent_config is None:
                yield _run_event(
                    "command.result",
                    run_id=run_id,
                    thread_id=current_thread_id,
                    payload={
                        "action": "submit_user_message",
                        "message": action.message,
                    },
                )
                continue

            yield _run_event(
                "message.user.created",
                run_id=run_id,
                thread_id=current_thread_id,
                payload={"text": action.message, "attachment_count": 0},
            )

            try:
                async for event in _stream_agent_turn(
                    agent,
                    action.message,
                    run_id=run_id,
                    thread_id=current_thread_id,
                    assistant_id=agent_config.assistant_id,
                    model_name=agent_config.model_name,
                    resolve_approvals=agent_config.resolve_approvals,
                    max_hitl_iterations=agent_config.max_hitl_iterations,
                    stats=stats,
                ):
                    yield event
                    if event.type in {"run.failed", "run.cancelled"}:
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                yield _run_event(
                    "run.failed",
                    run_id=run_id,
                    thread_id=current_thread_id,
                    payload={"error_type": type(exc).__name__, "message": str(exc)},
                )
                return

            continue

    wall_time = time.monotonic() - start_time
    stats.wall_time_seconds += wall_time
    yield _run_event(
        "run.completed",
        run_id=run_id,
        thread_id=current_thread_id,
        payload={"mode": "command", "wall_time_seconds": stats.wall_time_seconds},
    )


async def stream_run_events(
    envelope: InputEnvelope,
    *,
    agent: StreamingAgent | None = None,
    run_id: str | None = None,
    agent_config: AgentRunConfig | None = None,
    command_config: CommandRunConfig | None = None,
    bash_config: BashRunConfig | None = None,
    user_message_content: object | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Stream runtime events for one input envelope.

    Args:
        envelope: Normalized input envelope from a client.
        agent: Agent graph with an `astream()` method (required for `normal`,
            optional for `command` when it triggers `SubmitUserMessageAction`).
        run_id: Optional explicit run identifier.
        agent_config: Agent run configuration (required for `normal`).
        command_config: Command run configuration (required for `command`).
        bash_config: Bash run configuration (optional for `bash`).
        user_message_content: Optional override for the user message content
            passed to the agent for `mode=normal`. This is primarily useful for
            multimodal clients (for example passing a list of LangChain content
            blocks containing text plus images). When unset, the agent receives
            `envelope.text` as a plain string unless `envelope.attachments` are
            provided.

    Yields:
        Runtime events representing progress and output.

    Raises:
        asyncio.CancelledError: If the caller cancels the run.
    """
    resolved_run_id = run_id or generate_run_id()
    mode = envelope.mode
    thread_id = envelope.thread_id

    start_time = time.monotonic()

    if mode == "normal":
        if agent is None or agent_config is None:
            yield _run_event(
                "run.failed",
                run_id=resolved_run_id,
                thread_id=thread_id,
                payload={
                    "error_type": "MissingAgent",
                    "message": "mode=normal requires an agent and AgentRunConfig.",
                },
            )
            return

        stats = SessionStats()
        yield _run_event(
            "run.started",
            run_id=resolved_run_id,
            thread_id=thread_id,
            payload={"mode": mode},
        )
        yield _run_event(
            "message.user.created",
            run_id=resolved_run_id,
            thread_id=thread_id,
            payload={
                "text": envelope.text,
                "attachment_count": len(envelope.attachments),
            },
        )

        agent_input = _build_agent_input_from_envelope(
            envelope, user_message_content=user_message_content
        )

        try:
            async for event in _stream_agent_turn(
                agent,
                agent_input,
                run_id=resolved_run_id,
                thread_id=thread_id,
                assistant_id=agent_config.assistant_id,
                model_name=agent_config.model_name,
                resolve_approvals=agent_config.resolve_approvals,
                max_hitl_iterations=agent_config.max_hitl_iterations,
                stats=stats,
            ):
                yield event
                if event.type in {"run.failed", "run.cancelled"}:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  # Convert unexpected failures to events
            yield _run_event(
                "run.failed",
                run_id=resolved_run_id,
                thread_id=thread_id,
                payload={"error_type": type(exc).__name__, "message": str(exc)},
            )
            return

        wall_time = time.monotonic() - start_time
        stats.wall_time_seconds += wall_time
        yield _run_event(
            "run.completed",
            run_id=resolved_run_id,
            thread_id=thread_id,
            payload={
                "mode": mode,
                "request_count": stats.request_count,
                "input_tokens": stats.input_tokens,
                "output_tokens": stats.output_tokens,
                "wall_time_seconds": stats.wall_time_seconds,
            },
        )
        return

    if mode == "command":
        if command_config is None:
            yield _run_event(
                "run.failed",
                run_id=resolved_run_id,
                thread_id=thread_id,
                payload={
                    "error_type": "MissingCommandConfig",
                    "message": "mode=command requires CommandRunConfig.",
                },
            )
            return

        async for event in _stream_command_events(
            envelope,
            agent=agent,
            run_id=resolved_run_id,
            agent_config=agent_config,
            command_config=command_config,
            start_time=start_time,
        ):
            yield event
        return

    if mode == "bash":
        bash_cfg = bash_config or BashRunConfig()
        command = envelope.text

        yield _run_event(
            "run.started",
            run_id=resolved_run_id,
            thread_id=thread_id,
            payload={"mode": mode},
        )
        yield _run_event(
            "message.user.created",
            run_id=resolved_run_id,
            thread_id=thread_id,
            payload={"text": f"!{command}", "attachment_count": 0},
        )
        yield _run_event(
            "bash.started",
            run_id=resolved_run_id,
            thread_id=thread_id,
            payload={
                "command": command,
                "cwd": str(bash_cfg.cwd) if bash_cfg.cwd is not None else None,
            },
        )

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=bash_cfg.cwd,
                start_new_session=(sys.platform != "win32"),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=bash_cfg.timeout_seconds,
                )
            except TimeoutError:
                await terminate_shell_process(proc, platform=sys.platform)
                yield _run_event(
                    "bash.failed",
                    run_id=resolved_run_id,
                    thread_id=thread_id,
                    payload={
                        "command": command,
                        "reason": "timeout",
                        "timeout_seconds": bash_cfg.timeout_seconds,
                    },
                )
                yield _run_event(
                    "run.failed",
                    run_id=resolved_run_id,
                    thread_id=thread_id,
                    payload={
                        "error_type": "BashTimeout",
                        "message": (
                            f"Command timed out ({bash_cfg.timeout_seconds}s limit)."
                        ),
                    },
                )
                return
            except asyncio.CancelledError:
                await terminate_shell_process(proc, platform=sys.platform)
                raise

            output = format_shell_output(stdout_bytes, stderr_bytes)
            if output:
                yield _run_event(
                    "bash.output",
                    run_id=resolved_run_id,
                    thread_id=thread_id,
                    payload={"command": command, "output": output},
                )

            exit_code = proc.returncode or 0
            if exit_code != 0:
                yield _run_event(
                    "bash.failed",
                    run_id=resolved_run_id,
                    thread_id=thread_id,
                    payload={"command": command, "exit_code": exit_code},
                )
                yield _run_event(
                    "run.failed",
                    run_id=resolved_run_id,
                    thread_id=thread_id,
                    payload={
                        "error_type": "BashExitCode",
                        "message": f"Exit code: {exit_code}",
                        "exit_code": exit_code,
                    },
                )
                return

            yield _run_event(
                "bash.completed",
                run_id=resolved_run_id,
                thread_id=thread_id,
                payload={"command": command, "exit_code": exit_code},
            )
            yield _run_event(
                "run.completed",
                run_id=resolved_run_id,
                thread_id=thread_id,
                payload={"mode": mode},
            )

        except OSError as exc:
            yield _run_event(
                "bash.failed",
                run_id=resolved_run_id,
                thread_id=thread_id,
                payload={"command": command, "reason": "os_error", "message": str(exc)},
            )
            yield _run_event(
                "run.failed",
                run_id=resolved_run_id,
                thread_id=thread_id,
                payload={"error_type": type(exc).__name__, "message": str(exc)},
            )
            return
        else:
            return
        finally:
            if proc is not None:
                await terminate_shell_process(proc, platform=sys.platform)

    yield _run_event(
        "run.failed",
        run_id=resolved_run_id,
        thread_id=thread_id,
        payload={"error_type": "UnknownMode", "message": f"Unsupported mode: {mode}"},
    )


__all__ = [
    "AgentRunConfig",
    "ApprovalResolver",
    "BashRunConfig",
    "CommandRunConfig",
    "generate_run_id",
    "stream_run_events",
]
