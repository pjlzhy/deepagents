"""Runtime-specific agent graph assembly."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    TodoListMiddleware,
)
from langchain.agents.middleware.types import AgentMiddleware
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from deepagents._models import resolve_model
from deepagents.backends.protocol import BackendFactory, BackendProtocol
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import (
    GENERAL_PURPOSE_SUBAGENT,
    CompiledSubAgent,
    SubAgent,
    SubAgentMiddleware,
)
from agents_runtime.artifacts import ArtifactsMiddleware
from deepagents.middleware.summarization import create_summarization_middleware
from agents_runtime.runtime_filesystem import RuntimeFilesystemMiddleware

BASE_AGENT_PROMPT = """## Core Behavior

- Be concise and direct. Don't over-explain unless asked.
- NEVER add unnecessary preamble (\"Sure!\", \"Great question!\", \"I'll now...\").
- Don't say \"I'll now do X\" — just do it.
- If the request is ambiguous, ask questions before acting.
- If asked how to approach something, explain first, then act.

## Professional Objectivity

- Prioritize accuracy over validating the user's beliefs
- Disagree respectfully when the user is incorrect
- Avoid unnecessary superlatives, praise, or emotional validation

## Doing Tasks

When the user asks you to do something:

1. **Understand first** — read relevant files, check existing patterns. Quick but thorough — gather enough evidence to start, then iterate.
2. **Act** — implement the solution. Work quickly but accurately.
3. **Verify** — check your work against what was asked, not against your own output. Your first attempt is rarely correct — iterate.

Keep working until the task is fully complete. Don't stop partway and explain what you would do — just do it. Only yield back to the user when the task is done or you're genuinely blocked.

**When things go wrong:**
- If something fails repeatedly, stop and analyze *why* — don't keep retrying the same approach.
- If you're blocked, tell the user what's wrong and ask for guidance.

## Progress Updates

For longer tasks, provide brief progress updates at reasonable intervals — a concise sentence recapping what you've done and what's next."""

def create_runtime_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    backend: BackendProtocol | BackendFactory,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    checkpointer: Checkpointer | None = None,
    name: str | None = None,
) -> CompiledStateGraph:
    """Create a runtime-specific deep agent graph.

    This mirrors the SDK's `create_deep_agent` assembly but replaces the
    default filesystem middleware with a runtime-specific relative-path version.
    """
    gp_middleware: list[AgentMiddleware[Any, Any, Any]] = [
        TodoListMiddleware(),
        RuntimeFilesystemMiddleware(backend=backend),
        ArtifactsMiddleware(),
        create_summarization_middleware(model, backend),
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        PatchToolCallsMiddleware(),
    ]
    if interrupt_on is not None:
        gp_middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))

    general_purpose_spec: SubAgent = {  # ty: ignore[missing-typed-dict-key]
        **GENERAL_PURPOSE_SUBAGENT,
        "model": model,
        "tools": tools or [],
        "middleware": gp_middleware,
    }

    processed_subagents: list[SubAgent | CompiledSubAgent] = []
    for spec in subagents or []:
        if "runnable" in spec:
            processed_subagents.append(spec)
            continue

        subagent_middleware: list[AgentMiddleware[Any, Any, Any]] = [
            TodoListMiddleware(),
            RuntimeFilesystemMiddleware(backend=backend),
            ArtifactsMiddleware(),
            create_summarization_middleware(model, backend),
            AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
            PatchToolCallsMiddleware(),
        ]
        subagent_middleware.extend(spec.get("middleware", []))

        processed_spec: SubAgent = {  # ty: ignore[missing-typed-dict-key]
            **spec,
            "model": resolve_model(spec.get("model", model)),
            "tools": spec.get("tools", tools or []),
            "middleware": subagent_middleware,
        }
        processed_subagents.append(processed_spec)

    if any(spec["name"] == GENERAL_PURPOSE_SUBAGENT["name"] for spec in processed_subagents):
        all_subagents: list[SubAgent | CompiledSubAgent] = processed_subagents
    else:
        all_subagents = [general_purpose_spec, *processed_subagents]

    deepagent_middleware: list[AgentMiddleware[Any, Any, Any]] = [
        TodoListMiddleware(),
        RuntimeFilesystemMiddleware(backend=backend),
        ArtifactsMiddleware(),
        SubAgentMiddleware(
            backend=backend,
            subagents=all_subagents,
        ),
        create_summarization_middleware(model, backend),
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        PatchToolCallsMiddleware(),
    ]
    if middleware:
        deepagent_middleware.extend(middleware)
    if interrupt_on is not None:
        deepagent_middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))

    if system_prompt is None:
        final_system_prompt: str | SystemMessage = BASE_AGENT_PROMPT
    elif isinstance(system_prompt, SystemMessage):
        final_system_prompt = SystemMessage(
            content_blocks=[
                *system_prompt.content_blocks,
                {"type": "text", "text": f"\n\n{BASE_AGENT_PROMPT}"},
            ]
        )
    else:
        final_system_prompt = system_prompt + "\n\n" + BASE_AGENT_PROMPT

    return create_agent(
        model,
        system_prompt=final_system_prompt,
        tools=tools,
        middleware=deepagent_middleware,
        checkpointer=checkpointer,
        name=name,
    ).with_config(
        {
            "recursion_limit": 1000,
            "metadata": {
                "ls_integration": "agents",
            },
        }
    )
