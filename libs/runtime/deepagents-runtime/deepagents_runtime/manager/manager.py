"""AgentManager: the data plane kernel.

Central coordinator for the data plane. Manages:
- Agent specs via Registry (file-system backed)
- Agent assembly via assembly.py (spec → template)
- Agent execution via orchestration.py (run_agent_loop)
- Per-run resource lifecycle via AgentRun (sandbox, MCP)

The AgentManager does NOT know about the control plane or gRPC.
It is used by the gRPC servicers (entry/server.py) to handle RPCs.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from deepagents_runtime.events import RuntimeEvent
from deepagents_runtime.manager.assembly import assemble
from deepagents_runtime.manager.registry import Registry
from deepagents_runtime.orchestration import HITLHandler, run_agent_loop
from deepagents_runtime.sandbox.pool import SandboxPool
from deepagents_runtime.sessions import generate_thread_id, get_checkpointer
from deepagents_runtime.spec import (
    AgentMeta,
    AgentRun,
    AgentSpec,
    AgentStatus,
    AgentTemplate,
    ManagedAgent,
    RunConfig,
)

logger = logging.getLogger(__name__)


class AgentManager:
    """The data plane runtime kernel.

    Provides a unified API for:
    - Managing resources (skills, MCPs, agent specs) via Registry.
    - Assembling agents from specs (resolving all dependencies).
    - Running agents with per-run sandbox/MCP via AgentRun.

    Used by the gRPC servicers to handle incoming RPCs from the
    control plane.

    Lifecycle::

        manager = AgentManager()
        await manager.setup()      # opens checkpointer + sandbox pool
        # ... use manager ...
        await manager.shutdown()   # closes everything

    Or as an async context manager::

        async with AgentManager() as manager:
            await manager.define_agent(spec)
            await manager.assemble_agent("my-agent")
            async for event in manager.invoke("my-agent", RunConfig(input="hello")):
                print(event)
    """

    def __init__(
        self,
        registry: Registry | None = None,
        sandbox_pool: SandboxPool | None = None,
    ) -> None:
        self._registry = registry or Registry()
        self._sandbox_pool = sandbox_pool or SandboxPool()
        self._agents: dict[str, ManagedAgent] = {}
        self._active_runs: dict[str, AgentRun] = {}
        self._checkpointer: Any = None
        self._checkpointer_cm: Any = None  # context manager handle

    async def setup(self) -> None:
        """Initialise long-lived resources (checkpointer).

        Safe to call multiple times — only the first call takes effect.
        """
        if self._checkpointer is None:
            self._checkpointer_cm = get_checkpointer()
            self._checkpointer = await self._checkpointer_cm.__aenter__()
            logger.info("Checkpointer initialised")

    async def shutdown(self) -> None:
        """Release long-lived resources."""
        # Teardown any lingering active runs
        for run_id, run in list(self._active_runs.items()):
            logger.warning("Force-cleaning active run %s", run_id)
            await run.teardown(sandbox_pool=self._sandbox_pool)
        self._active_runs.clear()

        # Shutdown sandbox pool
        await self._sandbox_pool.shutdown()

        # Close checkpointer
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
    def sandbox_pool(self) -> SandboxPool:
        """Access the sandbox pool."""
        return self._sandbox_pool

    # ── Agent Lifecycle ──

    async def define_agent(self, spec: AgentSpec) -> None:
        """Register an agent spec and create a ManagedAgent entry.

        If the agent already exists, its spec is updated and status
        is reset to DEFINED.
        """
        await self._registry.add_agent_spec(spec)
        self._agents[spec.name] = ManagedAgent(
            name=spec.name,
            spec=spec,
            status=AgentStatus.DEFINED,
        )
        logger.info("Agent '%s' defined", spec.name)

    async def assemble_agent(self, name: str) -> AgentTemplate:
        """Assemble a defined agent into a runnable template.

        Resolves all resources from the registry and builds the
        compiled LangGraph agent.  Uses the manager's long-lived
        checkpointer so the graph can persist state across runs.

        Args:
            name: Agent name (must be previously defined or in registry).

        Returns:
            The assembled AgentTemplate.

        Raises:
            KeyError: If agent is not defined.
            ValueError: If referenced resources are missing.
        """
        await self.setup()  # ensure checkpointer is ready

        managed = await self._get_managed(name)

        template = await assemble(
            managed.spec, self._registry, checkpointer=self._checkpointer
        )

        managed.template = template
        managed.status = AgentStatus.ASSEMBLED
        logger.info("Agent '%s' assembled", name)
        return template

    async def invoke(
        self,
        name: str,
        run_config: RunConfig,
        *,
        hitl_handler: HITLHandler | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run an agent and stream events.

        Creates an ``AgentRun`` per invocation to manage sandbox and MCP
        resources. If the agent is not yet assembled, assembles it first.

        Args:
            name: Agent name.
            run_config: Runtime configuration (mode, input, etc.).
            hitl_handler: Optional HITL decision callback.

        Yields:
            RuntimeEvent instances.
        """
        managed = await self._get_managed(name)

        if managed.template is None:
            await self.assemble_agent(name)

        assert managed.template is not None
        managed.status = AgentStatus.RUNNING

        run_id = uuid.uuid4().hex[:12]
        thread_id = run_config.thread_id or generate_thread_id()
        config = {"configurable": {"thread_id": thread_id}}

        # Create per-run context
        agent_run = AgentRun(
            template=managed.template,
            run_id=run_id,
            thread_id=thread_id,
        )
        await agent_run.setup(sandbox_pool=self._sandbox_pool)
        self._active_runs[run_id] = agent_run

        try:
            async for evt in run_agent_loop(
                managed.template.graph,
                run_config.input,
                config=config,
                hitl_handler=hitl_handler,
                run_id=run_id,
                agent_name=name,
            ):
                yield evt
        finally:
            await agent_run.teardown(sandbox_pool=self._sandbox_pool)
            self._active_runs.pop(run_id, None)
            managed.status = AgentStatus.STOPPED

    async def list_agents(self) -> list[AgentMeta]:
        """List all defined agents (from both registry and in-memory)."""
        return await self._registry.list_agent_specs()

    async def get_agent_status(self, name: str) -> AgentStatus:
        """Get current status of an agent."""
        if name in self._agents:
            return self._agents[name].status
        # Check registry
        spec = await self._registry.get_agent_spec(name)
        if spec is not None:
            return AgentStatus.DEFINED
        raise KeyError(f"Agent '{name}' not found")

    # ── Internal ──

    async def _get_managed(self, name: str) -> ManagedAgent:
        """Get or create a ManagedAgent from registry."""
        if name not in self._agents:
            spec = await self._registry.get_agent_spec(name)
            if spec is None:
                raise KeyError(f"Agent '{name}' not found in registry")
            self._agents[name] = ManagedAgent(
                name=name,
                spec=spec,
                status=AgentStatus.DEFINED,
            )
        return self._agents[name]
