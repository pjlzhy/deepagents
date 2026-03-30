import asyncio
import logging
import os
import time
import uuid

from pathlib import Path
from types import SimpleNamespace

from typing import Any
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langchain.agents.middleware import InterruptOnConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from deepagents.graph import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend
from deepagents.middleware.subagents import SubAgent
from deepagents.middleware.memory import MemoryMiddleware
from deepagents.middleware.summarization import (
    SummarizationToolMiddleware,
    create_summarization_middleware,
)
from deepagents_runtime import events
from deepagents_runtime.events import RuntimeEvent

from deepagents_runtime.mcp_tool import load_mcp_tools_from_configs
from deepagents_runtime.models import create_model, ModelResult
from deepagents_runtime.registry import Registry
from deepagents_runtime.sandbox.docker import DockerSandboxBackend
from deepagents_runtime.sandbox.k8s import K8sSandboxBackend
from deepagents_runtime.skills import RuntimeSkillsMiddleware
from deepagents_runtime.spec import (
    AgentSpec,
    MCPRuntime,
    SandboxRuntime,
    AgentStatus,
    resolve_sandbox_backend_kind,
    validate_agent_spec,
)
from deepagents_runtime.streams import StreamParserState, parse_stream_part

REQUIRE_COMPACT_TOOL_APPROVAL: bool = True
"""When ``True``, ``compact_conversation`` requires HITL approval."""

_MAX_HITL_ITERATIONS = 50

logger = logging.getLogger(__name__)

HITLHandler = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]

