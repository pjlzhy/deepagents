"""Textual UI adapter for agent execution."""
# This module has complex streaming logic ported from execution.py

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from deepagents_runtime.events import RuntimeEvent
    from langchain.agents.middleware.human_in_the_loop import HITLRequest
    from rich.console import Console

from deepagents_runtime.approvals import (
    HITLDecisionPayload,
    normalize_batch_approval_choice,
    resolve_batch_approval_choice,
)
from deepagents_runtime.inputs import InputEnvelope
from deepagents_runtime.run_service import AgentRunConfig, stream_run_events
from deepagents_runtime.runs import (
    ModelStats as _ModelStats,
    SessionStats,
    build_stream_config,
    format_token_count,
    is_summarization_chunk,
)
from langchain_core.messages import AIMessage, HumanMessage

from deepagents_cli.config import settings
from deepagents_cli.file_ops import FileOpTracker
from deepagents_cli.input import MediaTracker, parse_file_mentions
from deepagents_cli.media_utils import create_multimodal_content
from deepagents_cli.tool_display import format_tool_message_content
from deepagents_cli.widgets.messages import (
    AppMessage,
    AssistantMessage,
    DiffMessage,
    ErrorMessage,
    SummarizationMessage,
    ToolCallMessage,
)

logger = logging.getLogger(__name__)
ModelStats = _ModelStats
_build_stream_config = build_stream_config
_is_summarization_chunk = is_summarization_chunk


def print_usage_table(
    stats: SessionStats,
    wall_time: float,
    console: Console,
) -> None:
    """Print a model-usage stats table to a Rich console.

    When the session spans multiple models each gets its own row with a
    totals row appended; single-model sessions show one row.

    Args:
        stats: Cumulative session stats.
        wall_time: Total wall-clock time in seconds.
        console: Rich console for output.
    """
    from rich.table import Table

    has_time = wall_time >= 0.1  # noqa: PLR2004
    if not (stats.request_count or stats.input_tokens or has_time):
        return

    if stats.per_model:
        multi_model = len(stats.per_model) > 1

        table = Table(
            show_header=True,
            header_style="bold",
            box=None,
            padding=(0, 2, 0, 0),
            show_edge=False,
        )
        table.add_column("Model", style="dim")
        table.add_column("Reqs", justify="right", style="dim")
        table.add_column("InputTok", justify="right", style="dim")
        table.add_column("OutputTok", justify="right", style="dim")

        if multi_model:
            for model_name, ms in stats.per_model.items():
                table.add_row(
                    model_name,
                    str(ms.request_count),
                    format_token_count(ms.input_tokens),
                    format_token_count(ms.output_tokens),
                )
            table.add_row(
                "Total",
                str(stats.request_count),
                format_token_count(stats.input_tokens),
                format_token_count(stats.output_tokens),
            )
        else:
            model_label = next(iter(stats.per_model))
            table.add_row(
                model_label,
                str(stats.request_count),
                format_token_count(stats.input_tokens),
                format_token_count(stats.output_tokens),
            )

        console.print()
        console.print("[bold]Usage Stats[/bold]")
        console.print(table)
    if has_time:
        console.print()
        console.print(f"[dim]Agent active  {wall_time:.1f}s[/dim]")


# Type alias matching LangGraph resume payload decision elements.
HITLDecision = HITLDecisionPayload


