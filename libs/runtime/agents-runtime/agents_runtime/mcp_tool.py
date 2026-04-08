"""MCP tool loading for the runtime data plane.

Converts ``McpConfig`` specs into live LangChain ``BaseTool`` instances
via ``langchain-mcp-adapters``.  All CLI-specific discovery / trust logic
lives in the CLI package; this module only deals with already-resolved
configurations.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from agents_runtime.spec import McpConfig

logger = logging.getLogger(__name__)

# ──────────────────── Data classes ────────────────────


@dataclass
class MCPToolInfo:
    """Metadata for a single MCP tool."""

    name: str
    description: str


@dataclass
class MCPServerInfo:
    """Metadata for a connected MCP server and its tools."""

    name: str
    transport: str
    tools: list[MCPToolInfo] = field(default_factory=list)


# ──────────────────── Session manager ────────────────────


class MCPSessionManager:
    """Manages persistent MCP sessions for stateful stdio servers.

    Creates and maintains persistent sessions for MCP servers, preventing
    server restarts on every tool call.  Sessions are kept alive until
    explicitly cleaned up.
    """

    def __init__(self) -> None:
        self.client: object | None = None  # MultiServerMCPClient
        self.exit_stack = AsyncExitStack()

    async def cleanup(self) -> None:
        """Close all managed sessions and connections."""
        await self.exit_stack.aclose()


# ──────────────────── Transport helpers ────────────────────

_SUPPORTED_REMOTE_TRANSPORTS = frozenset({"sse", "http", "streamable_http"})


def _build_connection(cfg: McpConfig) -> tuple[str, object]:
    """Convert a ``McpConfig`` into a ``(server_name, Connection)`` pair.

    Returns:
        Tuple of ``(name, connection_typed_dict)``.

    Raises:
        ValueError: If the transport type is unsupported or required fields
            are missing.
    """
    from langchain_mcp_adapters.sessions import (
        SSEConnection,
        StdioConnection,
        StreamableHttpConnection,
    )

    transport = cfg.transport.lower()

    if transport == "stdio":
        if not cfg.command:
            msg = f"MCP server '{cfg.name}': stdio transport requires 'command'"
            raise ValueError(msg)
        return cfg.name, StdioConnection(
            transport="stdio",
            command=cfg.command,
            args=cfg.args,
            env=cfg.env or None,
        )

    if transport in ("sse", "http", "streamable_http"):
        # SSE and HTTP-based transports need a URL.
        # McpConfig stores the URL in ``command`` for remote transports.
        url = cfg.command
        if not url:
            msg = f"MCP server '{cfg.name}': {transport} transport requires a URL (set as 'command')"
            raise ValueError(msg)

        if transport == "sse":
            return cfg.name, SSEConnection(transport="sse", url=url)
        # Both "http" and "streamable_http" use StreamableHttpConnection
        return cfg.name, StreamableHttpConnection(
            transport="streamable_http", url=url,
        )

    msg = (
        f"MCP server '{cfg.name}': unsupported transport '{transport}'. "
        "Supported: stdio, sse, http, streamable_http"
    )
    raise ValueError(msg)


# ──────────────────── Public API ────────────────────


async def load_mcp_tools_from_configs(
    configs: list[McpConfig],
) -> tuple[list[BaseTool], MCPSessionManager | None, list[MCPServerInfo]]:
    """Load LangChain tools from a list of ``McpConfig`` specs.

    This is the single entry-point used by the runtime assembly path. It converts
    each ``McpConfig`` into a ``langchain-mcp-adapters`` connection,
    starts sessions, and returns the loaded tools along with a session
    manager that **must** be cleaned up by the caller.

    Args:
        configs: MCP server configurations.  An empty list is valid and
            returns ``([], None, [])``.

    Returns:
        Tuple of ``(tools, session_manager, server_infos)``.
        When *configs* is empty, returns ``([], None, [])``.

    Raises:
        RuntimeError: If any MCP server fails to spawn or connect.
    """
    if not configs:
        return [], None, []

    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools

    # Build connections dict
    connections: dict[str, object] = {}
    for cfg in configs:
        try:
            name, conn = _build_connection(cfg)
            connections[name] = conn
        except ValueError as e:
            raise RuntimeError(str(e)) from e

    # Create session manager
    manager = MCPSessionManager()

    try:
        client = MultiServerMCPClient(connections=connections)
        manager.client = client
    except Exception as e:
        await manager.cleanup()
        msg = f"Failed to initialize MCP client: {e}"
        raise RuntimeError(msg) from e

    try:
        all_tools: list[BaseTool] = []
        server_infos: list[MCPServerInfo] = []

        for cfg in configs:
            session = await manager.exit_stack.enter_async_context(
                client.session(cfg.name)
            )
            tools = await load_mcp_tools(
                session, server_name=cfg.name, tool_name_prefix=True,
            )
            all_tools.extend(tools)
            server_infos.append(
                MCPServerInfo(
                    name=cfg.name,
                    transport=cfg.transport,
                    tools=[
                        MCPToolInfo(name=t.name, description=t.description or "")
                        for t in tools
                    ],
                )
            )
            logger.info(
                "Loaded %d tool(s) from MCP server '%s' (%s)",
                len(tools), cfg.name, cfg.transport,
            )
    except Exception as e:
        await manager.cleanup()
        msg = (
            f"Failed to load tools from MCP server: {e}\n"
            "For stdio servers: check that the command and args are correct "
            "and that the MCP server is installed.\n"
            "For sse/http servers: check that the URL is correct "
            "and the server is running."
        )
        raise RuntimeError(msg) from e

    return all_tools, manager, server_infos