# ---------------------------------------------------------------------------
# Default system prompt (hardcoded)
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = '''\
# Deep Agents CLI

You are a Deep Agent, an AI assistant running in an interactive CLI on the user's computer. You help with tasks like coding, debugging, research, analysis, and more.

The user sends you messages and you respond with text and tool calls. Your tools run on the user's machine. The user can see your responses and tool outputs in real time, so keep them informed — but don't over-explain.

# Core Behavior

- Be concise and direct. Answer in fewer than 4 lines unless detail is requested.
- After working on a file, stop — don't explain what you did unless asked.
- NEVER add unnecessary preamble ("Sure!", "Great question!", "I'll now...").
- Don't say "I'll now do X" — just do it.
- No time estimates. Focus on what needs to be done, not how long.
- If the request is ambiguous, ask questions before acting.
- If asked how to approach something, explain first, then act.
- When you run non-trivial bash commands, briefly explain what they do.
- For longer tasks, give brief progress updates — what you've done, what's next.

## Professional Objectivity

- Prioritize technical accuracy over validating the user's beliefs
- Disagree respectfully when the user is incorrect
- Avoid unnecessary superlatives, praise, or emotional validation

## Following Conventions

- Check existing code for libraries and frameworks before assuming
- Mimic existing code style, naming conventions, and patterns
- Prefer editing existing files over creating new ones
- Only make changes that are directly requested — don't add features, refactor, or "improve" code beyond what was asked
- Never add comments unless asked
- CRITICAL: Read files before editing — understand existing code before making changes

## Doing Tasks

When the user asks you to do something:

1. **Understand first** — read relevant files, check existing patterns.
2. **Build to the plan** — implement what you designed in step 1.
3. **Test and iterate** — run tests, read output carefully, fix issues one at a time.
4. **Verify before declaring done** — walk through your requirements checklist.

Keep working until the task is fully complete. Don't stop partway to explain what you would do — do it. Only ask when genuinely blocked.

CRITICAL: Match what the user asked for EXACTLY.
- Field names, paths, schemas, identifiers must match specifications verbatim
- If the user defines a schema, copy field names verbatim. Do not rename or "improve" them.

**When things go wrong:**
- Think through the issue by working backwards from the user's goal and plan.
- If something fails repeatedly, stop and analyze *why*.
- Use tools and dependencies specified by the user or already present in the codebase.

## Tool Usage

IMPORTANT: Use specialized tools instead of shell commands:
- `read_file` over `cat`/`head`/`tail`
- `edit_file` over `sed`/`awk`
- `write_file` over `echo`/heredoc
- `grep` tool over shell `grep`/`rg`
- `glob` over shell `find`/`ls`

When performing multiple independent operations, make all tool calls in a single response.

### shell

Execute shell commands. Always quote paths with spaces.

### File Tools

- read_file: Read file contents (use absolute paths)
- edit_file: Replace exact strings in files (must read first)
- write_file: Create or overwrite files
- ls: List directory contents
- glob: Find files by pattern
- grep: Search file contents

Always use absolute paths starting with /.

### web_search

Search for documentation, error solutions, and code examples.

### http_request

Make HTTP requests to APIs (GET, POST, etc.).

## File Reading Best Practices

When exploring codebases or reading multiple files, use pagination to prevent context overflow.

**Pattern for codebase exploration:**
1. First scan: `read_file(path, limit=100)` — See file structure
2. Targeted read: `read_file(path, offset=100, limit=200)` — Read specific sections
3. Full read: Only use `read_file(path)` without limit when necessary for editing

## Working with Subagents (task tool)

When delegating to subagents:
- **Use filesystem for large I/O**: If input/output is large (>500 words), communicate via files
- **Parallelize independent work**: Spawn parallel subagents for independent tasks
- **Clear specifications**: Tell subagent exactly what format/structure you need
- **Main agent synthesizes**: Subagents gather/execute, main agent integrates results

## Git Safety Protocol

- NEVER update the git config
- NEVER run destructive commands unless the user explicitly requests it
- NEVER skip hooks unless explicitly requested
- NEVER force push to main/master
- CRITICAL: Always create NEW commits rather than amending, unless explicitly asked
- When staging, prefer specific files over `git add -A` or `git add .`
- NEVER commit unless the user explicitly asks

## Security

- Be careful not to introduce XSS, SQL injection, command injection, or other OWASP top 10 vulnerabilities
- If you notice you wrote insecure code, fix it immediately
- Never commit secrets (.env, credentials.json, API keys)

## Debugging Best Practices

When something isn't working:
- Read the FULL error output — not just the first line
- Reproduce the error before attempting a fix
- Isolate variables: change one thing at a time
- Address root causes, not symptoms

## Error Handling

- If you introduce linter errors, fix them if the solution is clear
- DO NOT loop more than 3 times fixing the same error with the same approach
- On the third attempt, stop and ask the user what to do

## Dependencies

- Use the project's package manager to install dependencies
- Don't mix package managers in the same project

---

{model_identity_section}{working_dir_section}### Skills Directory

Your skills are stored at: `{skills_path}`
Skills may contain scripts or supporting files. When executing skill scripts with bash, use the real filesystem path:
Example: `bash python {skills_path}/web-research/script.py`

### Human-in-the-Loop Tool Approval

Some tool calls require user approval before execution. When a tool call is rejected by the user:
1. Accept their decision immediately - do NOT retry the same command
2. Explain that you understand they rejected the action
3. Suggest an alternative approach or ask for clarification
4. Never attempt the exact same rejected command again

### Web Search Tool Usage

When you use the web_search tool:
1. The tool will return search results with titles, URLs, and content excerpts
2. You MUST read and process these results, then respond naturally to the user
3. NEVER show raw JSON or tool results directly to the user
4. Synthesize the information from multiple sources into a coherent answer
5. Cite your sources by mentioning page titles or URLs when relevant

### Todo List Management

When using the write_todos tool:
1. Use todos for any task with 2+ steps — they give the user visibility
2. Mark tasks `in_progress` before starting, `completed` immediately after
3. Don't batch completions — mark each item done as you finish it
4. If a task reveals sub-tasks, add them right away
5. For simple 1-step tasks, just do them directly
6. When first creating a todo list for a task, ALWAYS ask the user if the plan looks good before starting work
7. Update todo status promptly as you complete each item
'''


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


