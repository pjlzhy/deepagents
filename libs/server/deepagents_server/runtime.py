"""Shared execution service for the Deep Agents HTTP server."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager, AbstractContextManager


HitlDecision = dict[str, str]
HitlResumePayload = dict[str, dict[str, list[HitlDecision]]]
ActionRequest = dict[str, object]

_MAX_HITL_ITERATIONS = 50
_SHELL_TOOL_NAMES = frozenset({"bash", "shell", "execute"})


class CliModelResultProtocol(Protocol):
    """Minimal protocol for `deepagents_cli.config.ModelResult`."""

    model: object
    model_name: str | None

    def apply_to_settings(self) -> None:
        """Apply resolved model metadata back to CLI settings."""


class CliSettingsProtocol(Protocol):
    """Minimal protocol for CLI runtime settings consumed by the server."""

    has_tavily: bool
    shell_allow_list: list[str] | None


@dataclass(frozen=True)
class ExecutionRequest:
    """Input for a single runtime execution.

    Args:
        assistant_id: Stable agent identity used by the runtime.
        input: User input to pass into the agent run.
        model: Optional model spec or name.
        thread_id: Optional existing thread identifier.
        model_params: Optional model constructor overrides.
        profile_override: Optional model profile overrides.
        sandbox_type: Sandbox provider name.
        sandbox_id: Optional existing sandbox identifier.
        sandbox_setup: Optional sandbox setup script path.
        checkpointer: Optional injected checkpointer.
        checkpointer_backend: Backend to use when no checkpointer is injected.
        enable_memory: Whether memory-related defaults are enabled for the thread.
        enable_skills: Whether skills-related defaults are enabled for the thread.
        run_id: Optional run identifier associated with the execution.
    """

    assistant_id: str
    input: str
    model: str | None = None
    thread_id: str | None = None
    model_params: dict[str, object] | None = None
    profile_override: dict[str, object] | None = None
    sandbox_type: str = "none"
    sandbox_id: str | None = None
    sandbox_setup: str | None = None
    checkpointer: object | None = None
    checkpointer_backend: str = "local"
    enable_memory: bool = False
    enable_skills: bool = False
    run_id: str | None = None


@dataclass(frozen=True)
class RuntimeEvent:
    """Typed event emitted by `ExecutionService.stream`."""

    type: str
    payload: dict[str, object]


@dataclass(frozen=True)
class ExecutionResult:
    """Result returned by `ExecutionService.run`."""

    assistant_id: str
    thread_id: str
    model: str | None
    output: str


class RuntimeDependencyError(RuntimeError):
    """Raised when the CLI-backed runtime dependencies are unavailable."""


class RuntimeServiceError(RuntimeError):
    """Raised when the shared execution service cannot complete a run."""


class RuntimeAgentProtocol(Protocol):
    """Protocol for agents that expose `astream`."""

    def astream(
        self,
        stream_input: object,
        *,
        stream_mode: list[str],
        subgraphs: bool,
        config: dict[str, object],
        durability: str,
    ) -> AsyncIterator[object]:
        """Yield streamed chunks for a single run."""


@dataclass(frozen=True)
class RuntimeContext:
    """Resolved execution context for a single request."""

    agent: RuntimeAgentProtocol
    config: dict[str, object]
    assistant_id: str
    thread_id: str
    model: str | None
    shell_allow_list: list[str] | None


@dataclass(frozen=True)
class RuntimeDependencies:
    """Resolved CLI-backed runtime dependencies.

    Keeping these imports explicit preserves source navigation and signatures while
    still allowing the server to load them lazily at runtime.
    """

    create_cli_agent: Callable[..., tuple[RuntimeAgentProtocol, object]]
    create_model: Callable[..., CliModelResultProtocol]
    settings: CliSettingsProtocol
    generate_thread_id: Callable[[], str]
    get_checkpointer: Callable[[], AbstractAsyncContextManager[object]]
    fetch_url: object
    http_request: object
    web_search: object
    create_sandbox: Callable[..., AbstractContextManager[object]]


class RuntimeAdapter(Protocol):
    """Adapter that bridges the server runtime to a concrete agent backend."""

    def open_runtime(
        self,
        request: ExecutionRequest,
    ) -> AbstractAsyncContextManager[RuntimeContext]:
        """Open a runtime context for a request."""

    def build_initial_input(self, request: ExecutionRequest) -> object:
        """Build the initial stream input for a request."""

    def build_resume_input(self, resume_payload: HitlResumePayload) -> object:
        """Build the follow-up stream input after HITL decisions."""

    def is_shell_command_allowed(
        self,
        command: str,
        allow_list: list[str] | None,
    ) -> bool:
        """Return whether the given shell command should be auto-approved."""


@dataclass
class _ExecutionState:
    """Mutable state accumulated across stream passes."""

    full_response: list[str] = field(default_factory=list)
    tool_call_buffers: dict[int | str, dict[str, str | None]] = field(default_factory=dict)
    pending_interrupts: dict[str, list[ActionRequest]] = field(default_factory=dict)
    resume_payload: HitlResumePayload = field(default_factory=dict)


class ExecutionService:
    """Runtime service shared by server routes and tests."""

    def __init__(self, adapter: RuntimeAdapter | None = None) -> None:
        """Create the execution service.

        Args:
            adapter: Optional runtime adapter override.
        """
        self._adapter = adapter or CliRuntimeAdapter()

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        """Run a request to completion and collect the final text output.

        Args:
            request: Runtime request to execute.

        Returns:
            Final execution result with collected text output.
        """
        output = ""
        thread_id = request.thread_id or ""
        model = request.model

        async for event in self.stream(request):
            thread_value = event.payload.get("thread_id")
            if isinstance(thread_value, str):
                thread_id = thread_value

            model_value = event.payload.get("model")
            if model_value is None or isinstance(model_value, str):
                model = model_value

            if event.type == "run.completed":
                output_value = event.payload.get("output")
                if isinstance(output_value, str):
                    output = output_value

        return ExecutionResult(
            assistant_id=request.assistant_id,
            thread_id=thread_id,
            model=model,
            output=output,
        )

    async def stream(self, request: ExecutionRequest) -> AsyncIterator[RuntimeEvent]:
        """Stream typed runtime events for a request.

        Args:
            request: Runtime request to execute.

        Yields:
            Typed runtime events.
        """
        async with self._adapter.open_runtime(request) as context:
            state = _ExecutionState()
            stream_input = self._adapter.build_initial_input(request)
            iterations = 0

            while True:
                async for event in self._consume_stream_pass(context, stream_input, state):
                    yield event

                if not state.pending_interrupts and not state.resume_payload:
                    break

                iterations += 1
                if iterations > _MAX_HITL_ITERATIONS:
                    msg = (
                        f"Exceeded {_MAX_HITL_ITERATIONS} HITL interrupt rounds. "
                        "The agent may be stuck retrying rejected commands."
                    )
                    raise RuntimeServiceError(msg)

                self._resolve_interrupts(context, state)
                stream_input = self._adapter.build_resume_input(dict(state.resume_payload))
                state.pending_interrupts.clear()
                state.resume_payload.clear()

            yield self._make_event(
                context,
                "run.completed",
                {"output": "".join(state.full_response)},
            )

    async def _consume_stream_pass(
        self,
        context: RuntimeContext,
        stream_input: object,
        state: _ExecutionState,
    ) -> AsyncIterator[RuntimeEvent]:
        async for chunk in context.agent.astream(
            stream_input,
            stream_mode=["messages", "updates"],
            subgraphs=True,
            config=context.config,
            durability="exit",
        ):
            for event in self._process_stream_chunk(context, chunk, state):
                yield event

    def _process_stream_chunk(
        self,
        context: RuntimeContext,
        chunk: object,
        state: _ExecutionState,
    ) -> list[RuntimeEvent]:
        if not isinstance(chunk, tuple) or len(chunk) != 3:  # noqa: PLR2004
            return []

        namespace, stream_mode, data = chunk
        if namespace:
            return []

        if stream_mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
            return self._process_interrupts(context, cast("dict[str, object]", data), state)
        if stream_mode == "messages":
            return self._process_message_chunk(context, data, state)
        return []

    def _process_interrupts(
        self,
        context: RuntimeContext,
        data: dict[str, object],
        state: _ExecutionState,
    ) -> list[RuntimeEvent]:
        interrupt_objects = data.get("__interrupt__")
        if not isinstance(interrupt_objects, list):
            return []

        events: list[RuntimeEvent] = []
        for interrupt_obj in interrupt_objects:
            interrupt_id = getattr(interrupt_obj, "id", None)
            interrupt_value = getattr(interrupt_obj, "value", None)
            if not isinstance(interrupt_id, str) or not isinstance(interrupt_value, dict):
                continue

            action_requests = interrupt_value.get("action_requests")
            if not isinstance(action_requests, list):
                state.resume_payload[interrupt_id] = {
                    "decisions": [{"type": "reject", "message": "Malformed interrupt"}],
                }
                continue

            normalized_actions = [
                cast("ActionRequest", action_request)
                for action_request in action_requests
                if isinstance(action_request, dict)
            ]
            state.pending_interrupts[interrupt_id] = normalized_actions
            events.append(
                self._make_event(
                    context,
                    "interrupt.required",
                    {
                        "interrupt_id": interrupt_id,
                        "action_requests": normalized_actions,
                    },
                )
            )
        return events

    def _process_message_chunk(
        self,
        context: RuntimeContext,
        data: object,
        state: _ExecutionState,
    ) -> list[RuntimeEvent]:
        if not isinstance(data, tuple) or len(data) != 2:  # noqa: PLR2004
            return []

        message_obj, metadata = data
        if isinstance(metadata, dict):
            metadata_dict = cast("dict[str, object]", metadata)
            if metadata_dict.get("lc_source") == "summarization":
                return []

        content_blocks = getattr(message_obj, "content_blocks", None)
        if isinstance(content_blocks, list):
            return self._process_content_blocks(context, content_blocks, state)

        tool_call_id = getattr(message_obj, "tool_call_id", None)
        if isinstance(tool_call_id, str):
            tool_payload: dict[str, object] = {
                "tool_call_id": tool_call_id,
                "content": self._stringify_message_content(getattr(message_obj, "content", None)),
            }
            name = getattr(message_obj, "name", None)
            if isinstance(name, str):
                tool_payload["name"] = name
            return [self._make_event(context, "tool.result", tool_payload)]
        return []

    def _process_content_blocks(
        self,
        context: RuntimeContext,
        content_blocks: list[object],
        state: _ExecutionState,
    ) -> list[RuntimeEvent]:
        events: list[RuntimeEvent] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue

            block_dict = cast("dict[str, object]", block)
            block_type = block_dict.get("type")
            if block_type == "text":
                text = block_dict.get("text")
                if isinstance(text, str) and text:
                    state.full_response.append(text)
                    events.append(self._make_event(context, "message.delta", {"text": text}))
                continue

            if block_type not in {"tool_call", "tool_call_chunk"}:
                continue

            chunk_name = block_dict.get("name")
            if not isinstance(chunk_name, str) or not chunk_name:
                continue

            chunk_index = block_dict.get("index")
            chunk_id = block_dict.get("id")
            if isinstance(chunk_index, int):
                buffer_key: int | str = chunk_index
            elif isinstance(chunk_id, str):
                buffer_key = chunk_id
            else:
                buffer_key = f"unknown-{len(state.tool_call_buffers)}"

            previous_name = state.tool_call_buffers.get(buffer_key, {}).get("name")
            state.tool_call_buffers[buffer_key] = {
                "name": chunk_name,
                "id": chunk_id if isinstance(chunk_id, str) else None,
            }
            if previous_name == chunk_name:
                continue

            events.append(
                self._make_event(
                    context,
                    "tool.call",
                    {
                        "name": chunk_name,
                        "tool_call_id": chunk_id if isinstance(chunk_id, str) else None,
                        "index": chunk_index if isinstance(chunk_index, int) else None,
                    },
                )
            )
        return events

    def _resolve_interrupts(self, context: RuntimeContext, state: _ExecutionState) -> None:
        for interrupt_id, action_requests in state.pending_interrupts.items():
            decisions = [
                self._make_hitl_decision(action_request, context.shell_allow_list)
                for action_request in action_requests
            ]
            state.resume_payload[interrupt_id] = {"decisions": decisions}

    def _make_hitl_decision(
        self,
        action_request: ActionRequest,
        allow_list: list[str] | None,
    ) -> HitlDecision:
        action_name = action_request.get("name")
        if not isinstance(action_name, str):
            return {"type": "reject", "message": "Malformed interrupt"}

        if action_name in _SHELL_TOOL_NAMES:
            command = self._extract_shell_command(action_request)
            if not allow_list:
                return {
                    "type": "reject",
                    "message": (
                        "Shell commands are not permitted in non-interactive mode "
                        "without a --shell-allow-list. Use --shell-allow-list to "
                        "specify allowed commands."
                    ),
                }
            if self._adapter.is_shell_command_allowed(command, allow_list):
                return {"type": "approve"}
            allowed_list_str = ", ".join(allow_list)
            return {
                "type": "reject",
                "message": (
                    f"Command '{command}' is not in the allow-list. "
                    f"Allowed commands: {allowed_list_str}. "
                    "Please use allowed commands or try another approach."
                ),
            }

        return {"type": "approve"}

    def _extract_shell_command(self, action_request: ActionRequest) -> str:
        args = action_request.get("args")
        if not isinstance(args, dict):
            return ""
        args_dict = cast("dict[str, object]", args)
        command = args_dict.get("command")
        return command if isinstance(command, str) else ""

    def _make_event(
        self,
        context: RuntimeContext,
        event_type: str,
        payload: dict[str, object],
    ) -> RuntimeEvent:
        event_payload = {
            "assistant_id": context.assistant_id,
            "thread_id": context.thread_id,
            "model": context.model,
            **payload,
        }
        return RuntimeEvent(type=event_type, payload=event_payload)

    def _stringify_message_content(self, content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(item) for item in content)
        if content is None:
            return ""
        return str(content)


class CliRuntimeAdapter:
    """Adapter that reuses CLI runtime semantics behind a non-UI boundary."""

    @asynccontextmanager
    async def open_runtime(self, request: ExecutionRequest) -> AsyncIterator[RuntimeContext]:
        """Open a CLI-backed runtime context."""
        dependencies = self._load_dependencies()

        thread_id = request.thread_id or dependencies.generate_thread_id()
        model_result = dependencies.create_model(
            request.model,
            extra_kwargs=request.model_params,
            profile_overrides=request.profile_override,
        )
        model_result.apply_to_settings()

        config: dict[str, object] = {
            "configurable": {"thread_id": thread_id},
            "metadata": {
                "assistant_id": request.assistant_id,
                "agent_name": request.assistant_id,
                "run_id": request.run_id,
                "checkpointer_backend": request.checkpointer_backend,
                "sandbox_type": request.sandbox_type,
                "enable_memory": request.enable_memory,
                "enable_skills": request.enable_skills,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }

        async with AsyncExitStack() as exit_stack:
            sandbox_backend = None
            if request.sandbox_type != "none":
                try:
                    sandbox_cm = dependencies.create_sandbox(
                        request.sandbox_type,
                        sandbox_id=request.sandbox_id,
                        setup_script_path=request.sandbox_setup,
                    )
                    sandbox_backend = exit_stack.enter_context(sandbox_cm)
                except Exception as exc:
                    msg = (
                        f"Sandbox type '{request.sandbox_type}' is not supported in the current "
                        f"server environment: {exc}"
                    )
                    raise RuntimeServiceError(msg) from exc

            if request.checkpointer is not None:
                checkpointer = request.checkpointer
            elif request.checkpointer_backend == "memory":
                checkpointer = None
            elif request.checkpointer_backend == "local":
                checkpointer = await exit_stack.enter_async_context(
                    dependencies.get_checkpointer()
                )
            else:
                msg = (
                    f"Unsupported checkpointer backend '{request.checkpointer_backend}'. "
                    "Expected one of: local, memory."
                )
                raise RuntimeServiceError(msg)

            tools = [dependencies.http_request, dependencies.fetch_url]
            if dependencies.settings.has_tavily:
                tools.append(dependencies.web_search)

            shell_allow_list = dependencies.settings.shell_allow_list
            enable_shell = bool(shell_allow_list)
            agent, _backend = dependencies.create_cli_agent(
                model=model_result.model,
                assistant_id=request.assistant_id,
                tools=tools,
                sandbox=sandbox_backend,
                sandbox_type=request.sandbox_type if request.sandbox_type != "none" else None,
                auto_approve=not enable_shell,
                enable_shell=enable_shell,
                checkpointer=checkpointer,
            )
            yield RuntimeContext(
                agent=agent,
                config=config,
                assistant_id=request.assistant_id,
                thread_id=thread_id,
                model=model_result.model_name,
                shell_allow_list=shell_allow_list,
            )

    def build_initial_input(self, request: ExecutionRequest) -> object:
        """Build the initial user message input."""
        return {"messages": [{"role": "user", "content": request.input}]}

    def build_resume_input(self, resume_payload: HitlResumePayload) -> object:
        """Build the resume input for a HITL continuation."""
        try:
            from langgraph.types import Command  # noqa: PLC0415
        except ImportError as exc:
            msg = (
                "CLI-backed runtime dependencies are unavailable. Install "
                "`deepagents-cli` in the same environment before using the "
                "server execution service."
            )
            raise RuntimeDependencyError(msg) from exc

        return Command(resume=resume_payload)

    def is_shell_command_allowed(
        self,
        command: str,
        allow_list: list[str] | None,
    ) -> bool:
        """Delegate shell allow-list checks to the CLI implementation."""
        try:
            from deepagents_cli.config import is_shell_command_allowed  # noqa: PLC0415
        except ImportError as exc:
            msg = (
                "CLI-backed runtime dependencies are unavailable. Install "
                "`deepagents-cli` in the same environment before using the "
                "server execution service."
            )
            raise RuntimeDependencyError(msg) from exc

        return is_shell_command_allowed(command, allow_list)

    def _load_dependencies(self) -> RuntimeDependencies:
        try:
            from deepagents_cli.agent import create_cli_agent  # noqa: PLC0415
            from deepagents_cli.config import create_model, settings  # noqa: PLC0415
            from deepagents_cli.integrations.sandbox_factory import (  # noqa: PLC0415
                create_sandbox,
            )
            from deepagents_cli.sessions import (  # noqa: PLC0415
                generate_thread_id,
                get_checkpointer,
            )
            from deepagents_cli.tools import (  # noqa: PLC0415
                fetch_url,
                http_request,
                web_search,
            )
        except ImportError as exc:
            msg = (
                "CLI-backed runtime dependencies are unavailable. Install "
                "`deepagents-cli` in the same environment before using the "
                "server execution service."
            )
            raise RuntimeDependencyError(msg) from exc

        return RuntimeDependencies(
            create_cli_agent=cast(
                "Callable[..., tuple[RuntimeAgentProtocol, object]]",
                create_cli_agent,
            ),
            create_model=cast(
                "Callable[..., CliModelResultProtocol]",
                create_model,
            ),
            settings=cast("CliSettingsProtocol", settings),
            generate_thread_id=cast("Callable[[], str]", generate_thread_id),
            get_checkpointer=cast(
                "Callable[[], AbstractAsyncContextManager[object]]",
                get_checkpointer,
            ),
            fetch_url=fetch_url,
            http_request=http_request,
            web_search=web_search,
            create_sandbox=cast(
                "Callable[..., AbstractContextManager[object]]",
                create_sandbox,
            ),
        )
