"""Agent assembly for Deep Agents clients.

This module extracts the core behavior currently baked into the Textual CLI
agent wiring so other clients (for example, a local web UI) can reuse the same
runtime semantics without drifting.

Key responsibilities:
- system prompt rendering (dynamic model identity + working directory sections)
- HITL interrupt configuration for gated tools
- backend selection (local shell, local filesystem-only, or remote sandbox)
- middleware stack assembly (memory, skills, local context, summarization)
- subagent discovery and wiring

Non-goals:
- UI rendering (Textual/Rich vs browser)
- persistence of user configuration and preferences
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from functools import partial
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from deepagents_runtime.sandboxes import get_default_working_dir

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from deepagents.backends import CompositeBackend
    from deepagents.backends.sandbox import SandboxBackendProtocol
    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain.agents.middleware import InterruptOnConfig
    from langchain.agents.middleware.types import AgentState
    from langchain.messages import ToolCall
    from langchain.tools import BaseTool
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.pregel import Pregel
    from langgraph.runtime import Runtime


_DEFAULT_GRAPH_CONFIG: dict[str, Any] = {"recursion_limit": 1000}

_TASK_DESCRIPTION_PREVIEW_MAX_CHARS = 500
_TASK_DESCRIPTION_SEPARATOR_LENGTH = 40


@runtime_checkable
class _HasWarningAndBoxHorizontal(Protocol):
    """Minimal glyph contract needed for HITL description formatting."""

    warning: str
    box_horizontal: str


@dataclass(frozen=True)
class DescriptionGlyphs:
    """UI glyphs used for tool-call descriptions in HITL prompts."""

    warning: str = "!"
    box_horizontal: str = "-"


def _coerce_description_glyphs(
    glyphs: _HasWarningAndBoxHorizontal | None,
) -> DescriptionGlyphs:
    """Normalize a user-provided glyph object into a runtime dataclass.

    Returns:
        Normalized glyphs used for tool-call descriptions.
    """
    if glyphs is None:
        return DescriptionGlyphs()
    return DescriptionGlyphs(
        warning=glyphs.warning,
        box_horizontal=glyphs.box_horizontal,
    )


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
    tool_path = cwd.as_posix()
    if re.match(r"^[a-zA-Z]:/", tool_path):
        return tool_path[2:]
    return tool_path


def _join_tool_path(base: str, suffix: str) -> str:
    """Join a virtual tool path with a relative suffix.

    Args:
        base: Base tool path starting with `/`.
        suffix: Relative path fragment to append.

    Returns:
        Joined POSIX-style tool path.
    """
    if base == "/":
        return f"/{suffix.lstrip('/')}"
    return f"{base.rstrip('/')}/{suffix.lstrip('/')}"


def _get_default_sandbox_working_dir(provider: str) -> str:
    """Back-compat alias for sandbox working dir defaults.

    Returns:
        Default working directory for the given sandbox provider.
    """
    return get_default_working_dir(provider)


def _load_system_prompt_template() -> str:
    """Load the immutable system prompt template shipped with the runtime.

    Returns:
        The system prompt template contents.
    """
    return (
        resources.files("deepagents_runtime")
        .joinpath("system_prompt.md")
        .read_text(encoding="utf-8")
    )


def get_system_prompt(
    assistant_id: str,
    *,
    sandbox_type: str | None = None,
    sandbox_working_dir: str | None = None,
    model_name: str | None = None,
    model_provider: str | None = None,
    model_context_limit: int | None = None,
    local_cwd: Path | None = None,
    skills_path: str | None = None,
) -> str:
    """Render the system prompt for an agent run.

    Args:
        assistant_id: Agent identifier, used for skills path references.
        sandbox_type: Sandbox provider type ("daytona", "langsmith", "modal",
            "runloop").
        sandbox_working_dir: Optional override for sandbox working dir. When unset
            and `sandbox_type` is provided, uses a runtime default mapping.
        model_name: Optional model name to include in the identity section.
        model_provider: Optional provider name to include in the identity section.
        model_context_limit: Optional context window size to include.
        local_cwd: Optional override for local working directory (primarily for
            tests).
        skills_path: Optional override for the displayed skills directory path.

    Returns:
        Rendered system prompt string.
    """
    template = _load_system_prompt_template()

    resolved_skills_path = skills_path or f"~/.deepagents/{assistant_id}/skills/"

    model_identity_section = ""
    if model_name:
        model_identity_section = "### Model Identity\n\n"
        model_identity_section += f"You are running as model `{model_name}`"
        if model_provider:
            model_identity_section += f" (provider: {model_provider})"
        model_identity_section += ".\n"
        if model_context_limit:
            model_identity_section += (
                f"Your context window is {model_context_limit:,} tokens.\n"
            )
        model_identity_section += "\n"

    if sandbox_type:
        working_dir = sandbox_working_dir or _get_default_sandbox_working_dir(
            sandbox_type
        )
        working_dir_section = (
            f"### Current Working Directory\n\n"
            f"You are operating in a **remote Linux sandbox** at `{working_dir}`.\n\n"
            f"All code execution and file operations happen in this sandbox "
            f"environment.\n\n"
            f"**Important:**\n"
            f"- The CLI is running locally on the user's machine, but you execute "
            f"code remotely\n"
            f"- Use `{working_dir}` as your working directory for all operations\n\n"
        )
    else:
        cwd = local_cwd or Path.cwd()
        tool_cwd = _format_local_filesystem_tool_path(cwd)
        example_path = _join_tool_path(tool_cwd, "research_project/file.md")
        working_dir_section = (
            f"### Current Working Directory\n\n"
            f"You are operating locally on the user's machine.\n\n"
            f"- Native shell working directory: `{cwd}`\n"
            f"- File tool working directory: `{tool_cwd}`\n\n"
            f"### File System and Paths\n\n"
            f"**IMPORTANT - Path Handling:**\n"
            f"- File tools (`ls`, `read_file`, `write_file`, `edit_file`, "
            f"`glob`, `grep`) must use POSIX-style absolute paths starting "
            f"with `/`\n"
            f"- On Windows, do not use drive-letter paths like `D:\\...` with "
            f"file tools\n"
            f"- Use the file tool working directory to construct file-tool "
            f"paths\n"
            f"- Example: To create a file in your working directory, "
            f"use `{example_path}`\n"
            f"- Shell commands still execute locally from `{cwd}`\n"
            f"- Never use relative paths with file tools\n\n"
        )

    return (
        template.replace("{model_identity_section}", model_identity_section)
        .replace("{working_dir_section}", working_dir_section)
        .replace("{skills_path}", resolved_skills_path)  # noqa: RUF027  # Placeholder replacement
    )


def _format_write_file_description(  # Fixed signature for InterruptOnConfig callbacks
    tool_call: ToolCall,
    _state: AgentState[Any],
    _runtime: Runtime[Any],
) -> str:
    """Format write_file tool call for approval prompt.

    Returns:
        Formatted description string for display in an approval UI.
    """
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    content = args.get("content", "")

    action = "Overwrite" if Path(file_path).exists() else "Create"
    line_count = len(content.splitlines())

    return f"File: {file_path}\nAction: {action} file\nLines: {line_count}"


def _format_edit_file_description(  # Fixed signature for InterruptOnConfig callbacks
    tool_call: ToolCall,
    _state: AgentState[Any],
    _runtime: Runtime[Any],
) -> str:
    """Format edit_file tool call for approval prompt.

    Returns:
        Formatted description string for display in an approval UI.
    """
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    replace_all = bool(args.get("replace_all", False))

    scope = "all occurrences" if replace_all else "single occurrence"
    return f"File: {file_path}\nAction: Replace text ({scope})"


def _format_web_search_description(  # Fixed signature for InterruptOnConfig callbacks
    tool_call: ToolCall,
    _state: AgentState[Any],
    _runtime: Runtime[Any],
    *,
    glyphs: _HasWarningAndBoxHorizontal | None = None,
) -> str:
    """Format web_search tool call for approval prompt.

    Returns:
        Formatted description string for display in an approval UI.
    """
    args = tool_call["args"]
    query = args.get("query", "unknown")
    max_results = args.get("max_results", 5)
    resolved_glyphs = _coerce_description_glyphs(glyphs)

    return (
        f"Query: {query}\nMax results: {max_results}\n\n"
        f"{resolved_glyphs.warning}  This will use Tavily API credits"
    )


def _format_fetch_url_description(  # Fixed signature for InterruptOnConfig callbacks
    tool_call: ToolCall,
    _state: AgentState[Any],
    _runtime: Runtime[Any],
    *,
    glyphs: _HasWarningAndBoxHorizontal | None = None,
) -> str:
    """Format fetch_url tool call for approval prompt.

    Returns:
        Formatted description string for display in an approval UI.
    """
    args = tool_call["args"]
    url = args.get("url", "unknown")
    timeout = args.get("timeout", 30)
    resolved_glyphs = _coerce_description_glyphs(glyphs)

    return (
        f"URL: {url}\nTimeout: {timeout}s\n\n"
        f"{resolved_glyphs.warning}  Will fetch and convert web content to markdown"
    )


def _format_task_description(  # Fixed signature for InterruptOnConfig callbacks
    tool_call: ToolCall,
    _state: AgentState[Any],
    _runtime: Runtime[Any],
    *,
    glyphs: _HasWarningAndBoxHorizontal | None = None,
) -> str:
    """Format task (subagent) tool call for approval prompt.

    Returns:
        Formatted description string for display in an approval UI.
    """
    args = tool_call["args"]
    description = args.get("description", "unknown")
    subagent_type = args.get("subagent_type", "unknown")
    resolved_glyphs = _coerce_description_glyphs(glyphs)

    description_preview = description
    if len(description) > _TASK_DESCRIPTION_PREVIEW_MAX_CHARS:
        description_preview = description[:_TASK_DESCRIPTION_PREVIEW_MAX_CHARS] + "..."

    separator = resolved_glyphs.box_horizontal * _TASK_DESCRIPTION_SEPARATOR_LENGTH
    warning_msg = "Subagent will have access to file operations and shell commands"
    return (
        f"Subagent Type: {subagent_type}\n\n"
        f"Task Instructions:\n"
        f"{separator}\n"
        f"{description_preview}\n"
        f"{separator}\n\n"
        f"{resolved_glyphs.warning}  {warning_msg}"
    )


def _format_execute_description(  # Fixed signature for InterruptOnConfig callbacks
    tool_call: ToolCall,
    _state: AgentState[Any],
    _runtime: Runtime[Any],
) -> str:
    """Format execute tool call for approval prompt.

    Returns:
        Formatted description string for display in an approval UI.
    """
    args = tool_call["args"]
    command = args.get("command", "N/A")
    return f"Execute Command: {command}\nWorking Directory: {Path.cwd()}"


def _add_interrupt_on(
    *,
    require_compact_tool_approval: bool = True,
    glyphs: _HasWarningAndBoxHorizontal | None = None,
) -> dict[str, InterruptOnConfig]:
    """Configure human-in-the-loop interrupt settings for gated tools.

    Args:
        require_compact_tool_approval: When `True`, compact_conversation is gated.
        glyphs: Optional UI glyphs used for formatting descriptions.

    Returns:
        Dictionary mapping tool names to their interrupt configuration.
    """
    resolved_glyphs = _coerce_description_glyphs(glyphs)

    execute_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_execute_description,  # type: ignore[typeddict-item]  # Callable description narrower than TypedDict expects
    }

    write_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_write_file_description,  # type: ignore[typeddict-item]  # Callable description narrower than TypedDict expects
    }

    edit_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_edit_file_description,  # type: ignore[typeddict-item]  # Callable description narrower than TypedDict expects
    }

    web_search_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": partial(_format_web_search_description, glyphs=resolved_glyphs),  # type: ignore[typeddict-item]  # Callable description narrower than TypedDict expects
    }

    fetch_url_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": partial(_format_fetch_url_description, glyphs=resolved_glyphs),  # type: ignore[typeddict-item]  # Callable description narrower than TypedDict expects
    }

    task_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": partial(_format_task_description, glyphs=resolved_glyphs),  # type: ignore[typeddict-item]  # Callable description narrower than TypedDict expects
    }

    interrupt_map: dict[str, InterruptOnConfig] = {
        "execute": execute_interrupt_config,
        "write_file": write_file_interrupt_config,
        "edit_file": edit_file_interrupt_config,
        "web_search": web_search_interrupt_config,
        "fetch_url": fetch_url_interrupt_config,
        "task": task_interrupt_config,
    }

    if require_compact_tool_approval:
        interrupt_map["compact_conversation"] = {
            "allowed_decisions": ["approve", "reject"],
            "description": (
                "Summarizes older messages into a shorter summary using an LLM call, "
                "then replaces them in context. Recent messages are kept as-is. Full "
                "history is written to backend storage for agent retrieval."
            ),
        }

    return interrupt_map


def create_agent(
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
    graph_config: RunnableConfig | None = None,
    memory_sources: Sequence[str] | None = None,
    skills_sources: Sequence[str] | None = None,
    user_agents_dir: Path | None = None,
    project_agents_dir: Path | None = None,
    model_name: str | None = None,
    model_provider: str | None = None,
    model_context_limit: int | None = None,
    user_langchain_project: str | None = None,
    interrupt_glyphs: _HasWarningAndBoxHorizontal | None = None,
    require_compact_tool_approval: bool = True,
) -> tuple[Pregel, CompositeBackend]:
    """Create an agent graph and its composite backend.

    This is the shared runtime entry point for assembling the same Deep Agents
    configuration across different clients.

    Args:
        model: LLM model to use (provider model string or a LangChain model).
        assistant_id: Agent identifier used for persistent paths.
        tools: Extra tools to provide to the agent.
        sandbox: Optional remote sandbox backend for execution and file ops.
        sandbox_type: Optional sandbox provider identifier for system prompt
            rendering.
        system_prompt: Optional system prompt override. When unset, a prompt is
            rendered via `get_system_prompt()`.
        auto_approve: When `True`, disables HITL interrupts for all gated tools.
        enable_memory: When `True`, includes MemoryMiddleware configured from
            `memory_sources`.
        enable_skills: When `True`, includes SkillsMiddleware configured from
            `skills_sources`.
        enable_shell: When `True` and `sandbox` is unset, uses LocalShellBackend for
            `execute` support.
        checkpointer: Optional LangGraph checkpointer.
        graph_config: Optional LangChain RunnableConfig applied to the compiled graph.
        memory_sources: Memory source file paths (required when
            `enable_memory=True`).
        skills_sources: Skill source directories (required when
            `enable_skills=True`).
        user_agents_dir: Optional directory for user subagents.
        project_agents_dir: Optional directory for project subagents.
        model_name: Optional resolved model name used for prompt identity section.
        model_provider: Optional model provider name used for prompt identity section.
        model_context_limit: Optional model context window size used for prompt
            identity section.
        user_langchain_project: Optional original LANGSMITH_PROJECT to restore in
            shell env.
        interrupt_glyphs: Optional glyph set used in HITL tool descriptions.
        require_compact_tool_approval: When `True`, compact_conversation is gated.

    Returns:
        A tuple of `(agent_graph, composite_backend)`.

    Raises:
        ValueError: If required sources are missing for enabled middleware.
    """
    tools = tools or []

    if enable_memory and memory_sources is None:
        msg = "memory_sources must be provided when enable_memory=True"
        raise ValueError(msg)

    if enable_skills and skills_sources is None:
        msg = "skills_sources must be provided when enable_skills=True"
        raise ValueError(msg)

    from deepagents_runtime.subagents import list_subagents

    custom_subagents: list[SubAgent | CompiledSubAgent] = []
    for subagent_meta in list_subagents(
        user_agents_dir=user_agents_dir,
        project_agents_dir=project_agents_dir,
    ):
        subagent: SubAgent = {
            "name": subagent_meta["name"],
            "description": subagent_meta["description"],
            "system_prompt": subagent_meta["system_prompt"],
        }
        if subagent_meta["model"]:
            subagent["model"] = subagent_meta["model"]
        custom_subagents.append(subagent)

    agent_middleware: list[Any] = []

    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.middleware import MemoryMiddleware, SkillsMiddleware

    if enable_memory:
        agent_middleware.append(
            MemoryMiddleware(
                backend=FilesystemBackend(),
                sources=list(memory_sources or []),
            )
        )

    if enable_skills:
        agent_middleware.append(
            SkillsMiddleware(
                backend=FilesystemBackend(),
                sources=list(skills_sources or []),
            )
        )

    from deepagents.backends import CompositeBackend, LocalShellBackend

    if sandbox is None:
        if enable_shell:
            shell_env = os.environ.copy()
            if user_langchain_project:
                shell_env["LANGSMITH_PROJECT"] = user_langchain_project

            backend = LocalShellBackend(
                root_dir=Path.cwd(),
                inherit_env=True,
                env=shell_env,
            )
        else:
            backend = FilesystemBackend()
    else:
        backend = sandbox

    from deepagents_runtime.local_context import (
        LocalContextMiddleware,
        _ExecutableBackend,
    )

    if isinstance(backend, _ExecutableBackend):
        agent_middleware.append(LocalContextMiddleware(backend=backend))

    if system_prompt is None:
        system_prompt = get_system_prompt(
            assistant_id,
            sandbox_type=sandbox_type,
            model_name=model_name,
            model_provider=model_provider,
            model_context_limit=model_context_limit,
        )

    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None
    if auto_approve:
        interrupt_on = {}
    else:
        interrupt_on = _add_interrupt_on(
            require_compact_tool_approval=require_compact_tool_approval,
            glyphs=interrupt_glyphs,
        )

    if sandbox is None:
        large_results_backend = FilesystemBackend(
            root_dir=tempfile.mkdtemp(prefix="deepagents_large_results_"),
            virtual_mode=True,
        )
        conversation_history_backend = FilesystemBackend(
            root_dir=tempfile.mkdtemp(prefix="deepagents_conversation_history_"),
            virtual_mode=True,
        )
        composite_backend = CompositeBackend(
            default=backend,
            routes={
                "/large_tool_results/": large_results_backend,
                "/conversation_history/": conversation_history_backend,
            },
        )
    else:
        composite_backend = CompositeBackend(
            default=backend,
            routes={},
        )

    from deepagents.graph import resolve_model

    resolved_model = resolve_model(model)

    from deepagents.middleware.summarization import (
        SummarizationToolMiddleware,
        create_summarization_middleware,
    )

    agent_middleware.append(
        SummarizationToolMiddleware(
            create_summarization_middleware(resolved_model, composite_backend)
        )
    )

    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import InMemorySaver

    final_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
    agent = create_deep_agent(
        model=resolved_model,
        system_prompt=system_prompt,
        tools=tools,
        backend=composite_backend,
        middleware=agent_middleware,
        interrupt_on=interrupt_on,
        checkpointer=final_checkpointer,
        subagents=custom_subagents or None,
    ).with_config(graph_config or _DEFAULT_GRAPH_CONFIG)

    return agent, composite_backend


__all__ = [
    "DescriptionGlyphs",
    "create_agent",
    "get_system_prompt",
]
