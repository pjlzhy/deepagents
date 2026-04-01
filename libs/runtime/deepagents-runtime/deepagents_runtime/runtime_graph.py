"""Runtime-specific deep agent graph assembly."""

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
from deepagents.graph import BASE_AGENT_PROMPT
from deepagents.backends.protocol import BackendFactory, BackendProtocol
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import (
    GENERAL_PURPOSE_SUBAGENT,
    CompiledSubAgent,
    SubAgent,
    SubAgentMiddleware,
)
from deepagents.middleware.summarization import create_summarization_middleware
from deepagents_runtime.runtime_filesystem import RuntimeFilesystemMiddleware


def create_runtime_deep_agent(
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
                "ls_integration": "deepagents",
            },
        }
    )
