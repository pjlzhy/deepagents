"""AgentManager: manager-controlled install, compile, and run lifecycle.

Central coordinator for the data plane. Manages:
- Agent specs via Registry (file-system backed)
- Agent compilation into RuntimeAgent-owned runnable graphs
- Agent execution via RuntimeAgent.astream()
- Compiled agent scoped MCP / sandbox runtime resources

The AgentManager does NOT know about the control plane or gRPC.
It is used by the gRPC servicers (entry/server.py) to handle RPCs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from deepagents_runtime.agent import HITLHandler, RuntimeAgent
from deepagents_runtime.events import RuntimeEvent
from deepagents_runtime.registry import Registry
from deepagents_runtime.sandbox.pool import SandboxPool
from deepagents_runtime.sessions import generate_thread_id, get_checkpointer
from deepagents_runtime.spec import AgentMeta, AgentSpec, AgentStatus, RunConfig

logger = logging.getLogger(__name__)


class AgentPool:
    """Concurrent-safe runtime agent pool."""

    def __init__(self, agents: dict[str, RuntimeAgent] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._agents: dict[str, RuntimeAgent] = agents or {}

    async def get(self, name: str) -> RuntimeAgent:
        """Get a runtime agent by name."""
        async with self._lock:
            agent = self._agents.get(name)
            if agent is None:
                raise KeyError(f"Agent '{name}' not found in agent pool")
            return agent

    async def get_optional(self, name: str) -> RuntimeAgent | None:
        """Get a runtime agent by name, returning `None` if absent."""
        async with self._lock:
            return self._agents.get(name)

    async def set(self, agent: RuntimeAgent) -> None:
        """Insert or replace a runtime agent."""
        async with self._lock:
            self._agents[agent.spec.name] = agent

    async def pop(self, name: str) -> RuntimeAgent | None:
        """Remove and return a runtime agent."""
        async with self._lock:
            return self._agents.pop(name, None)

    async def values(self) -> list[RuntimeAgent]:
        """Snapshot all runtime agents."""
        async with self._lock:
            return list(self._agents.values())

    async def count(self) -> int:
        """Return the number of pooled agents."""
        async with self._lock:
            return len(self._agents)

    async def status(self, name: str) -> AgentStatus:
        """Return the public status of a pooled agent."""
        agent = await self.get(name)
        return agent.status()


class AgentManager:
    """Manager-owned lifecycle controller for installed and compiled agents."""

    def __init__(
            self,
            registry: Registry | None = None,
            sandbox_pool: SandboxPool | None = None,
    ) -> None:
        self._registry = registry or Registry()
        self._sandbox_pool = sandbox_pool
        self.agent_pool: AgentPool | None = None
        self._checkpointer: Any = None
        self._checkpointer_cm: Any = None

    async def setup(self) -> None:
        """Initialise long-lived resources."""
        if self._checkpointer is None:
            self._checkpointer_cm = get_checkpointer()
            self._checkpointer = await self._checkpointer_cm.__aenter__()
            logger.info("Checkpointer initialised")
        if self.agent_pool is None:
            self.agent_pool = AgentPool()

    async def shutdown(self) -> None:
        """Release compiled runtime resources and the shared checkpointer."""
        if self.agent_pool is not None:
            for agent in await self.agent_pool.values():
                if agent.is_running():
                    logger.warning(
                        "Skipping runtime release for running agent '%s' during shutdown",
                        agent.spec.name,
                    )
                    continue
                if agent.has_runtime():
                    try:
                        await agent.release()
                    except Exception:
                        logger.warning(
                            "Failed to release runtime for agent '%s' during shutdown",
                            agent.spec.name,
                            exc_info=True,
                        )

        if self._checkpointer_cm is not None:
            await self._checkpointer_cm.__aexit__(None, None, None)
            self._checkpointer = None
            self._checkpointer_cm = None
            logger.info("Checkpointer closed")

    async def __aenter__(self) -> AgentManager:
        await self.setup()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.shutdown()

    @property
    def registry(self) -> Registry:
        """Access the underlying registry for direct resource operations."""
        return self._registry

    @property
    def sandbox_pool(self) -> SandboxPool | None:
        """Compatibility accessor for callers still expecting manager ownership."""
        return self._sandbox_pool

    # ── Agent Lifecycle ──

    async def define_agent(self, spec: AgentSpec) -> None:
        """Install or update an agent spec without compiling it."""
        await self.setup()
        assert self.agent_pool is not None

        agent = await self.agent_pool.get_optional(spec.name)
        if agent is not None:
            if agent.is_busy():
                msg = f"cannot redefine agent '{spec.name}' while busy"
                raise RuntimeError(msg)
            if agent.has_runtime():
                await agent.release()

        await self._registry.add_agent_spec(spec)

        if agent is None:
            agent = RuntimeAgent(spec=spec, reg=self._registry)
            await self.agent_pool.set(agent)

        logger.info("Agent '%s' installed", spec.name)

    async def assemble_agent(self, name: str) -> None:
        """Compile an installed agent into runnable runtime resources."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if agent.is_busy():
            msg = f"cannot assemble agent '{name}' while busy"
            raise RuntimeError(msg)

        latest_spec = await self._registry.get_agent_spec(name)
        if latest_spec is None:
            raise KeyError(f"Agent '{name}' not found")

        if agent.has_runtime():
            await agent.release()

        agent.spec = latest_spec
        agent.registry = self._registry
        await agent.assemble(checkpointer=self._checkpointer)
        logger.info("Agent '%s' compiled", name)

    async def unload_agent(self, name: str) -> None:
        """Release compiled runtime resources while keeping the installed spec."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if agent.is_busy():
            msg = f"cannot unload agent '{name}' while busy"
            raise RuntimeError(msg)

        if agent.has_runtime():
            await agent.release()
            logger.info("Agent '%s' unloaded", name)

    async def stop_agent(self, name: str) -> None:
        """Compatibility wrapper for callers still using stop terminology."""
        await self.unload_agent(name)

    async def remove_agent(self, name: str) -> bool:
        """Uninstall an agent by unloading runtime state and deleting its spec."""
        await self.setup()
        assert self.agent_pool is not None

        agent = await self.agent_pool.get_optional(name)
        if agent is not None:
            if agent.is_busy():
                msg = f"cannot remove agent '{name}' while busy"
                raise RuntimeError(msg)
            if agent.has_runtime():
                await agent.release()
            await self.agent_pool.pop(name)

        deleted = await self._registry.delete_agent_spec(name)
        if deleted or agent is not None:
            logger.info("Agent '%s' uninstalled", name)
            return True
        return False

    async def invoke(
            self,
            name: str,
            run_config: RunConfig,
            *,
            hitl_handler: HITLHandler | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run an already compiled agent and stream events."""
        await self.setup()
        agent = await self._get_or_create_agent(name)
        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)

        thread_id = run_config.thread_id or generate_thread_id()
        configurable: dict[str, Any] = {"thread_id": thread_id}
        if run_config.run_id:
            configurable["run_id"] = run_config.run_id

        agent.last_invoked = datetime.now(UTC)

        async for evt in agent.astream(
                context=None,
                message=run_config.input,
                config={"configurable": configurable},
                hitl_handler=hitl_handler,
        ):
            yield evt


    async def list_agents(self) -> list[AgentMeta]:
        """List all installed agents with live runtime status overlays."""
        await self.setup()
        assert self.agent_pool is not None

        installed = await self._registry.list_agent_specs()
        runtime_statuses = {
            agent.spec.name: agent.status()
            for agent in await self.agent_pool.values()
        }

        return [
            AgentMeta(
                name=meta.name,
                version=meta.version,
                description=meta.description,
                tags=meta.tags,
                status=runtime_statuses.get(meta.name, meta.status),
            )
            for meta in installed
        ]

    async def get_agent_status(self, name: str) -> AgentStatus:
        """Get current status of an agent."""
        await self.setup()
        assert self.agent_pool is not None

        agent = await self.agent_pool.get_optional(name)
        if agent is not None:
            return agent.status()
        spec = await self._registry.get_agent_spec(name)
        if spec is not None:
            return AgentStatus.INSTALLED
        raise KeyError(f"Agent '{name}' not found")

    # ── Internal ──

    async def _get_or_create_agent(self, name: str) -> RuntimeAgent:
        """Load an installed agent into the runtime pool if needed."""
        assert self.agent_pool is not None

        agent = await self.agent_pool.get_optional(name)
        if agent is not None:
            return agent

        spec = await self._registry.get_agent_spec(name)
        if spec is None:
            raise KeyError(f"Agent '{name}' not found")

        agent = RuntimeAgent(spec=spec, reg=self._registry)
        await self.agent_pool.set(agent)
        return agent
