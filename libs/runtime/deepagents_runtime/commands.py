"""Shared slash-command parsing and formatting helpers."""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import uuid
from dataclasses import dataclass
from typing import Literal, TypeAlias

from deepagents_runtime import tracing
from deepagents_runtime.runs import format_token_count

logger = logging.getLogger(__name__)

CommandKind = Literal[
    "quit",
    "help",
    "open_url",
    "version",
    "clear",
    "compact",
    "threads",
    "trace",
    "tokens",
    "remember",
    "model_selector",
    "model_switch",
    "model_set_default",
    "model_clear_default",
    "model_default_usage",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """Normalized representation of one slash command."""

    kind: CommandKind
    command: str
    normalized: str
    argument: str | None = None
    url_key: str | None = None


ActionKind = Literal[
    "exit",
    "open_url",
    "show_message",
    "clear_conversation",
    "set_thread",
    "show_thread_selector",
    "show_model_selector",
    "compact_thread",
    "switch_model",
    "set_default_model",
    "clear_default_model",
    "submit_user_message",
]


@dataclass(frozen=True, slots=True)
class ExitAction:
    """Exit the current client session."""

    kind: Literal["exit"] = "exit"


@dataclass(frozen=True, slots=True)
class OpenUrlAction:
    """Open a URL in the user's browser (when supported by the client)."""

    url: str
    kind: Literal["open_url"] = "open_url"


@dataclass(frozen=True, slots=True)
class ShowMessageAction:
    """Render a message to the user."""

    message: str
    kind: Literal["show_message"] = "show_message"
    style: str | None = None
    link_url: str | None = None


@dataclass(frozen=True, slots=True)
class SubmitUserMessageAction:
    """Submit a message through the normal agent/user message path."""

    message: str
    kind: Literal["submit_user_message"] = "submit_user_message"


@dataclass(frozen=True, slots=True)
class ClearConversationAction:
    """Clear the current conversation view and reset client-side state."""

    kind: Literal["clear_conversation"] = "clear_conversation"


@dataclass(frozen=True, slots=True)
class SetThreadAction:
    """Set the active thread identifier for subsequent agent runs."""

    thread_id: str
    kind: Literal["set_thread"] = "set_thread"


@dataclass(frozen=True, slots=True)
class ShowThreadSelectorAction:
    """Request that the client open its thread selector UI."""

    kind: Literal["show_thread_selector"] = "show_thread_selector"


@dataclass(frozen=True, slots=True)
class ShowModelSelectorAction:
    """Request that the client open its model selector UI."""

    kind: Literal["show_model_selector"] = "show_model_selector"


@dataclass(frozen=True, slots=True)
class CompactThreadAction:
    """Request that the client compact/summarize the current thread."""

    kind: Literal["compact_thread"] = "compact_thread"


@dataclass(frozen=True, slots=True)
class SwitchModelAction:
    """Request that the client switch to a new model spec."""

    model_spec: str
    kind: Literal["switch_model"] = "switch_model"


@dataclass(frozen=True, slots=True)
class SetDefaultModelAction:
    """Request that the client set the default model spec."""

    model_spec: str
    kind: Literal["set_default_model"] = "set_default_model"


@dataclass(frozen=True, slots=True)
class ClearDefaultModelAction:
    """Request that the client clear its default model."""

    kind: Literal["clear_default_model"] = "clear_default_model"


CommandAction: TypeAlias = (
    ExitAction
    | OpenUrlAction
    | ShowMessageAction
    | SubmitUserMessageAction
    | ClearConversationAction
    | SetThreadAction
    | ShowThreadSelectorAction
    | ShowModelSelectorAction
    | CompactThreadAction
    | SwitchModelAction
    | SetDefaultModelAction
    | ClearDefaultModelAction
)


@dataclass(frozen=True, slots=True)
class CommandExecution:
    """UI-neutral result for one slash command."""

    echo_command: bool
    actions: tuple[CommandAction, ...]


_CHANGELOG_URL = (
    "https://github.com/langchain-ai/deepagents/blob/main/libs/cli/CHANGELOG.md"
)
_FEEDBACK_URL = "https://github.com/langchain-ai/deepagents/issues/new/choose"
_MODEL_DEFAULT_USAGE_TEXT = (
    "Usage: /model --default provider:model\n       /model --default --clear"
)

REMEMBER_PROMPT = """Review our conversation and capture valuable knowledge. Focus especially on **best practices** we discussed or discovered—these are the most important things to preserve.

## Step 1: Identify Best Practices and Key Learnings

Scan the conversation for:

### Best Practices (highest priority)
- **Patterns that worked well** - approaches, techniques, or solutions we found effective
- **Anti-patterns to avoid** - mistakes, gotchas, or approaches that caused problems
- **Quality standards** - criteria we established for good code, documentation, or processes
- **Decision rationale** - why we chose one approach over another

### Other Valuable Knowledge
- Coding conventions and style preferences
- Project architecture decisions
- Workflows and processes we developed
- Tools, libraries, or techniques worth remembering
- Feedback I gave about your behavior or outputs

## Step 2: Decide Where to Store Each Learning

For each best practice or learning, choose the right destination:

### -> Memory (AGENTS.md) for preferences and guidelines
Use memory when the knowledge is:
- A preference or guideline (not a multi-step process)
- Something to always keep in mind
- A simple rule or pattern

**Global** (`~/.deepagents/agent/AGENTS.md`): Universal preferences across all projects
**Project** (`.deepagents/AGENTS.md`): Project-specific conventions and decisions

### -> Skill for reusable workflows and methodologies
**Create a skill when** we developed:
- A multi-step process worth reusing
- A methodology for a specific type of task
- A workflow with best practices baked in
- A procedure that should be followed consistently

Skills are more powerful than memory entries because they can encode **how** to do something well, not just **what** to remember.

## Step 3: Create Skills for Significant Best Practices

If we established best practices around a workflow or process, capture them in a skill.

**Example:** If we discussed best practices for code review, create a `code-review` skill that encodes those practices into a reusable workflow.

### Skill Location
`~/.deepagents/agent/skills/<skill-name>/SKILL.md`

### Skill Structure
```
skill-name/
├── SKILL.md          (required - main instructions with best practices)
├── scripts/          (optional - executable code)
├── references/       (optional - detailed documentation)
└── assets/           (optional - templates, examples)
```

### SKILL.md Format
```markdown
---
name: skill-name
description: "What this skill does AND when to use it. Include triggers like 'when the user asks to X' or 'when working with Y'. This description determines when the skill activates."
---

# Skill Name

## Overview
Brief explanation of what this skill accomplishes.

## Best Practices
Capture the key best practices upfront:
- Best practice 1: explanation
- Best practice 2: explanation

## Process
Step-by-step instructions (imperative form):
1. First, do X
2. Then, do Y
3. Finally, do Z

## Common Pitfalls
- Pitfall to avoid and why
- Another anti-pattern we discovered
```

### Key Principles
1. **Encode best practices prominently** - Put them near the top so they guide the entire workflow
2. **Concise is key** - Only include non-obvious knowledge. Every paragraph should justify its token cost.
3. **Clear triggers** - The description determines when the skill activates. Be specific.
4. **Imperative form** - Write as commands: "Create a file" not "You should create a file"
5. **Include anti-patterns** - What NOT to do is often as valuable as what to do

## Step 4: Update Memory for Simpler Learnings

For preferences, guidelines, and simple rules that don't warrant a full skill:

```markdown
## Best Practices
- When doing X, always Y because Z
- Avoid A because it leads to B
```

Use `edit_file` to update existing files or `write_file` to create new ones.

## Step 5: Summarize Changes

List what you captured and where you stored it:
- Skills created (with key best practices encoded)
- Memory entries added (with location)
"""  # noqa: E501


def _generate_thread_id() -> str:
    """Generate a new 8-character hexadecimal thread ID.

    Returns:
        New thread identifier.
    """
    return uuid.uuid4().hex[:8]


def parse_slash_command(command: str) -> ParsedCommand:
    """Parse a slash command into a structured runtime result.

    Args:
        command: Raw slash command entered by the user.

    Returns:
        Structured command result with normalized kind and any payload.
    """
    stripped = command.strip()
    normalized = stripped.lower()

    if normalized in {"/quit", "/q"}:
        return ParsedCommand("quit", stripped, normalized)

    if normalized == "/help":
        return ParsedCommand("help", stripped, normalized)

    if normalized in {"/changelog", "/docs", "/feedback"}:
        return ParsedCommand(
            "open_url",
            stripped,
            normalized,
            url_key=normalized,
        )

    if normalized == "/version":
        return ParsedCommand("version", stripped, normalized)

    if normalized == "/clear":
        return ParsedCommand("clear", stripped, normalized)

    if normalized == "/compact":
        return ParsedCommand("compact", stripped, normalized)

    if normalized == "/threads":
        return ParsedCommand("threads", stripped, normalized)

    if normalized == "/trace":
        return ParsedCommand("trace", stripped, normalized)

    if normalized == "/tokens":
        return ParsedCommand("tokens", stripped, normalized)

    if normalized == "/remember":
        return ParsedCommand("remember", stripped, normalized)

    if normalized.startswith("/remember "):
        return ParsedCommand(
            "remember",
            stripped,
            normalized,
            argument=stripped[len("/remember ") :].strip() or None,
        )

    if normalized == "/model":
        return ParsedCommand("model_selector", stripped, normalized)

    if normalized.startswith("/model "):
        raw_arg = stripped[len("/model ") :].strip()
        lowered_arg = raw_arg.lower()
        if lowered_arg.startswith("--default"):
            default_arg = raw_arg[len("--default") :].strip() or None
            if default_arg is None:
                return ParsedCommand("model_default_usage", stripped, normalized)
            if default_arg.lower() == "--clear":
                return ParsedCommand("model_clear_default", stripped, normalized)
            return ParsedCommand(
                "model_set_default",
                stripped,
                normalized,
                argument=default_arg,
            )
        return ParsedCommand(
            "model_switch",
            stripped,
            normalized,
            argument=raw_arg or None,
        )

    return ParsedCommand("unknown", stripped, normalized)


def resolve_command_url(url_key: str, *, docs_url: str) -> str | None:
    """Resolve a slash command URL key into a concrete URL.

    Args:
        url_key: Normalized url key returned by `parse_slash_command`.
        docs_url: Docs URL to use for `/docs`.

    Returns:
        Resolved URL string, or `None` if unknown/unavailable.
    """
    if url_key == "/docs":
        return docs_url or None
    if url_key == "/changelog":
        return _CHANGELOG_URL
    if url_key == "/feedback":
        return _FEEDBACK_URL
    return None


def execute_parsed_slash_command(
    parsed: ParsedCommand,
    *,
    docs_url: str,
    client_label: str = "deepagents-cli",
    client_version: str | None = None,
    current_context: int = 0,
    model_name: str | None = None,
    context_limit: int | None = None,
    conversation_line: str | None = None,
) -> CommandExecution | None:
    """Execute a parsed slash command into UI-neutral actions.

    This is the seam that allows multiple clients (Textual, web) to share the
    same command semantics without duplicating the mapping logic in each UI.

    Args:
        parsed: Parsed command from `parse_slash_command`.
        docs_url: Docs URL used in help output and `/docs` resolution.
        client_label: Client label used for `/version`.
        client_version: Client version string used for `/version`.
        current_context: Token usage (total), used for `/tokens`.
        model_name: Model name, used for `/tokens`.
        context_limit: Model context limit, used for `/tokens`.
        conversation_line: Optional extra token line, used for `/tokens`.

    Returns:
        `CommandExecution` for commands owned by the shared runtime, or `None`
        when the caller should handle the command locally.
    """
    if parsed.kind == "quit":
        return CommandExecution(echo_command=False, actions=(ExitAction(),))

    if parsed.kind == "help":
        return CommandExecution(
            echo_command=True,
            actions=(
                ShowMessageAction(
                    build_help_text(docs_url),
                    style="dim italic",
                    link_url=docs_url,
                ),
            ),
        )

    if parsed.kind == "open_url" and parsed.url_key is not None:
        url = resolve_command_url(parsed.url_key, docs_url=docs_url)
        if url is None:
            return CommandExecution(
                echo_command=True,
                actions=(ShowMessageAction(f"Unknown command: {parsed.normalized}"),),
            )
        return CommandExecution(echo_command=True, actions=(OpenUrlAction(url),))

    if parsed.kind == "clear":
        new_thread_id = _generate_thread_id()
        return CommandExecution(
            echo_command=False,
            actions=(
                ClearConversationAction(),
                SetThreadAction(new_thread_id),
                ShowMessageAction(f"Started new thread: {new_thread_id}"),
            ),
        )

    if parsed.kind == "threads":
        return CommandExecution(
            echo_command=False,
            actions=(ShowThreadSelectorAction(),),
        )

    if parsed.kind == "compact":
        return CommandExecution(
            echo_command=True,
            actions=(CompactThreadAction(),),
        )

    if parsed.kind == "model_selector":
        return CommandExecution(
            echo_command=False,
            actions=(ShowModelSelectorAction(),),
        )

    if parsed.kind == "model_switch" and parsed.argument is not None:
        return CommandExecution(
            echo_command=True,
            actions=(SwitchModelAction(parsed.argument),),
        )

    if parsed.kind == "model_set_default" and parsed.argument is not None:
        return CommandExecution(
            echo_command=True,
            actions=(SetDefaultModelAction(parsed.argument),),
        )

    if parsed.kind == "model_clear_default":
        return CommandExecution(
            echo_command=True,
            actions=(ClearDefaultModelAction(),),
        )

    if parsed.kind == "remember":
        prompt = build_remember_prompt(REMEMBER_PROMPT, parsed.argument)
        return CommandExecution(
            echo_command=False,
            actions=(SubmitUserMessageAction(prompt),),
        )

    if parsed.kind == "version":
        message = build_version_message(
            client_label=client_label,
            client_version=client_version,
        )
        return CommandExecution(
            echo_command=True,
            actions=(ShowMessageAction(message),),
        )

    if parsed.kind == "tokens":
        message = build_token_usage_message(
            current_context=current_context,
            model_name=model_name,
            context_limit=context_limit,
            conversation_line=conversation_line,
        )
        return CommandExecution(
            echo_command=True,
            actions=(ShowMessageAction(message),),
        )

    if parsed.kind == "model_default_usage":
        return CommandExecution(
            echo_command=True,
            actions=(ShowMessageAction(_MODEL_DEFAULT_USAGE_TEXT),),
        )

    if parsed.kind == "unknown":
        return CommandExecution(
            echo_command=True,
            actions=(ShowMessageAction(f"Unknown command: {parsed.normalized}"),),
        )

    return None


async def execute_parsed_slash_command_async(
    parsed: ParsedCommand,
    *,
    docs_url: str,
    thread_id: str | None = None,
    client_label: str = "deepagents-cli",
    client_version: str | None = None,
    current_context: int = 0,
    model_name: str | None = None,
    context_limit: int | None = None,
    conversation_line: str | None = None,
) -> CommandExecution | None:
    """Async command executor that can perform I/O without blocking the caller.

    The sync `execute_parsed_slash_command` is intentionally pure and fast. Some
    commands (currently `/trace`) require URL resolution that may involve a
    network call to LangSmith. This async wrapper performs that work in a
    background thread while still returning UI-neutral actions.

    Args:
        parsed: Parsed command from `parse_slash_command`.
        docs_url: Docs URL used in help output and `/docs` resolution.
        thread_id: Thread identifier used for `/trace`. Pass `None` when the
            client has no active session.
        client_label: Client label used for `/version`.
        client_version: Client version string used for `/version`.
        current_context: Token usage (total), used for `/tokens`.
        model_name: Model name, used for `/tokens`.
        context_limit: Model context limit, used for `/tokens`.
        conversation_line: Optional extra token line, used for `/tokens`.

    Returns:
        `CommandExecution` for commands owned by the shared runtime, or `None`
        when the caller should handle the command locally.
    """
    if parsed.kind != "trace":
        return execute_parsed_slash_command(
            parsed,
            docs_url=docs_url,
            client_label=client_label,
            client_version=client_version,
            current_context=current_context,
            model_name=model_name,
            context_limit=context_limit,
            conversation_line=conversation_line,
        )

    if not thread_id:
        return CommandExecution(
            echo_command=True,
            actions=(ShowMessageAction("No active session."),),
        )

    try:
        url = await asyncio.to_thread(tracing.build_langsmith_thread_url, thread_id)
    except Exception:
        logger.exception("Failed to build LangSmith thread URL for %s", thread_id)
        return CommandExecution(
            echo_command=True,
            actions=(ShowMessageAction("Failed to resolve LangSmith thread URL."),),
        )

    if not url:
        return CommandExecution(
            echo_command=True,
            actions=(
                ShowMessageAction(
                    "LangSmith tracing is not configured. "
                    "Set LANGSMITH_API_KEY and LANGSMITH_TRACING=true to enable."
                ),
            ),
        )

    return CommandExecution(echo_command=True, actions=(OpenUrlAction(url),))


def build_help_text(docs_url: str) -> str:
    """Build the shared `/help` response text.

    Args:
        docs_url: Documentation URL to include in the help output.

    Returns:
        Help text suitable for rendering in any client.
    """
    return (
        "Commands: /quit, /clear, /compact, /model [--default], /remember, "
        "/tokens, /threads, /trace, /changelog, /docs, /feedback, /version, /help\n\n"
        "Interactive Features:\n"
        "  Enter           Submit your message\n"
        "  Ctrl+J          Insert newline\n"
        "  Shift+Tab       Toggle auto-approve mode\n"
        "  @filename       Auto-complete files and inject content\n"
        "  /command        Slash commands (/help, /clear, /quit)\n"
        "  !command        Run bash commands directly\n\n"
        f"Docs: {docs_url}"
    )


def build_version_message(*, client_label: str, client_version: str | None) -> str:
    """Build the shared `/version` response text.

    Args:
        client_label: Label for the active client.
        client_version: Version string for the active client.

    Returns:
        Human-readable version output, including client and SDK versions.
    """
    client_line = f"{client_label} version: {client_version or 'unknown'}"

    try:
        sdk_version = importlib.metadata.version("deepagents")
    except importlib.metadata.PackageNotFoundError:
        logger.debug("deepagents SDK package not found in environment")
        sdk_version = None
    except Exception:
        logger.warning("Unexpected error looking up SDK version", exc_info=True)
        sdk_version = None

    sdk_line = f"deepagents (SDK) version: {sdk_version or 'unknown'}"
    return f"{client_line}\n{sdk_line}"


def build_token_usage_message(
    *,
    current_context: int,
    model_name: str | None,
    context_limit: int | None,
    conversation_line: str | None = None,
) -> str:
    """Build the shared `/tokens` response text.

    Args:
        current_context: Total current token usage.
        model_name: Active model name, if known.
        context_limit: Active model context window, if known.
        conversation_line: Optional extra line for conversation-only token usage.

    Returns:
        Human-readable token usage summary.
    """
    if current_context > 0:
        formatted = format_token_count(current_context)
        if context_limit is not None:
            limit_str = format_token_count(context_limit)
            pct = current_context / context_limit * 100
            usage = (
                f"{formatted} / {limit_str} tokens "
                f"({pct:.0f}%, includes system prompt + tools)"
            )
        else:
            usage = f"{formatted} tokens used (includes system prompt + tools)"

        message = f"{usage} · {model_name}" if model_name else usage
        if conversation_line:
            return f"{message}\n{conversation_line}"
        return message

    parts: list[str] = ["No token usage yet"]
    if context_limit is not None:
        parts.append(f"{format_token_count(context_limit)} context window")
    if model_name:
        parts.append(model_name)
    return " · ".join(parts)


def build_remember_prompt(
    base_prompt: str,
    additional_context: str | None = None,
) -> str:
    """Build the final `/remember` prompt sent through the normal agent path.

    Args:
        base_prompt: Base remember prompt text.
        additional_context: Optional extra user-provided guidance.

    Returns:
        Final remember prompt for the agent.
    """
    if not additional_context:
        return base_prompt
    return f"{base_prompt}\n\n**Additional context from user:** {additional_context}"
