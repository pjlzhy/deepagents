"""Agent management and creation for the CLI."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from deepagents.backends import CompositeBackend
    from deepagents.backends.sandbox import SandboxBackendProtocol
    from langchain.agents.middleware import InterruptOnConfig
    from langchain.agents.middleware.types import AgentState
    from langchain.messages import ToolCall
    from langchain.tools import BaseTool
    from langchain_core.language_models import BaseChatModel
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.pregel import Pregel
    from langgraph.runtime import Runtime

from deepagents_cli.config import (
    COLORS,
    config,
    console,
    get_default_coding_instructions,
    get_glyphs,
    settings,
)

DEFAULT_AGENT_NAME = "agent"
"""The default agent name used when no `-a` flag is provided."""

REQUIRE_COMPACT_TOOL_APPROVAL: bool = True
"""When `True`, `compact_conversation` requires HITL approval like other gated tools."""


def _format_local_filesystem_tool_path(cwd: Path) -> str:
    """Convert the local working directory into the file-tool path contract.

    File tools in Deep Agents use POSIX-style absolute paths starting with `/`,
    even on Windows. This helper converts a native local cwd into the form that
    the file tools actually accept.

    Args:
        cwd: Native current working directory path.

    Returns:
        Path string suitable for filesystem tools.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._format_local_filesystem_tool_path(cwd)


def _join_tool_path(base: str, suffix: str) -> str:
    """Join a virtual tool path with a relative suffix.

    Args:
        base: Base tool path starting with `/`.
        suffix: Relative path fragment to append.

    Returns:
        Joined POSIX-style tool path.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._join_tool_path(base, suffix)


def list_agents() -> None:
    """List all available agents."""
    agents_dir = settings.user_deepagents_dir

    if not agents_dir.exists() or not any(agents_dir.iterdir()):
        console.print("[yellow]No agents found.[/yellow]")
        console.print(
            "[dim]Agents will be created in ~/.deepagents/ "
            "when you first use them.[/dim]",
            style=COLORS["dim"],
        )
        return

    console.print("\n[bold]Available Agents:[/bold]\n", style=COLORS["primary"])

    for agent_path in sorted(agents_dir.iterdir()):
        if agent_path.is_dir():
            agent_name = agent_path.name
            agent_md = agent_path / "AGENTS.md"
            is_default = agent_name == DEFAULT_AGENT_NAME
            default_label = " [dim](default)[/dim]" if is_default else ""

            bullet = get_glyphs().bullet
            if agent_md.exists():
                console.print(
                    f"  {bullet} [bold]{agent_name}[/bold]{default_label}",
                    style=COLORS["primary"],
                )
                console.print(f"    {agent_path}", style=COLORS["dim"])
            else:
                console.print(
                    f"  {bullet} [bold]{agent_name}[/bold]{default_label}"
                    " [dim](incomplete)[/dim]",
                    style=COLORS["tool"],
                )
                console.print(f"    {agent_path}", style=COLORS["dim"])

    console.print()


def reset_agent(agent_name: str, source_agent: str | None = None) -> None:
    """Reset an agent to default or copy from another agent."""
    agents_dir = settings.user_deepagents_dir
    agent_dir = agents_dir / agent_name

    if source_agent:
        source_dir = agents_dir / source_agent
        source_md = source_dir / "AGENTS.md"

        if not source_md.exists():
            console.print(
                f"[bold red]Error:[/bold red] Source agent '{source_agent}' not found "
                "or has no AGENTS.md"
            )
            return

        source_content = source_md.read_text(encoding="utf-8")
        action_desc = f"contents of agent '{source_agent}'"
    else:
        source_content = get_default_coding_instructions()
        action_desc = "default"

    if agent_dir.exists():
        shutil.rmtree(agent_dir)
        console.print(
            f"Removed existing agent directory: {agent_dir}", style=COLORS["tool"]
        )

    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_md = agent_dir / "AGENTS.md"
    agent_md.write_text(source_content)

    console.print(
        f"{get_glyphs().checkmark} Agent '{agent_name}' reset to {action_desc}",
        style=COLORS["primary"],
    )
    console.print(f"Location: {agent_dir}\n", style=COLORS["dim"])


def get_system_prompt(assistant_id: str, sandbox_type: str | None = None) -> str:
    """Get the base system prompt for the agent.

    Loads the immutable system prompt from `system_prompt.md` and
    interpolates dynamic sections (model identity, working directory,
    skills path).

    Args:
        assistant_id: The agent identifier for path references
        sandbox_type: Type of sandbox provider
            (`'daytona'`, `'langsmith'`, `'modal'`, `'runloop'`).

            If `None`, agent is operating in local mode.

    Returns:
        The system prompt string

    Example:
        ```txt
        You are running as model {MODEL} (provider: {PROVIDER}).

        Your context window is {CONTEXT_WINDOW} tokens.

        ... {CONDITIONAL SECTIONS} ...
        ```
    """
    from deepagents_runtime.agent_factory import (
        get_system_prompt as _runtime_get_system_prompt,
    )

    return _runtime_get_system_prompt(
        assistant_id,
        sandbox_type=sandbox_type,
        model_name=settings.model_name,
        model_provider=settings.model_provider,
        model_context_limit=settings.model_context_limit,
        local_cwd=Path.cwd(),
    )


def _format_write_file_description(
    tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any]
) -> str:
    """Format write_file tool call for approval prompt.

    Returns:
        Formatted description string for the write_file tool call.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._format_write_file_description(
        tool_call,
        _state,
        _runtime,
    )


