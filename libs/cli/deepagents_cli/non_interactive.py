"""Non-interactive execution mode for deepagents CLI.

Provides `run_non_interactive` which runs a single user task against the
agent graph, streams results to stdout, and exits with an appropriate code.

Shell commands are gated by an optional allow-list. When no allow-list is
set, shell is disabled and all other tool calls are auto-approved via the
`auto_approve` flag. When an allow-list is provided, shell is enabled and
all tool calls (shell and non-shell) pass through HITL, where non-shell
tools are approved unconditionally and shell commands are validated against
the list.

An optional quiet mode (`--quiet` / `-q`) redirects all console output to
stderr, leaving stdout exclusively for the agent's response text.

Note: in non-interactive mode (`-n`), auto-approval is determined solely by
whether a `--shell-allow-list` is present, not by the `--auto-approve` CLI
flag. See `run_non_interactive` for details.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from deepagents_runtime.inputs import InputEnvelope
from deepagents_runtime.orchestration import build_hitl_response
from deepagents_runtime.run_service import AgentRunConfig, stream_run_events
from deepagents_runtime.runs import SessionStats
from rich.console import Console
from rich.style import Style
from rich.text import Text

from deepagents_cli.agent import DEFAULT_AGENT_NAME, create_cli_agent
from deepagents_cli.config import (
    SHELL_TOOL_NAMES,
    build_langsmith_thread_url,
    create_model,
    is_shell_command_allowed,
    settings,
)
from deepagents_cli.file_ops import FileOpTracker
from deepagents_cli.model_config import ModelConfigError
from deepagents_cli.sessions import generate_thread_id, get_checkpointer
from deepagents_cli.textual_adapter import print_usage_table
from deepagents_cli.tools import fetch_url, http_request, web_search

if TYPE_CHECKING:
    from deepagents_runtime.events import RuntimeEvent
    from langchain.agents.middleware.human_in_the_loop import ActionRequest, HITLRequest
    from langgraph.pregel import Pregel

logger = logging.getLogger(__name__)


_MAX_HITL_ITERATIONS = 50
"""Safety cap on the number of HITL interrupt round-trips to prevent infinite
loops (e.g. when the agent keeps retrying rejected commands)."""


def _write_text(text: str) -> None:
    """Write agent response text to stdout (without a trailing newline).

    Uses `sys.stdout` directly (rather than the Rich Console) so that agent
    response text always appears on stdout, even in quiet mode where the
    Console is redirected to stderr.

    Args:
        text: The text string to write.
    """
    sys.stdout.write(text)
    sys.stdout.flush()


def _write_newline() -> None:
    """Write a newline to stdout (and flush)."""
    sys.stdout.write("\n")
    sys.stdout.flush()


@dataclass
class StreamState:
    """Mutable state accumulated while iterating over runtime events."""

    quiet: bool = False
    """When `True`, diagnostic formatting that would otherwise go to stdout
    (e.g. separator newlines before tool notifications) is suppressed so that
    stdout contains only agent response text."""

    stream: bool = True
    """When `True` (default), text chunks are written to stdout as they arrive.

    When `False`, text is buffered in `full_response` and flushed after the
    agent finishes.
    """

    full_response: list[str] = field(default_factory=list)
    """Accumulated text fragments from the AI message stream."""

    stats: SessionStats = field(default_factory=SessionStats)
    """Usage stats accumulated from runtime `usage.updated` events."""

    run_failed: bool = False
    run_cancelled: bool = False
    error_type: str | None = None
    error_message: str | None = None


@dataclass
class ThreadUrlLookupState:
    """Best-effort background LangSmith thread URL lookup state.

    Thread safety: the background thread sets `url` then calls `done.set()`.
    Consumers must check `done.is_set()` before reading `url`.
    """

    done: threading.Event = field(default_factory=threading.Event)
    url: str | None = None


def _start_langsmith_thread_url_lookup(thread_id: str) -> ThreadUrlLookupState:
    """Start background LangSmith URL resolution without blocking.

    Args:
        thread_id: Thread identifier to resolve.

    Returns:
        Mutable lookup state whose completion can be checked later.
    """
    state = ThreadUrlLookupState()

    def _resolve() -> None:
        try:
            state.url = build_langsmith_thread_url(thread_id)
        except Exception:  # build_langsmith_thread_url already handles known errors
            logger.debug(
                "Could not resolve LangSmith thread URL for '%s'",
                thread_id,
                exc_info=True,
            )
        finally:
            state.done.set()

    threading.Thread(target=_resolve, daemon=True).start()
    return state


def _consume_runtime_event(
    event: RuntimeEvent,
    state: StreamState,
    console: Console,
    file_op_tracker: FileOpTracker,
) -> None:
    """Render one runtime event for the non-interactive CLI."""
    payload = event.payload

    if event.type == "message.assistant.delta":
        text = str(payload.get("text", ""))
        if not text:
            return
        if state.stream:
            _write_text(text)
        state.full_response.append(text)
        return

    if event.type == "usage.updated":
        model_name = str(payload.get("model_name", ""))
        input_tokens = int(payload.get("input_tokens", 0) or 0)
        output_tokens = int(payload.get("output_tokens", 0) or 0)
        state.stats.record_request(model_name, input_tokens, output_tokens)
        return

    if event.type == "run.failed":
        state.run_failed = True
        state.error_type = str(payload.get("error_type", "") or "") or "RunFailed"
        state.error_message = str(payload.get("message", "") or "") or None
        return

    if event.type == "run.cancelled":
        state.run_cancelled = True
        return

    if event.type == "tool.call.started":
        tool_name = str(payload.get("tool_name", ""))
        if state.full_response and not state.quiet:
            _write_newline()
        console.print(f"[dim]🔧 Calling tool: {tool_name}[/dim]")
        args = payload.get("args", {})
        tool_call_id = payload.get("tool_call_id")
        if isinstance(args, dict) and args and tool_call_id is not None:
            file_op_tracker.start_operation(tool_name, args, str(tool_call_id))
        return

    if event.type == "tool.call.arguments":
        tool_name = str(payload.get("tool_name", ""))
        tool_call_id = payload.get("tool_call_id")
        args = payload.get("args", {})

        if isinstance(args, dict) and args:
            file_op_tracker.start_operation(
                tool_name,
                args,
                str(tool_call_id) if tool_call_id is not None else None,
            )
        return

    if event.type != "tool.call.completed":
        return

    tool_message = SimpleNamespace(
        tool_call_id=payload.get("tool_call_id"),
        content=payload.get("content"),
        status=payload.get("status", "success"),
        name=payload.get("tool_name"),
    )
    record = file_op_tracker.complete_with_message(tool_message)
    if record and record.diff:
        console.print(f"[dim]📝 {record.display_path}[/dim]")


def _make_hitl_decision(
    action_request: ActionRequest, console: Console
) -> dict[str, str]:
    """Decide whether to approve or reject a single action request.

    Shell tools are always gated: if an allow-list is configured, the command
    is validated against it; if no allow-list is configured, shell commands
    are rejected outright (defense-in-depth -- the caller should disable
    shell tools when no allow-list is present, but this function fails
    closed regardless). Non-shell tools are approved unconditionally.

    Args:
        action_request: The action-request dict emitted by the HITL middleware.

            Must contain at least a `name` key.
        console: Rich console for status output.

    Returns:
        Decision dict with a `type` key (`"approve"` or `"reject"`)
            and an optional `message` key with a human-readable explanation.
    """
    action_name = action_request.get("name", "")

    if action_name in SHELL_TOOL_NAMES:
        if not settings.shell_allow_list:
            command = action_request.get("args", {}).get("command", "")
            console.print(
                f"\n[red]Shell command rejected (no allow-list configured): "
                f"{command}[/red]"
            )
            return {
                "type": "reject",
                "message": (
                    "Shell commands are not permitted in non-interactive mode "
                    "without a --shell-allow-list. Use --shell-allow-list to "
                    "specify allowed commands."
                ),
            }

        command = action_request.get("args", {}).get("command", "")

        if is_shell_command_allowed(command, settings.shell_allow_list):
            console.print(f"[dim]✓ Auto-approved: {command}[/dim]")
            return {"type": "approve"}

        allowed_list_str = ", ".join(settings.shell_allow_list)
        console.print(f"\n[red]Shell command rejected:[/red] {command}")
        console.print(f"[yellow]Allowed commands:[/yellow] {allowed_list_str}")
        return {
            "type": "reject",
            "message": (
                f"Command '{command}' is not in the allow-list. "
                f"Allowed commands: {allowed_list_str}. "
                f"Please use allowed commands or try another approach."
            ),
        }

    console.print(f"[dim]✓ Auto-approved action: {action_name}[/dim]")
    return {"type": "approve"}


async def _run_agent_loop(
    agent: Pregel,
    message: str,
    console: Console,
    file_op_tracker: FileOpTracker,
    *,
    assistant_id: str,
    thread_id: str,
    quiet: bool = False,
    stream: bool = True,
    thread_url_lookup: ThreadUrlLookupState | None = None,
) -> int:
    """Run the agent and handle HITL interrupts until the task completes.

    Args:
        agent: The compiled LangGraph agent.
        message: The user's task message.
        console: Rich console for formatted output.
        file_op_tracker: Tracker for file-operation diffs.
        assistant_id: Agent identifier used for run metadata.
        thread_id: Thread identifier used for session storage.
        quiet: Suppress diagnostic formatting on stdout.
        stream: When `True`, text is written to stdout as it arrives.

            When `False`, the full response is buffered and flushed at
            the end.
        thread_url_lookup: Optional non-blocking lookup state for rendering
            a fast-follow LangSmith thread link.

    Returns:
        Exit code: 0 for success, 1 for error/cancellation.

    """
    state = StreamState(quiet=quiet, stream=stream)
    start_time = time.monotonic()

    envelope = InputEnvelope(thread_id=thread_id, mode="normal", text=message)

    def _resolve_approvals(
        pending_interrupts: dict[str, HITLRequest],
    ) -> dict[str, dict[str, list[dict[str, str]]]]:
        return build_hitl_response(
            pending_interrupts,
            lambda _interrupt_id, hitl_request: [
                _make_hitl_decision(action_request, console)
                for action_request in hitl_request["action_requests"]
            ],
        )

    agent_config = AgentRunConfig(
        assistant_id=assistant_id,
        model_name=settings.model_name or "",
        resolve_approvals=_resolve_approvals,
        max_hitl_iterations=_MAX_HITL_ITERATIONS,
    )

    async for event in stream_run_events(
        envelope,
        agent=agent,
        agent_config=agent_config,
    ):
        _consume_runtime_event(event, state, console, file_op_tracker)

    wall_time = time.monotonic() - start_time

    if state.full_response:
        if not state.stream:
            _write_text("".join(state.full_response))
        _write_newline()

    if state.run_failed:
        error_type = state.error_type or "RunFailed"
        error_message = state.error_message or "The agent run failed."
        console.print(f"\n[red]Error ({error_type}): {error_message}[/red]")
        if error_type == "HITLIterationLimitError":
            console.print(
                "[yellow]Hint: The agent may be repeatedly attempting commands "
                "that are not in the allow-list. Consider expanding the "
                "--shell-allow-list or adjusting the task.[/yellow]"
            )
        return 1

    if state.run_cancelled:
        console.print("\n[yellow]Run cancelled[/yellow]")
        return 1

    if not quiet:
        console.print()
        if thread_url_lookup is not None and thread_url_lookup.done.is_set():
            thread_url = thread_url_lookup.url
        else:
            thread_url = None

        if thread_url:
            link_text = Text("View in LangSmith: ", style="dim")
            link_text.append(
                thread_url,
                style=Style(dim=True, link=thread_url),
            )
            console.print(link_text)
        console.print("[green]✓ Task completed[/green]")
        print_usage_table(state.stats, wall_time, console)
    return 0


def _build_non_interactive_header(
    assistant_id: str,
    thread_id: str,
    *,
    include_thread_link: bool = False,
) -> Text:
    """Build the non-interactive mode header with model, agent, and thread info.

    By default, this function avoids LangSmith network lookups and renders the
    thread ID as plain text. Callers can opt in to hyperlink resolution.

    Args:
        assistant_id: Agent identifier.
        thread_id: Thread identifier.
        include_thread_link: Whether to resolve and render a LangSmith link for
            the thread ID.

    Returns:
        Rich Text object with the formatted header line.
    """
    default_label = " (default)" if assistant_id == DEFAULT_AGENT_NAME else ""
    parts: list[tuple[str, str | Style]] = [
        (f"Agent: {assistant_id}{default_label}", "dim"),
    ]

    if settings.model_name:
        parts.extend([(" | ", "dim"), (f"Model: {settings.model_name}", "dim")])

    parts.append((" | ", "dim"))

    thread_url = build_langsmith_thread_url(thread_id) if include_thread_link else None
    if thread_url:
        parts.extend(
            [
                ("Thread: ", "dim"),
                (thread_id, Style(dim=True, link=thread_url)),
            ]
        )
    else:
        parts.append((f"Thread: {thread_id}", "dim"))

    return Text.assemble(*parts)


async def run_non_interactive(
    message: str,
    assistant_id: str = "agent",
    model_name: str | None = None,
    model_params: dict[str, Any] | None = None,
    sandbox_type: str = "none",  # str (not None) to match argparse choices
    sandbox_id: str | None = None,
    sandbox_setup: str | None = None,
    *,
    profile_override: dict[str, Any] | None = None,
    quiet: bool = False,
    stream: bool = True,
) -> int:
    """Run a single task non-interactively and exit.

    When no `shell_allow_list` is configured, shell execution is disabled
    and all other tool calls are auto-approved (no HITL prompts). When an
    allow-list **is** provided, shell execution is enabled but gated by the
    list; commands not in the list are rejected with an error message sent
    back to the agent.

    Note: startup header rendering avoids synchronous LangSmith URL lookups.
    A background thread resolves the thread URL concurrently and the result is
    displayed after task completion if available.

    Args:
        message: The task/message to execute.
        assistant_id: Agent identifier for memory storage.
        model_name: Optional model name to use.
        model_params: Extra kwargs from `--model-params` to pass to the model.

            These override config file values.
        sandbox_type: Type of sandbox (`'none'`, `'modal'`,
            `'runloop'`, `'daytona'`, `'langsmith'`).
        sandbox_id: Optional existing sandbox ID to reuse.
        sandbox_setup: Optional path to setup script to run in the sandbox
            after creation.
        profile_override: Extra profile fields from `--profile-override`.

            Merged on top of config file profile overrides.
        quiet: When `True`, all console output (headers, status messages,
            tool notifications, HITL decisions, errors) is redirected to
            stderr so that only the agent's response text appears on stdout.
        stream: When `True` (default), text chunks are written to stdout
            as they arrive.

            When `False`, the full response is buffered and written to stdout in
            one shot after the agent finishes.

    Returns:
        Exit code: 0 for success, 1 for error, 130 for keyboard interrupt.
    """
    # stderr=True routes all console.print() to stderr; agent response text
    # uses _write_text() -> sys.stdout directly.
    console = Console(stderr=True) if quiet else Console()
    try:
        result = create_model(
            model_name,
            extra_kwargs=model_params,
            profile_overrides=profile_override,
        )
    except ModelConfigError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        return 1

    model = result.model
    result.apply_to_settings()
    thread_id = generate_thread_id()

    thread_url_lookup: ThreadUrlLookupState | None = None
    if not quiet:
        thread_url_lookup = _start_langsmith_thread_url_lookup(thread_id)
        console.print("[dim]Running task non-interactively...[/dim]")
        header = _build_non_interactive_header(assistant_id, thread_id)
        console.print(header)
        console.print()

    sandbox_backend = None
    exit_stack = contextlib.ExitStack()

    if sandbox_type != "none":
        # Conditional: sandbox_factory transitively imports provider modules
        # and SDKs — skip that cost for the common no-sandbox path.
        from deepagents_cli.integrations.sandbox_factory import (
            create_sandbox,
        )

        try:
            sandbox_cm = create_sandbox(
                sandbox_type,
                sandbox_id=sandbox_id,
                setup_script_path=sandbox_setup,
            )
            sandbox_backend = exit_stack.enter_context(sandbox_cm)
        except (ImportError, ValueError) as e:
            logger.exception("Sandbox creation failed")
            console.print(f"[red]Sandbox creation failed: {e}[/red]")
            return 1
        except NotImplementedError as e:
            logger.exception("Unsupported sandbox type %r", sandbox_type)
            console.print(
                f"[red]Sandbox type '{sandbox_type}' is not yet supported: {e}[/red]"
            )
            return 1
        except RuntimeError as e:
            logger.exception("Sandbox creation failed")
            console.print(f"[red]Sandbox creation failed: {e}[/red]")
            return 1

    try:
        async with get_checkpointer() as checkpointer:
            tools = [http_request, fetch_url]
            if settings.has_tavily:
                tools.append(web_search)

            # If an allow-list is provided, enable shell but disable
            # auto-approve so HITL can gate commands. If no allow-list, disable
            # shell entirely and auto-approve all other tools.
            enable_shell = bool(settings.shell_allow_list)
            use_auto_approve = not enable_shell

            agent, composite_backend = create_cli_agent(
                model=model,
                assistant_id=assistant_id,
                tools=tools,
                sandbox=sandbox_backend,
                sandbox_type=sandbox_type if sandbox_type != "none" else None,
                auto_approve=use_auto_approve,
                enable_shell=enable_shell,
                checkpointer=checkpointer,
            )

            file_op_tracker = FileOpTracker(
                assistant_id=assistant_id, backend=composite_backend
            )

            return await _run_agent_loop(
                agent,
                message,
                console,
                file_op_tracker,
                assistant_id=assistant_id,
                thread_id=thread_id,
                quiet=quiet,
                stream=stream,
                thread_url_lookup=thread_url_lookup,
            )

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        return 130
    except (ValueError, OSError) as e:
        logger.exception("Error during non-interactive execution")
        console.print(f"\n[red]Error: {e}[/red]")
        return 1
    except Exception as e:
        logger.exception("Unexpected error during non-interactive execution")
        console.print(f"\n[red]Unexpected error ({type(e).__name__}): {e}[/red]")
        return 1
    finally:
        try:
            exit_stack.close()
        except (OSError, RuntimeError) as cleanup_err:
            msg = "Failed to clean up resources during exit"
            logger.warning("%s: %s", msg, cleanup_err, exc_info=True)
            console.print(
                f"[yellow]Warning: Resource cleanup failed: {cleanup_err}[/yellow]"
            )