def get_system_prompt(
        agent_name: str,
        *,
        prompt: str,
        model: ModelResult,
        skills_dir: str,
) -> str:
    """Build the full system prompt.

    Structure: ``[user prompt]\\n\\n[DEFAULT_SYSTEM_PROMPT with interpolations]``

    The SDK will further append its own ``BASE_AGENT_PROMPT`` after this.
    """
    template = DEFAULT_SYSTEM_PROMPT

    skills_path = skills_dir

    # Model identity section
    model_identity_section = (
        f"### Model Identity\n\n"
        f"You are running as model `{model.model_name}`"
        f" (provider: {model.provider}).\n"
    )
    if model.context_limit:
        model_identity_section += (
            f"Your context window is {model.context_limit:,} tokens.\n"
        )
    model_identity_section += f"Your name is {agent_name}.\n\n"

    # Working directory section
    cwd = Path.cwd()
    working_dir_section = (
        f"### Current Working Directory\n\n"
        f"The filesystem backend is currently operating in: `{cwd}`\n\n"
        f"### File System and Paths\n\n"
        f"**IMPORTANT - Path Handling:**\n"
        f"- All file paths must be absolute paths (e.g., `{cwd}/file.txt`)\n"
        f"- Use the working directory to construct absolute paths\n"
        f"- Never use relative paths - always construct full absolute paths\n\n"
    )

    if prompt:
        template = f"{prompt}\n\n{template}"

    return (
        template.replace("{model_identity_section}", model_identity_section)
        .replace("{working_dir_section}", working_dir_section)
        .replace("{skills_path}", skills_path)
    )


# ---------------------------------------------------------------------------
# HITL description formatters
# ---------------------------------------------------------------------------


def _format_write_file_description(
        tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any],
) -> str:
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    content = args.get("content", "")
    action = "Overwrite" if Path(file_path).exists() else "Create"
    line_count = len(content.splitlines())
    return f"File: {file_path}\nAction: {action} file\nLines: {line_count}"


def _format_edit_file_description(
        tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any],
) -> str:
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    replace_all = bool(args.get("replace_all", False))
    scope = "all occurrences" if replace_all else "single occurrence"
    return f"File: {file_path}\nAction: Replace text ({scope})"


def _format_web_search_description(
        tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any],
) -> str:
    args = tool_call["args"]
    query = args.get("query", "unknown")
    max_results = args.get("max_results", 5)
    return (
        f"Query: {query}\nMax results: {max_results}\n\n"
        f"[warn]  This will use Tavily API credits"
    )


def _format_fetch_url_description(
        tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any],
) -> str:
    args = tool_call["args"]
    url = args.get("url", "unknown")
    timeout = args.get("timeout", 30)
    return (
        f"URL: {url}\nTimeout: {timeout}s\n\n"
        f"[warn]  Will fetch and convert web content to markdown"
    )


def _format_task_description(
        tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any],
) -> str:
    args = tool_call["args"]
    description = args.get("description", "unknown")
    subagent_type = args.get("subagent_type", "unknown")
    description_preview = description
    if len(description) > 500:
        description_preview = description[:500] + "..."
    return (
        f"Subagent Type: {subagent_type}\n\n"
        f"Task Instructions:\n"
        f"{description_preview}\n"
        f"[warn]  Subagent will have access to file operations and shell commands"
    )


def _format_execute_description(
        tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any],
) -> str:
    args = tool_call["args"]
    command = args.get("command", "N/A")
    return f"Execute Command: {command}\nWorking Directory: {Path.cwd()}"


# ---------------------------------------------------------------------------
# interrupt_on builder
# ---------------------------------------------------------------------------


def _add_interrupt_on() -> dict[str, bool | InterruptOnConfig]:
    """Build the default interrupt_on mapping for all gated tools."""
    interrupt_map: dict[str, bool | InterruptOnConfig] = {
        "execute": {
            "allowed_decisions": ["approve", "reject"],
            "description": _format_execute_description,
        },
        "write_file": {
            "allowed_decisions": ["approve", "reject"],
            "description": _format_write_file_description,
        },
        "edit_file": {
            "allowed_decisions": ["approve", "reject"],
            "description": _format_edit_file_description,
        },
        "web_search": {
            "allowed_decisions": ["approve", "reject"],
            "description": _format_web_search_description,
        },
        "fetch_url": {
            "allowed_decisions": ["approve", "reject"],
            "description": _format_fetch_url_description,
        },
        "task": {
            "allowed_decisions": ["approve", "reject"],
            "description": _format_task_description,
        },
    }

    if REQUIRE_COMPACT_TOOL_APPROVAL:
        interrupt_map["compact_conversation"] = {
            "allowed_decisions": ["approve", "reject"],
            "description": (
                "Summarizes older messages into a shorter summary "
                "using an LLM call, then replaces them in context. "
                "Recent messages are kept as-is. Full history is "
                "written to backend storage for agent retrieval."
            ),
        }

    return interrupt_map


