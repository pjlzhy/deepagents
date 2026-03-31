"""Unit tests for AgentSpec validation."""

from __future__ import annotations

import pytest

from deepagents_runtime.spec import AgentSpec, McpConfig, validate_agent_spec


def test_validate_agent_spec_rejects_invalid_model_format() -> None:
    """Agent model must use the `provider:model` format."""

    spec = AgentSpec(
        name="demo-agent",
        model="gpt-5.2",
    )

    with pytest.raises(ValueError, match="agent model must be in provider:model format"):
        validate_agent_spec(spec)


def test_validate_agent_spec_rejects_duplicate_subagent_names() -> None:
    """Subagent names should be unique within one agent."""

    spec = AgentSpec(
        name="demo-agent",
        subagents=[
            {
                "name": "reviewer",
                "description": "review code",
                "system_prompt": "review carefully",
            },
            {
                "name": "reviewer",
                "description": "review docs",
                "system_prompt": "review docs carefully",
            },
        ],
    )

    with pytest.raises(ValueError, match="duplicate subagent names"):
        validate_agent_spec(spec)


def test_validate_agent_spec_rejects_invalid_mcp_transport() -> None:
    """MCP server transport should be validated before assembly."""

    spec = AgentSpec(
        name="demo-agent",
        mcp_servers=[
            McpConfig(
                name="github",
                command="https://example.com/mcp",
                transport="grpc",
            )
        ],
    )

    with pytest.raises(ValueError, match="transport must be one of"):
        validate_agent_spec(spec)


def test_validate_agent_spec_rejects_duplicate_interrupt_entries() -> None:
    """interrupt_on should not contain duplicate tool names."""

    spec = AgentSpec(
        name="demo-agent",
        interrupt_on=["execute", "execute"],
    )

    with pytest.raises(ValueError, match="duplicate interrupt_on entries"):
        validate_agent_spec(spec)


def test_validate_agent_spec_rejects_unknown_sandbox_backend() -> None:
    """Sandbox backend selection should reject unsupported backend kinds."""

    with pytest.raises(ValueError, match="sandbox backend 'modal' must be one of"):
        AgentSpec(
            name="demo-agent",
            sandbox={"resources": {"backend": "modal"}},
        )