class TextualUIAdapter:
    """Adapter for rendering agent output to Textual widgets.

    This adapter provides an abstraction layer between the agent execution and the
    Textual UI, allowing streaming output to be rendered as widgets.
    """

    _mount_message: Callable[..., Awaitable[None]]
    """Async callback to mount a message widget to the chat."""

    _update_status: Callable[[str], None]
    """Callback to update the status bar text."""

    _request_approval: Callable[..., Awaitable[Any]]
    """Async callback that returns a Future for HITL approval."""

    _on_auto_approve_enabled: Callable[[], None] | None
    """Callback invoked when auto-approve is enabled via the HITL approval menu.

    Fired when the user selects "Auto-approve all" from an approval dialog,
    allowing the app to sync its status bar and session state.
    """

    _scroll_to_bottom: Callable[[], None] | None
    """Callback to scroll chat to bottom."""

    _set_spinner: Callable[[str | None], Awaitable[None]] | None
    """Callback to show/hide loading spinner.

    Pass `None` to hide, or a status string to show.
    """

    _set_active_message: Callable[[str | None], None] | None
    """Callback to set the active streaming message ID (pass `None` to clear)."""

    _sync_message_content: Callable[[str, str], None] | None
    """Callback to sync final message content back to the store after streaming."""

    _sync_tool_args: Callable[[str, dict[str, Any]], None] | None
    """Callback to sync tool arguments back to the store after hydration."""

    _current_tool_messages: dict[str, ToolCallMessage]
    """Map of tool call IDs to their message widgets."""

    _token_tracker: Any
    """Token usage tracker for displaying counts."""

    def __init__(
        self,
        mount_message: Callable[..., Awaitable[None]],
        update_status: Callable[[str], None],
        request_approval: Callable[..., Awaitable[Any]],
        on_auto_approve_enabled: Callable[[], None] | None = None,
        scroll_to_bottom: Callable[[], None] | None = None,
        set_spinner: Callable[[str | None], Awaitable[None]] | None = None,
        set_active_message: Callable[[str | None], None] | None = None,
        sync_message_content: Callable[[str, str], None] | None = None,
        sync_tool_args: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            mount_message: Async callable to mount a message widget.
            update_status: Callable to update the status bar message.
            request_approval: Async callable that returns a Future for HITL approval.
            on_auto_approve_enabled: Callback fired when the user selects
                "Auto-approve all" from an approval dialog.

                Used by the app to sync the status bar indicator and session state.
            scroll_to_bottom: Callback to scroll chat to bottom.
            set_spinner: Callback to show/hide loading spinner (pass `None` to hide).
            set_active_message: Callback to set the active streaming message ID.
            sync_message_content: Callback to sync final content back to the
                message store after streaming completes.
            sync_tool_args: Callback to sync late-arriving tool arguments back
                to the message store after the widget is mounted.
        """
        self._mount_message = mount_message
        self._update_status = update_status
        self._request_approval = request_approval
        self._on_auto_approve_enabled = on_auto_approve_enabled
        self._scroll_to_bottom = scroll_to_bottom
        self._set_spinner = set_spinner
        self._set_active_message = set_active_message
        self._sync_message_content = sync_message_content
        self._sync_tool_args = sync_tool_args

        # State tracking
        self._current_tool_messages: dict[str, ToolCallMessage] = {}
        self._token_tracker: Any = None

    def set_token_tracker(self, tracker: Any) -> None:  # noqa: ANN401  # Dynamic tracker type from Textual
        """Set the token tracker for usage tracking."""
        self._token_tracker = tracker

    def finalize_pending_tools_with_error(self, error: str) -> None:
        """Mark all pending/running tool widgets as error and clear tracking.

        This is used as a safety net when an unexpected exception aborts
        streaming before matching `ToolMessage` results are received.

        Args:
            error: Error text to display in each pending tool widget.
        """
        for tool_msg in list(self._current_tool_messages.values()):
            tool_msg.set_error(error)
        self._current_tool_messages.clear()

        # Clear active streaming message to avoid stale "active" state in the store.
        if self._set_active_message:
            self._set_active_message(None)


def _build_interrupted_ai_message(
    pending_text_by_namespace: dict[tuple, str],
    current_tool_messages: dict[str, Any],
) -> AIMessage | None:
    """Build an AIMessage capturing interrupted state (text + tool calls).

    Args:
        pending_text_by_namespace: Dict of accumulated text by namespace
        current_tool_messages: Dict of tool_id -> ToolCallMessage widget

    Returns:
        AIMessage with accumulated content and tool calls, or None if empty.
    """
    main_ns_key = ()
    accumulated_text = pending_text_by_namespace.get(main_ns_key, "").strip()

    # Reconstruct tool_calls from displayed tool messages
    tool_calls = []
    for tool_id, tool_widget in list(current_tool_messages.items()):
        tool_calls.append(
            {
                "id": tool_id,
                "name": tool_widget._tool_name,
                "args": tool_widget._args,
            }
        )

    if not accumulated_text and not tool_calls:
        return None

    return AIMessage(
        content=accumulated_text,
        tool_calls=tool_calls or [],
    )


def _set_pending_tools_running(adapter: TextualUIAdapter) -> None:
    """Mark all currently displayed tool widgets as running."""
    for tool_msg in list(adapter._current_tool_messages.values()):
        tool_msg.set_running()


def _reject_pending_tools(adapter: TextualUIAdapter) -> None:
    """Reject and clear all currently displayed tool widgets."""
    for tool_msg in list(adapter._current_tool_messages.values()):
        tool_msg.set_rejected()
    adapter._current_tool_messages.clear()


def _mark_hitl_approved_file_ops(
    file_op_tracker: FileOpTracker,
    action_requests: list[dict[str, Any]],
) -> None:
    """Record HITL approval for file-writing actions."""
    for action_request in action_requests:
        tool_name = action_request.get("name")
        if tool_name not in {"write_file", "edit_file"}:
            continue
        args = action_request.get("args", {})
        if isinstance(args, dict):
            file_op_tracker.mark_hitl_approved(tool_name, args)


async def _resolve_textual_hitl_responses(
    pending_interrupts: dict[str, HITLRequest],
    *,
    adapter: TextualUIAdapter,
    assistant_id: str | None,
    session_state: Any,  # noqa: ANN401  # Session state carries dynamic auto_approve flag
    file_op_tracker: FileOpTracker,
) -> tuple[dict[str, dict[str, list[HITLDecision]]], bool]:
    """Resolve Textual batch approvals for one interrupt round.

    Args:
        pending_interrupts: Pending interrupt requests keyed by interrupt ID.
        adapter: Textual adapter used to request approval and update widgets.
        assistant_id: Agent identifier for the approval dialog.
        session_state: Session state carrying the `auto_approve` flag.
        file_op_tracker: File operation tracker to mark approved writes.

    Returns:
        Tuple of `(hitl_response, suppressed_output)` where `suppressed_output`
        indicates the run should stop after showing the rejection message.
    """
    hitl_response: dict[str, dict[str, list[HITLDecision]]] = {}
    any_rejected = False

    for interrupt_id, hitl_request in list(pending_interrupts.items()):
        action_requests = hitl_request["action_requests"]

        if session_state.auto_approve:
            resolution = resolve_batch_approval_choice(
                len(action_requests),
                None,
                auto_approve=True,
            )
            _set_pending_tools_running(adapter)
        else:
            future = await adapter._request_approval(action_requests, assistant_id)
            decision = await future

            choice = normalize_batch_approval_choice(decision)
            if choice is None:
                if isinstance(decision, dict):
                    logger.warning(
                        "Unexpected HITL decision type: %s",
                        decision.get("type"),
                    )
                else:
                    logger.warning(
                        "HITL decision was not a dict: %s",
                        type(decision).__name__,
                    )

            resolution = resolve_batch_approval_choice(
                len(action_requests),
                choice,
            )

            if resolution.enable_auto_approve:
                session_state.auto_approve = True
                if adapter._on_auto_approve_enabled:
                    adapter._on_auto_approve_enabled()

            if resolution.rejected:
                _reject_pending_tools(adapter)
                any_rejected = True
            else:
                _set_pending_tools_running(adapter)
                _mark_hitl_approved_file_ops(file_op_tracker, action_requests)

        hitl_response[interrupt_id] = {"decisions": resolution.decisions}

        if any_rejected:
            break

    return hitl_response, any_rejected


async def execute_task_textual(
    user_input: str,
    agent: Any,  # noqa: ANN401  # Dynamic agent graph type
    assistant_id: str | None,
    session_state: Any,  # noqa: ANN401  # Dynamic session state type
    adapter: TextualUIAdapter,
    backend: Any = None,  # noqa: ANN401  # Dynamic backend type
    image_tracker: MediaTracker | None = None,
) -> SessionStats:
    """Execute a task with output directed to Textual UI.

    This is the Textual-compatible version of execute_task() that uses
    the TextualUIAdapter for all UI operations.

    Args:
        user_input: The user's input message
        agent: The LangGraph agent to execute
        assistant_id: The agent identifier
        session_state: Session state with auto_approve flag
        adapter: The TextualUIAdapter for UI operations
        backend: Optional backend for file operations
        image_tracker: Optional tracker for images

    Returns:
        Stats accumulated over this turn (request count, token counts,
            wall-clock time).

    """
    # Parse file mentions and inject content if any
    prompt_text, mentioned_files = parse_file_mentions(user_input)

    # Max file size to embed inline (256KB, matching mistral-vibe)
    # Larger files get a reference instead - use read_file tool to view them
    max_embed_bytes = 256 * 1024

    if mentioned_files:
        context_parts = [prompt_text, "\n\n## Referenced Files\n"]
        for file_path in mentioned_files:
            try:
                file_size = file_path.stat().st_size
                if file_size > max_embed_bytes:
                    # File too large - include reference instead of content
                    size_kb = file_size // 1024
                    context_parts.append(
                        f"\n### {file_path.name}\n"
                        f"Path: `{file_path}`\n"
                        f"Size: {size_kb}KB (too large to embed, "
                        "use read_file tool to view)"
                    )
                else:
                    content = file_path.read_text(encoding="utf-8")
                    context_parts.append(
                        f"\n### {file_path.name}\n"
                        f"Path: `{file_path}`\n```\n{content}\n```"
                    )
            except Exception as e:  # noqa: BLE001  # Resilient adapter error handling
                context_parts.append(
                    f"\n### {file_path.name}\n[Error reading file: {e}]"
                )
        final_input = "\n".join(context_parts)
    else:
        final_input = prompt_text

    # Include images as runtime attachments; keep the content override only for
    # videos until the runtime schema supports them.
    attachments: tuple[dict[str, object], ...] = ()
    message_content_override: object | None = None

    images_to_send = []
    videos_to_send = []
    if image_tracker:
        images_to_send = image_tracker.get_images()
        videos_to_send = image_tracker.get_videos()

    if videos_to_send:
        message_content_override = create_multimodal_content(
            final_input, images_to_send, videos_to_send
        )
    elif images_to_send:
        attachments = tuple(
            {
                "kind": "image",
                "data_url": f"data:image/{image.format};base64,{image.base64_data}",
            }
            for image in images_to_send
        )

    thread_id = session_state.thread_id
    config = build_stream_config(thread_id, assistant_id)

    captured_input_tokens = 0
    captured_output_tokens = 0
    turn_stats = SessionStats()
    start_time = time.monotonic()

    # Show spinner
    if adapter._set_spinner:
        await adapter._set_spinner("Thinking")

    # Hide token display during streaming (will be shown with accurate count at end)
    if adapter._token_tracker:
        adapter._token_tracker.hide()

    file_op_tracker = FileOpTracker(assistant_id=assistant_id, backend=backend)
    displayed_tool_ids: set[str] = set()
    tracked_tool_ids: set[str] = set()

    # Track pending text and assistant messages PER NAMESPACE to avoid interleaving
    # when multiple subagents stream in parallel
    pending_text_by_namespace: dict[tuple, str] = {}
    assistant_message_by_namespace: dict[tuple, Any] = {}

    # Clear media from tracker after creating the message
    if image_tracker:
        image_tracker.clear()

    suppress_resumed_output = False

    try:

        async def _flush_namespace(ns_key: tuple[Any, ...]) -> None:
            pending_text = pending_text_by_namespace.get(ns_key, "")
            if pending_text:
                await _flush_assistant_text_ns(
                    adapter,
                    pending_text,
                    ns_key,
                    assistant_message_by_namespace,
                )
                pending_text_by_namespace[ns_key] = ""
            assistant_message_by_namespace.pop(ns_key, None)

        async def _mount_tool_widget(
            tool_name: str,
            tool_call_id: str | None,
            args: object,
        ) -> None:
            if tool_call_id is None:
                return

            parsed_args = args if isinstance(args, dict) else {}
            tool_msg = adapter._current_tool_messages.get(tool_call_id)
            if tool_msg is not None:
                if parsed_args and parsed_args != tool_msg._args:
                    tool_msg.update_args(parsed_args)
                    if adapter._sync_tool_args and tool_msg.id:
                        adapter._sync_tool_args(tool_msg.id, parsed_args)
                if parsed_args and tool_call_id not in tracked_tool_ids:
                    file_op_tracker.start_operation(
                        tool_name,
                        parsed_args,
                        tool_call_id,
                    )
                    tracked_tool_ids.add(tool_call_id)
                return

            displayed_tool_ids.add(tool_call_id)
            if parsed_args:
                file_op_tracker.start_operation(tool_name, parsed_args, tool_call_id)
                tracked_tool_ids.add(tool_call_id)

            if adapter._set_spinner:
                await adapter._set_spinner(None)

            tool_msg = ToolCallMessage(
                tool_name,
                parsed_args,
                id=f"tool-{uuid.uuid4().hex[:8]}",
            )
            await adapter._mount_message(tool_msg)
            adapter._current_tool_messages[tool_call_id] = tool_msg

            if adapter._scroll_to_bottom:
                adapter._scroll_to_bottom()

        async def _consume_runtime_event(event: RuntimeEvent) -> None:
            nonlocal captured_input_tokens, captured_output_tokens

            payload = event.payload
            ns_key = tuple(payload.get("namespace", []))

            if event.type == "run.failed":
                error_type = str(payload.get("error_type", "") or "") or "RunFailed"
                message = str(payload.get("message", "") or "")
                adapter.finalize_pending_tools_with_error(
                    f"Run failed ({error_type}): {message}".strip()
                )
                detail = f": {message}" if message else ""
                await adapter._mount_message(
                    ErrorMessage(f"Run failed ({error_type}){detail}")
                )
                return

            if event.type == "message.assistant.delta":
                text = str(payload.get("text", ""))
                if not text:
                    return

                pending_text = pending_text_by_namespace.get(ns_key, "")
                pending_text += text
                pending_text_by_namespace[ns_key] = pending_text

                current_msg = assistant_message_by_namespace.get(ns_key)
                if current_msg is None:
                    if adapter._set_spinner:
                        await adapter._set_spinner(None)
                    msg_id = f"asst-{uuid.uuid4().hex[:8]}"
                    if adapter._set_active_message:
                        adapter._set_active_message(msg_id)
                    current_msg = AssistantMessage(id=msg_id)
                    await adapter._mount_message(current_msg)
                    assistant_message_by_namespace[ns_key] = current_msg

                await current_msg.append_content(text)

                if adapter._scroll_to_bottom:
                    adapter._scroll_to_bottom()
                return

            if event.type == "message.assistant.completed":
                await _flush_namespace(ns_key)
                return

            if event.type == "run.summarization.started":
                if adapter._set_spinner:
                    await adapter._set_spinner("Summarizing")
                return

            if event.type == "run.summarization.completed":
                try:
                    await adapter._mount_message(SummarizationMessage())
                except Exception:
                    logger.debug(
                        "Failed to mount summarization notification",
                        exc_info=True,
                    )
                if adapter._set_spinner:
                    await adapter._set_spinner("Thinking")
                return

            if event.type == "run.usage":
                total_toks = int(payload.get("total_tokens", 0) or 0)
                output_toks = int(payload.get("output_tokens", 0) or 0)
                if total_toks:
                    captured_input_tokens = max(captured_input_tokens, total_toks)
                    captured_output_tokens = max(captured_output_tokens, output_toks)
                return

            if event.type == "usage.updated":
                model_name = str(payload.get("model_name", ""))
                input_tokens = int(payload.get("input_tokens", 0) or 0)
                output_tokens = int(payload.get("output_tokens", 0) or 0)
                total_tokens = int(payload.get("total_tokens", 0) or 0)
                if input_tokens or output_tokens:
                    turn_stats.record_request(model_name, input_tokens, output_tokens)
                elif total_tokens:
                    turn_stats.record_request(model_name, total_tokens, 0)
                return

            if event.type in {"tool.call.started", "tool.call.arguments"}:
                await _mount_tool_widget(
                    str(payload.get("tool_name", "")),
                    (
                        str(payload["tool_call_id"])
                        if payload.get("tool_call_id") is not None
                        else None
                    ),
                    payload.get("args", {}),
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
            tool_status = getattr(tool_message, "status", "success")
            tool_content = format_tool_message_content(tool_message.content)
            record = file_op_tracker.complete_with_message(tool_message)

            if adapter._set_spinner:
                await adapter._set_spinner("Thinking")

            tool_id = getattr(tool_message, "tool_call_id", None)
            if tool_id and tool_id in adapter._current_tool_messages:
                tool_msg = adapter._current_tool_messages[tool_id]
                output_str = str(tool_content) if tool_content else ""
                if tool_status == "success":
                    tool_msg.set_success(output_str)
                else:
                    tool_msg.set_error(output_str or "Error")
                adapter._current_tool_messages.pop(tool_id, None)

            if record:
                await _flush_namespace(ns_key)
                if record.diff:
                    await adapter._mount_message(
                        DiffMessage(record.diff, record.display_path)
                    )

        async def _resolve_approvals(
            pending_interrupts: dict[str, HITLRequest],
        ) -> dict[str, object]:
            nonlocal suppress_resumed_output

            hitl_response, any_rejected = await _resolve_textual_hitl_responses(
                pending_interrupts,
                adapter=adapter,
                assistant_id=assistant_id,
                session_state=session_state,
                file_op_tracker=file_op_tracker,
            )
            if any_rejected:
                suppress_resumed_output = True
                return {}
            return hitl_response

        envelope = InputEnvelope(
            thread_id=thread_id,
            mode="normal",
            text=final_input,
            attachments=attachments,
        )
        agent_run_config = AgentRunConfig(
            assistant_id=assistant_id,
            model_name=settings.model_name or "",
            resolve_approvals=_resolve_approvals,
        )

        async for event in stream_run_events(
            envelope,
            agent=agent,
            agent_config=agent_run_config,
            user_message_content=message_content_override,
        ):
            await _consume_runtime_event(event)

        if suppress_resumed_output:
            await adapter._mount_message(
                AppMessage("Command rejected. Tell the agent what you'd like instead.")
            )

    except asyncio.CancelledError:
        # Clear active message immediately so it won't block pruning
        # If we don't do this, the store still thinks it's actice and protects
        # from pruning, which breaks get_messages_to_prune(), potentially
        # blocking all future pruning
        if adapter._set_active_message:
            adapter._set_active_message(None)

        # Hide spinner (may still show "Summarizing" if interrupted mid-summary)
        if adapter._set_spinner:
            await adapter._set_spinner(None)

        await adapter._mount_message(AppMessage("Interrupted by user"))

        # Save accumulated state before marking tools as rejected (best-effort)
        # State update failures shouldn't prevent cleanup
        try:
            interrupted_msg = _build_interrupted_ai_message(
                pending_text_by_namespace,
                adapter._current_tool_messages,
            )
            if interrupted_msg:
                await agent.aupdate_state(config, {"messages": [interrupted_msg]})

            cancellation_msg = HumanMessage(
                content="[SYSTEM] Task interrupted by user. "
                "Previous operation was cancelled."
            )
            await agent.aupdate_state(config, {"messages": [cancellation_msg]})
        except Exception:
            logger.debug("Failed to save interrupted state", exc_info=True)

        # Mark tools as rejected AFTER saving state
        for tool_msg in list(adapter._current_tool_messages.values()):
            tool_msg.set_rejected()
        adapter._current_tool_messages.clear()

        # Report tokens even on interrupt (or restore display if none captured)
        turn_stats.wall_time_seconds = time.monotonic() - start_time
        if adapter._token_tracker:
            if captured_input_tokens or captured_output_tokens:
                adapter._token_tracker.add(
                    captured_input_tokens, captured_output_tokens
                )
            else:
                adapter._token_tracker.show()  # Restore previous value
        return turn_stats

    except KeyboardInterrupt:
        # Clear active message immediately so it won't block pruning
        # If we don't do this, the store still thinks it's actice and protects
        # from pruning, which breaks get_messages_to_prune(), potentially
        # blocking all future pruning
        if adapter._set_active_message:
            adapter._set_active_message(None)

        # Hide spinner (may still show "Summarizing" if interrupted mid-summary)
        if adapter._set_spinner:
            await adapter._set_spinner(None)

        await adapter._mount_message(AppMessage("Interrupted by user"))

        # Save accumulated state before marking tools as rejected (best-effort)
        # State update failures shouldn't prevent cleanup
        try:
            interrupted_msg = _build_interrupted_ai_message(
                pending_text_by_namespace,
                adapter._current_tool_messages,
            )
            if interrupted_msg:
                await agent.aupdate_state(config, {"messages": [interrupted_msg]})

            cancellation_msg = HumanMessage(
                content="[SYSTEM] Task interrupted by user. "
                "Previous operation was cancelled."
            )
            await agent.aupdate_state(config, {"messages": [cancellation_msg]})
        except Exception:
            logger.debug("Failed to save interrupted state", exc_info=True)

        # Mark tools as rejected AFTER saving state
        for tool_msg in list(adapter._current_tool_messages.values()):
            tool_msg.set_rejected()
        adapter._current_tool_messages.clear()

        # Report tokens even on interrupt (or restore display if none captured)
        turn_stats.wall_time_seconds = time.monotonic() - start_time
        if adapter._token_tracker:
            if captured_input_tokens or captured_output_tokens:
                adapter._token_tracker.add(
                    captured_input_tokens, captured_output_tokens
                )
            else:
                adapter._token_tracker.show()  # Restore previous value
        return turn_stats

    # Update token tracker and return stats
    turn_stats.wall_time_seconds = time.monotonic() - start_time
    if adapter._token_tracker and (captured_input_tokens or captured_output_tokens):
        adapter._token_tracker.add(captured_input_tokens, captured_output_tokens)
    return turn_stats


async def _flush_assistant_text_ns(
    adapter: TextualUIAdapter,
    text: str,
    ns_key: tuple,
    assistant_message_by_namespace: dict[tuple, Any],
) -> None:
    """Flush accumulated assistant text for a specific namespace.

    Finalizes the streaming by stopping the MarkdownStream.
    If no message exists yet, creates one with the full content.
    """
    if not text.strip():
        return

    current_msg = assistant_message_by_namespace.get(ns_key)
    if current_msg is None:
        # No message was created during streaming - create one with full content
        msg_id = f"asst-{uuid.uuid4().hex[:8]}"
        current_msg = AssistantMessage(text, id=msg_id)
        await adapter._mount_message(current_msg)
        await current_msg.write_initial_content()
        assistant_message_by_namespace[ns_key] = current_msg
    else:
        # Stop the stream to finalize the content
        await current_msg.stop_stream()

    # When the AssistantMessage was first mounted and recorded in the
    # MessageStore, it had empty content (streaming hadn't started yet).
    # Now that streaming is done, the widget holds the full text in
    # `_content`, but the store's MessageData still has `content=""`.
    # If the message is later pruned and re-hydrated, `to_widget()` would
    # recreate it from that stale empty string. This call copies the
    # widget's final content back into the store so re-hydration works.
    if adapter._sync_message_content and current_msg.id:
        adapter._sync_message_content(current_msg.id, current_msg._content)

    # Clear active message since streaming is done
    if adapter._set_active_message:
        adapter._set_active_message(None)