@dataclass
class RuntimeAgent:
    """Manager-owned runtime bookkeeping per agent."""

    def __init__(
            self,
            *,
            spec: AgentSpec,
            reg: Registry,
    ):
        self.spec: AgentSpec = spec

        self._graph: CompiledStateGraph = None
        self._mcp_runtime: MCPRuntime | None = None
        self._sandbox_runtime: SandboxRuntime | None = None

        self.registry: Registry = reg

        self.last_invoked: datetime | None = None

        self._runtime_lock: asyncio.Lock = asyncio.Lock()
        self._runtime_status: str | None = None

    def status(self) -> AgentStatus:
        """Return the public lifecycle status for this runtime agent."""
        if self._runtime_status == "running":
            return AgentStatus.RUNNING
        if self._graph is not None:
            return AgentStatus.COMPILED
        return AgentStatus.INSTALLED

    def is_busy(self) -> bool:
        """Return whether the agent is in a transitional or running state."""
        return self._runtime_status in {"assembling", "running", "releasing"}

    def is_running(self) -> bool:
        """Return whether the agent currently has an active run."""
        return self._runtime_status == "running"

    def has_runtime(self) -> bool:
        """Return whether compiled runtime resources are currently loaded."""
        return self._graph is not None

    def _build_workspace_backend(self) -> LocalShellBackend:
        """Create the default workspace-local backend for this agent."""
        return LocalShellBackend(
            root_dir=str(self.registry.workspace_dir(self.spec.name)),
            inherit_env=True,
            virtual_mode=False,
        )

    async def _build_sandbox_backend(self, *, spec: dict[str, Any]) -> Any:
        """Create the concrete backend selected by the sandbox spec."""
        backend_kind = resolve_sandbox_backend_kind(spec)
        if backend_kind == "local":
            return self._build_workspace_backend()
        if backend_kind == "docker":
            backend = await DockerSandboxBackend.from_spec(spec)
            await backend.start()
            return backend
        if backend_kind == "k8s":
            backend = await K8sSandboxBackend.from_spec(spec)
            await backend.start()
            return backend

        msg = f"unsupported sandbox backend '{backend_kind}'"
        raise ValueError(msg)

    async def _create_sandbox_runtime(self, *, spec: dict[str, Any]) -> SandboxRuntime:
        """Create the agent-scoped sandbox runtime owner."""
        backend = await self._build_sandbox_backend(spec=spec)

        return SandboxRuntime(
            spec=spec,
            backend=backend,
        )

    def _merge_runtime_context(
            self,
            context: Any,
            *,
            sandbox_backend: Any,
    ) -> Any:
        """Overlay the sandbox backend onto a graph runtime context."""
        if context is None:
            return {"sandbox_backend": sandbox_backend}
        if isinstance(context, dict):
            merged_context = dict(context)
            merged_context["sandbox_backend"] = sandbox_backend
            return merged_context
        overlay = SimpleNamespace(sandbox_backend=sandbox_backend)
        for attr in dir(context):
            if attr.startswith("_") or hasattr(overlay, attr):
                continue
            try:
                setattr(overlay, attr, getattr(context, attr))
            except AttributeError:
                continue
        return overlay

    @asynccontextmanager
    async def _sandbox_context(self, context: Any) -> AsyncIterator[Any]:
        """Inject the agent-owned sandbox backend into the runtime context."""
        sandbox_runtime = self._sandbox_runtime
        if sandbox_runtime is None:
            yield context
            return

        yield self._merge_runtime_context(
            context,
            sandbox_backend=sandbox_runtime.backend,
        )

    async def _cleanup_sandbox_backend(self, sandbox_backend: Any) -> None:
        """Best-effort cleanup for an owned sandbox backend."""
        cleanup = getattr(sandbox_backend, "cleanup", None)
        if cleanup and callable(cleanup):
            try:
                result = cleanup()
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception:
                logger.warning("Error cleaning up sandbox", exc_info=True)

    def build_model_extra_kwargs(self) -> dict[str, Any]:
        """Resolve model constructor kwargs from an agent spec."""
        extra_kwargs: dict[str, Any] = {}
        if self.spec.model_config:
            if self.spec.model_config.get("base_url"):
                extra_kwargs["base_url"] = self.spec.model_config["base_url"]
            if self.spec.model_config.get("api_key"):
                extra_kwargs["api_key"] = self.spec.model_config["api_key"]
            elif self.spec.model_config.get("api_key_env"):
                env_val = os.environ.get(self.spec.model_config["api_key_env"])
                if env_val:
                    extra_kwargs["api_key"] = env_val
            if self.spec.model_config.get("extra_params"):
                extra_kwargs.update(self.spec.model_config["extra_params"])
        return extra_kwargs

    @asynccontextmanager
    async def _runtime_phase(
            self,
            *,
            blocked_states: tuple[str, ...],
            enter_state: str,
            success_state: str | None,
    ) -> AsyncIterator[None]:
        """Transition runtime state with automatic rollback on failure."""
        async with self._runtime_lock:
            if self._runtime_status in blocked_states:
                msg = (
                    f"agent {self.spec.name} is {self._runtime_status}, "
                    "try again later."
                )
                raise RuntimeError(msg)
            previous_status = self._runtime_status
            self._runtime_status = enter_state

        succeeded = False
        try:
            yield
            succeeded = True
        finally:
            async with self._runtime_lock:
                if self._runtime_status == enter_state:
                    self._runtime_status = (
                        success_state if succeeded else previous_status
                    )

    async def assemble(
            self,
            *,
            checkpointer: Any = None,
    ):
        async with self._runtime_phase(
                blocked_states=("assembling", "running"),
                enter_state="assembling",
                success_state="assembled",
        ):
            await self._assemble_impl(checkpointer=checkpointer)

    async def _assemble_impl(
            self,
            *,
            checkpointer: Any = None,
    ) -> None:
        """Build compiled runtime resources for the current agent spec.

        Steps:
            1. Validate the current spec and resolve the chat model.
            2. Load MCP tools and retain releasable MCP runtime resources.
            3. Build the backend selector and middleware stack.
            4. Build the final system prompt and interrupt mapping.
            5. Materialize subagent configuration and compile the graph.

        Args:
            checkpointer: Optional LangGraph checkpointer for persistence.

        """
        # Runtime state is managed by `_runtime_phase()`.
        validate_agent_spec(self.spec)
        # 1. Resolve the chat model.
        extra_kwargs = self.build_model_extra_kwargs()
        result = create_model(self.spec.model, extra_kwargs=extra_kwargs or None)

        # 2. Load MCP tools and stage releasable runtime resources.
        mcp_tools, mcp_session_manager, mcp_server_infos = (
            await load_mcp_tools_from_configs(self.spec.mcp_servers)
        )
        mcp_runtime = None
        if mcp_session_manager is not None:
            mcp_runtime = MCPRuntime(
                session_manager=mcp_session_manager,
                tools=list(mcp_tools),
                server_infos=list(mcp_server_infos),
            )

        tools: list[Any] = list(mcp_tools)
        if mcp_tools:
            logger.info(
                "Loaded %d MCP tool(s) for agent '%s' from %d server(s)",
                len(mcp_tools), self.spec.name, len(mcp_server_infos),
            )

        desired_sandbox_spec = dict(self.spec.sandbox or {})
        existing_sandbox_runtime = self._sandbox_runtime
        replace_sandbox_runtime = (
            existing_sandbox_runtime is not None
            and existing_sandbox_runtime.spec != desired_sandbox_spec
        )
        sandbox_runtime = existing_sandbox_runtime
        created_sandbox_runtime: SandboxRuntime | None = None
        if replace_sandbox_runtime:
            sandbox_runtime = None
        if sandbox_runtime is None and desired_sandbox_spec:
            sandbox_runtime = await self._create_sandbox_runtime(
                spec=desired_sandbox_spec
            )
            created_sandbox_runtime = sandbox_runtime

        # 3. Build the backend selector and middleware stack.
        fallback_backend = (
            sandbox_runtime.backend
            if sandbox_runtime is not None
            else self._build_workspace_backend()
        )

        def runtime_backend_factory(tool_runtime: Any) -> Any:
            """Resolve the backend for the current tool call.

            When an invocation provides an agent-owned sandbox backend via
            runtime context, file and execute tools should use that backend.
            Otherwise the assembled agent falls back to the workspace-local
            shell backend.
            """
            sandbox_backend = None
            context = getattr(tool_runtime, "context", None)
            if isinstance(context, dict):
                sandbox_backend = context.get("sandbox_backend")
            elif context is not None:
                sandbox_backend = getattr(context, "sandbox_backend", None)

            backend = sandbox_backend or fallback_backend
            if isinstance(backend, CompositeBackend):
                return backend
            return CompositeBackend(default=backend, routes={})

        agent_middleware: list[Any] = []

        # Memory middleware
        agent_middleware.append(
            MemoryMiddleware(
                backend=FilesystemBackend(virtual_mode=False),
                sources=[str(self.registry.memory_dir(self.spec.name))],
            )
        )

        # Skills middleware
        agent_middleware.append(
            RuntimeSkillsMiddleware(
                backend=FilesystemBackend(virtual_mode=False),
                sources=[str(self.registry.skills_dir(self.spec.name))],
            )
        )

        # Expose summarization through an explicit tool-backed middleware.
        agent_middleware.append(
            SummarizationToolMiddleware(
                create_summarization_middleware(result.model, runtime_backend_factory)
            )
        )

        # 4. Build the final system prompt.
        prompt_system = self.spec.prompt.get("system", "") if self.spec.prompt else ""
        system_prompt = get_system_prompt(
            agent_name=self.spec.name,
            prompt=prompt_system,
            model=result,
            skills_dir=str(self.registry.skills_dir(self.spec.name)),
        )

        # 5. Build the interrupt_on mapping.
        if self.spec.interrupt_on:
            # Convert list[str] to dict[str, bool].
            interrupt_on: dict[str, bool | InterruptOnConfig] = {
                name: True for name in self.spec.interrupt_on
            }
        else:
            interrupt_on = _add_interrupt_on()

        # 6. Materialize subagent configuration.
        custom_subagents: list[Any] = []
        for sa_meta in self.spec.subagents:
            subagent: SubAgent = {
                "name": sa_meta["name"],
                "description": sa_meta["description"],
                "system_prompt": sa_meta["system_prompt"],
            }
            if sa_meta.get("model"):
                subagent["model"] = sa_meta["model"]
            custom_subagents.append(subagent)

        # 7. Compile the runnable graph via the SDK.
        try:
            graph = create_deep_agent(
                name=self.spec.name,
                model=result.model,
                tools=tools if tools else None,
                system_prompt=system_prompt,
                middleware=agent_middleware,
                subagents=custom_subagents if custom_subagents else None,
                backend=runtime_backend_factory,
                interrupt_on=interrupt_on,
                checkpointer=checkpointer,
            )
        except Exception:
            if created_sandbox_runtime is not None:
                await self._cleanup_sandbox_backend(created_sandbox_runtime.backend)
            if mcp_runtime is not None:
                await mcp_runtime.session_manager.cleanup()
            raise

        self._graph = graph
        self._mcp_runtime = mcp_runtime
        self._sandbox_runtime = sandbox_runtime
        if replace_sandbox_runtime and existing_sandbox_runtime is not None:
            await self._cleanup_sandbox_backend(existing_sandbox_runtime.backend)

    async def astream(self,
                      *,
                      context: Any = None,
                      message: str,
                      config: RunnableConfig,
                      hitl_handler: HITLHandler | None = None,
                      ) -> AsyncIterator[RuntimeEvent]:
        async with self._runtime_phase(
                blocked_states=("running", "releasing", "assembling"),
                enter_state="running",
                success_state="assembled",
        ):
            async for event in self._astream_impl(
                    context=context,
                    message=message,
                    config=config,
                    hitl_handler=hitl_handler,
            ):
                yield event

    async def _astream_impl(self,
                            *,
                            context: Any = None,
                            message: str,
                            config: RunnableConfig,
                            hitl_handler: HITLHandler | None = None,
                            ) -> AsyncIterator[RuntimeEvent]:
        """Stream one invocation as RuntimeEvents."""
        if self._graph is None:
            msg = f"Agent '{self.spec.name}' has not been assembled"
            raise RuntimeError(msg)

        run_id = uuid.uuid4().hex[:12]
        thread_id = ""
        configurable = config.get("configurable", {})
        if isinstance(configurable, dict):
            thread_id = str(configurable.get("thread_id", ""))
            if configurable.get("run_id"):
                run_id = str(configurable["run_id"])

        yield events.run_start(
            run_id=run_id,
            agent_name=self.spec.name,
            thread_id=thread_id,
        )

        parser_state = StreamParserState(
            run_id=run_id,
            agent_name=self.spec.name,
        )
        wall_start = time.monotonic()
        iteration = 0
        stream_input: dict[str, Any] | Any = {
            "messages": [{"role": "user", "content": message}],
        }

        async with self._sandbox_context(context) as runtime_context:
            while True:
                pending_interrupts: dict[str, Any] = {}

                async for part in self._graph.astream(
                        stream_input,
                        config=config,
                        context=runtime_context,
                        stream_mode=["messages", "updates"],
                        subgraphs=True,
                        version="v2",
                ):
                    parsed = parse_stream_part(part, parser_state)
                    pending_interrupts.update(parsed.interrupts)
                    for event in parsed.events:
                        yield event

                if not pending_interrupts:
                    break

                iteration += 1
                if iteration > _MAX_HITL_ITERATIONS:
                    msg = (
                        f"HITL loop exceeded {_MAX_HITL_ITERATIONS} iterations "
                        f"for agent '{self.spec.name}'"
                    )
                    raise RuntimeError(msg)

                hitl_response: dict[str, Any] = {}
                for interrupt_id, request in pending_interrupts.items():
                    action_requests = (
                        request.get("action_requests", [])
                        if isinstance(request, dict)
                        else []
                    )
                    yield events.hitl_request(
                        interrupt_id=interrupt_id,
                        action_requests=[dict(ar) for ar in action_requests],
                        review_configs=[
                            dict(config)
                            for config in request.get("review_configs", [])
                        ]
                        if isinstance(request, dict)
                        else [],
                        run_id=run_id,
                        agent_name=self.spec.name,
                    )

                    if hitl_handler is not None:
                        decisions = await hitl_handler({
                            "interrupt_id": interrupt_id,
                            "action_requests": action_requests,
                            "review_configs": (
                                request.get("review_configs", [])
                                if isinstance(request, dict)
                                else []
                            ),
                        })
                    else:
                        decisions = [{"type": "approve"} for _ in action_requests]

                    hitl_response[interrupt_id] = {"decisions": decisions}

                stream_input = Command(resume=hitl_response)

        wall_time = time.monotonic() - wall_start
        parser_state.stats.wall_time_seconds = wall_time

        full_text = "".join(parser_state.full_response)
        if full_text:
            yield events.text_done(
                full_text,
                run_id=run_id,
                agent_name=self.spec.name,
            )

        yield events.run_end(
            run_id=run_id,
            agent_name=self.spec.name,
            stats={
                "request_count": parser_state.stats.request_count,
                "input_tokens": parser_state.stats.input_tokens,
                "output_tokens": parser_state.stats.output_tokens,
                "wall_time_seconds": round(wall_time, 2),
            },
        )
        return

    async def release(self):
        async with self._runtime_phase(
                blocked_states=("releasing", "running", "assembling"),
                enter_state="releasing",
                success_state="released",
        ):
            await self._release_impl()

    async def _release_impl(self) -> None:
        self._graph = None

        if self._mcp_runtime is not None:
            await self._mcp_runtime.session_manager.cleanup()
            self._mcp_runtime = None

        if self._sandbox_runtime is not None:
            await self._cleanup_sandbox_backend(self._sandbox_runtime.backend)
            self._sandbox_runtime = None
