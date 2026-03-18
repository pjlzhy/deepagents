"""AgentSpec → AgentTemplate assembly.

Resolves all referenced resources (skills, MCPs, model, subagents) from
the spec and SDK, then builds a compiled LangGraph agent.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from langchain.agents.middleware import InterruptOnConfig
from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langgraph.runtime import Runtime

from deepagents_runtime.manager.registry import Registry
from deepagents_runtime.models import ModelResult, create_model
from deepagents_runtime.spec import AgentSpec, AgentTemplate

logger = logging.getLogger(__name__)

REQUIRE_COMPACT_TOOL_APPROVAL: bool = True
"""When ``True``, ``compact_conversation`` requires HITL approval."""

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


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


async def assemble(
    spec: AgentSpec,
    registry: Registry,
    *,
    checkpointer: Any = None,
    _assembling: frozenset[str] = frozenset(),
) -> AgentTemplate:
    """Assemble an ``AgentSpec`` into an ``AgentTemplate``.

    Steps:
        1. Create the model via ``create_model(spec.model)``.
        2. Load MCP tools from ``spec.mcp_servers``.
        3. Build middleware stack (Memory, Skills, Summarization).
        4. Construct system prompt.
        5. Build ``interrupt_on`` mapping.
        6. Resolve subagents (with cycle detection).
        7. Create backend (``LocalShellBackend`` + ``CompositeBackend``).
        8. Call SDK ``create_deep_agent()`` to build the compiled graph.

    Args:
        spec: The agent specification to assemble.
        registry: Registry instance (for subagent spec lookup).
        checkpointer: Optional LangGraph checkpointer for persistence.
        _assembling: Internal — agent names currently being assembled.
            Used for circular-dependency detection.  Callers should not
            pass this parameter.

    Returns:
        ``AgentTemplate`` ready for execution.

    Raises:
        ValueError: If a circular dependency is detected or a referenced
            subagent is not found in the registry.
    """
    # ── 0. Cycle detection ──
    if spec.name in _assembling:
        msg = (
            f"Circular subagent dependency detected: "
            f"'{spec.name}' is already being assembled. "
            f"Chain: {' → '.join(_assembling)} → {spec.name}"
        )
        raise ValueError(msg)
    assembling = _assembling | {spec.name}

    # ── 1. Create model ──
    extra_kwargs: dict[str, Any] = {}
    if spec.model_config:
        if spec.model_config.get("base_url"):
            extra_kwargs["base_url"] = spec.model_config["base_url"]
        if spec.model_config.get("api_key"):
            extra_kwargs["api_key"] = spec.model_config["api_key"]
        elif spec.model_config.get("api_key_env"):
            env_val = os.environ.get(spec.model_config["api_key_env"])
            if env_val:
                extra_kwargs["api_key"] = env_val
        if spec.model_config.get("extra_params"):
            extra_kwargs.update(spec.model_config["extra_params"])
    result = create_model(spec.model, extra_kwargs=extra_kwargs or None)

    # ── 2. Load MCP tools ──
    from deepagents_runtime.mcp_tool import MCPSessionManager, load_mcp_tools_from_configs

    mcp_tools, mcp_session_manager, mcp_server_infos = (
        await load_mcp_tools_from_configs(spec.mcp_servers)
    )

    tools: list[Any] = list(mcp_tools)
    if mcp_tools:
        logger.info(
            "Loaded %d MCP tool(s) for agent '%s' from %d server(s)",
            len(mcp_tools), spec.name, len(mcp_server_infos),
        )

    # ── 3. Build middleware stack ──
    from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend
    from deepagents.middleware.memory import MemoryMiddleware
    from deepagents.middleware.skills import SkillsMiddleware
    from deepagents.middleware.summarization import (
        SummarizationToolMiddleware,
        create_summarization_middleware,
    )

    backend = LocalShellBackend(
        root_dir=str(registry.workspace_dir(spec.name)),
        inherit_env=True,
    )

    composite_backend = CompositeBackend(
        default=backend,
        routes={},
    )

    agent_middleware: list[Any] = []

    # Memory middleware
    agent_middleware.append(
        MemoryMiddleware(
            backend=FilesystemBackend(),
            sources=[str(registry.memory_dir(spec.name))],
        )
    )

    # Skills middleware
    agent_middleware.append(
        SkillsMiddleware(
            backend=FilesystemBackend(),
            sources=[str(registry.skills_dir(spec.name))],
        )
    )

    # 手动摘要工具中间件，通过prompt调用工具触发
    agent_middleware.append(
        SummarizationToolMiddleware(
            create_summarization_middleware(result.model, composite_backend)
        )
    )

    # ── 4. System prompt ──
    prompt_system = spec.prompt.get("system", "") if spec.prompt else ""
    system_prompt = get_system_prompt(
        agent_name=spec.name,
        prompt=prompt_system,
        model=result,
        skills_dir=str(registry.skills_dir(spec.name)),
    )

    # ── 5. interrupt_on ──
    if spec.interrupt_on:
        # Convert list[str] → dict[str, bool]
        interrupt_on: dict[str, bool | InterruptOnConfig] = {
            name: True for name in spec.interrupt_on
        }
    else:
        interrupt_on = _add_interrupt_on()

    # ── 6. Subagents ──
    from deepagents.middleware.subagents import SubAgent

    custom_subagents: list[Any] = []
    for sa_meta in spec.subagents:
        subagent: SubAgent = {
            "name": sa_meta["name"],
            "description": sa_meta["description"],
            "system_prompt": sa_meta["system_prompt"],
        }
        if sa_meta.get("model"):
            subagent["model"] = sa_meta["model"]
        custom_subagents.append(subagent)

    # ── 7. Build compiled graph via SDK ──
    from deepagents.graph import create_deep_agent

    graph = create_deep_agent(
        name=spec.name,
        model=result.model,
        tools=tools if tools else None,
        system_prompt=system_prompt,
        middleware=agent_middleware,
        subagents=custom_subagents if custom_subagents else None,
        backend=composite_backend,
        interrupt_on=interrupt_on,
        checkpointer=checkpointer,
    )

    return AgentTemplate(
        graph=graph,
        sandbox_spec=spec.sandbox or {},
        mcp_configs=spec.mcp_servers,
        resolved_spec=spec,
    )