def _format_edit_file_description(
    tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any]
) -> str:
    """Format edit_file tool call for approval prompt.

    Returns:
        Formatted description string for the edit_file tool call.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._format_edit_file_description(
        tool_call,
        _state,
        _runtime,
    )


def _format_web_search_description(
    tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any]
) -> str:
    """Format web_search tool call for approval prompt.

    Returns:
        Formatted description string for the web_search tool call.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._format_web_search_description(
        tool_call,
        _state,
        _runtime,
        glyphs=get_glyphs(),
    )


def _format_fetch_url_description(
    tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any]
) -> str:
    """Format fetch_url tool call for approval prompt.

    Returns:
        Formatted description string for the fetch_url tool call.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._format_fetch_url_description(
        tool_call,
        _state,
        _runtime,
        glyphs=get_glyphs(),
    )


def _format_task_description(
    tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any]
) -> str:
    """Format task (subagent) tool call for approval prompt.

    The task tool signature is: task(description: str, subagent_type: str)
    The description contains all instructions that will be sent to the subagent.

    Returns:
        Formatted description string for the task tool call.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._format_task_description(
        tool_call,
        _state,
        _runtime,
        glyphs=get_glyphs(),
    )


def _format_execute_description(
    tool_call: ToolCall, _state: AgentState[Any], _runtime: Runtime[Any]
) -> str:
    """Format execute tool call for approval prompt.

    Returns:
        Formatted description string for the execute tool call.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._format_execute_description(
        tool_call,
        _state,
        _runtime,
    )


def _add_interrupt_on() -> dict[str, InterruptOnConfig]:
    """Configure human-in-the-loop interrupt settings for all gated tools.

    Every tool that can have side effects or access external resources
    (shell execution, file writes/edits, web search, URL fetch, task
    delegation) is gated behind an approval prompt unless auto-approve
    is enabled.

    Returns:
        Dictionary mapping tool names to their interrupt configuration.
    """
    import deepagents_runtime.agent_factory as runtime_agent_factory

    return runtime_agent_factory._add_interrupt_on(
        require_compact_tool_approval=REQUIRE_COMPACT_TOOL_APPROVAL,
        glyphs=get_glyphs(),
    )


def create_cli_agent(
    model: str | BaseChatModel,
    assistant_id: str,
    *,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    system_prompt: str | None = None,
    auto_approve: bool = False,
    enable_memory: bool = True,
    enable_skills: bool = True,
    enable_shell: bool = True,
    checkpointer: BaseCheckpointSaver | None = None,
) -> tuple[Pregel, CompositeBackend]:
    """Create a CLI-configured agent with flexible options.

    This is the main entry point for creating a deepagents CLI agent, usable
    both internally and from external code (e.g., benchmarking frameworks).

    Args:
        model: LLM model to use (e.g., `'anthropic:claude-sonnet-4-6'`)
        assistant_id: Agent identifier for memory/state storage
        tools: Additional tools to provide to agent
        sandbox: Optional sandbox backend for remote execution
            (e.g., `ModalBackend`).

            If `None`, uses local filesystem + shell.
        sandbox_type: Type of sandbox provider
            (`'daytona'`, `'langsmith'`, `'modal'`, `'runloop'`).
            Used for system prompt generation.
        system_prompt: Override the default system prompt.

            If `None`, generates one based on `sandbox_type` and `assistant_id`.
        auto_approve: If `True`, no tools trigger human-in-the-loop
            interrupts — all calls (shell execution, file writes/edits,
            web search, URL fetch) run automatically.

            If `False`, tools pause for user confirmation via the approval menu.
            See `_add_interrupt_on` for the full list of gated tools.
        enable_memory: Enable `MemoryMiddleware` for persistent memory
        enable_skills: Enable `SkillsMiddleware` for custom agent skills
        enable_shell: Enable shell execution via `LocalShellBackend`
            (only in local mode). When enabled, the `execute` tool is available.
        checkpointer: Optional checkpointer for session persistence.

            If `None`, uses `InMemorySaver` (no persistence across
            CLI invocations).

    Returns:
        2-tuple of `(agent_graph, backend)`

            - `agent_graph`: Configured LangGraph Pregel instance ready
                for execution
                - `composite_backend`: `CompositeBackend` for file operations
    """
    tools = tools or []

    if enable_memory or enable_skills:
        agent_dir = settings.ensure_agent_dir(assistant_id)
        agent_md = agent_dir / "AGENTS.md"
        if not agent_md.exists():
            # Create empty file for user customizations; base instructions are loaded
            # fresh from the system prompt template.
            agent_md.touch()

    memory_sources: list[str] | None = None
    if enable_memory:
        memory_sources = [str(settings.get_user_agent_md_path(assistant_id))]
        memory_sources.extend(str(p) for p in settings.get_project_agent_md_path())

    skills_sources: list[str] | None = None
    if enable_skills:
        skills_dir = settings.ensure_user_skills_dir(assistant_id)
        user_agent_skills_dir = settings.get_user_agent_skills_dir()
        project_skills_dir = settings.get_project_skills_dir()
        project_agent_skills_dir = settings.get_project_agent_skills_dir()

        skills_sources = [
            str(settings.get_built_in_skills_dir()),
            str(skills_dir),
            str(user_agent_skills_dir),
        ]
        if project_skills_dir:
            skills_sources.append(str(project_skills_dir))
        if project_agent_skills_dir:
            skills_sources.append(str(project_agent_skills_dir))

    from deepagents_runtime.agent_factory import create_agent

    return create_agent(
        model=model,
        assistant_id=assistant_id,
        tools=tools,
        sandbox=sandbox,
        sandbox_type=sandbox_type,
        system_prompt=system_prompt,
        auto_approve=auto_approve,
        enable_memory=enable_memory,
        enable_skills=enable_skills,
        enable_shell=enable_shell,
        checkpointer=checkpointer,
        graph_config=config,
        memory_sources=memory_sources,
        skills_sources=skills_sources,
        user_agents_dir=settings.get_user_agents_dir(assistant_id),
        project_agents_dir=settings.get_project_agents_dir(),
        model_name=settings.model_name,
        model_provider=settings.model_provider,
        model_context_limit=settings.model_context_limit,
        user_langchain_project=settings.user_langchain_project,
        interrupt_glyphs=get_glyphs(),
        require_compact_tool_approval=REQUIRE_COMPACT_TOOL_APPROVAL,
    )
