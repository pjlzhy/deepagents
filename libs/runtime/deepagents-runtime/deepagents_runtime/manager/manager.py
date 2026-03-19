"""AgentManager: the data plane runtime kernel.

Central coordinator for the data plane. Manages:
- Agent specs via Registry (file-system backed)
- Agent compilation via assembly.py (spec → template)
- Agent execution via orchestration.py (run_agent_loop)
- Compiled agent scoped MCP / sandbox runtime resources

The AgentManager does NOT know about the control plane or gRPC.
It is used by the gRPC servicers (entry/server.py) to handle RPCs.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from deepagents.backends import LocalShellBackend
from deepagents_runtime.events import RuntimeEvent
from deepagents_runtime.manager.assembly import assemble, warm_runtime_dependencies
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
    SandboxRuntime,
)

logger = logging.getLogger(__name__)


class AgentManager:
    """The data plane runtime kernel.

    Provides a unified API for:
    - Managing installed agent specs via Registry.
    - Compiling agents into reusable runtime templates.
    - Running agents with agent-scoped MCP runtime and run-scoped sandbox leases.

    Used by the gRPC servicers to handle incoming RPCs from the
    control plane.
    """

    def __init__(
        self,
        registry: Registry | None = None,
        sandbox_pool: SandboxPool | None = None,
    ) -> None:
        self._registry = registry or Registry()
        self._sandbox_pool = sandbox_pool or SandboxPool()
        self._use_shared_sandbox_pool = sandbox_pool is not None
        self._agents: dict[str, ManagedAgent] = {}
        self._active_runs: dict[str, AgentRun] = {}
        self._checkpointer: Any = None
        self._checkpointer_cm: Any = None  # context manager handle

    async def setup(self) -> None:
        """Initialise long-lived resources (checkpointer)."""
        if self._checkpointer is None:
            self._checkpointer_cm = get_checkpointer()
            self._checkpointer = await self._checkpointer_cm.__aenter__()
            logger.info("Checkpointer initialised")
            providers = await self._installed_model_providers()
            warm_runtime_dependencies(model_providers=providers)

    async def shutdown(self) -> None:
        """Release all active runs and compiled runtime resources."""
        for run_id, run in list(self._active_runs.items()):
            logger.warning("Force-cleaning active run %s", run_id)
            managed = self._agents.get(run.agent_name)
            sandbox_pool = (
                managed.sandbox_runtime.pool
                if managed is not None and managed.sandbox_runtime is not None
                else None
            )
            await run.teardown(sandbox_pool=sandbox_pool)
            self._active_runs.pop(run_id, None)
            if managed is not None:
                managed.active_run_count = max(0, managed.active_run_count - 1)
                if managed.active_run_count == 0 and managed.template is not None:
                    managed.status = AgentStatus.COMPILED

        for managed in self._agents.values():
            await self._release_managed_resources(managed)
            managed.status = AgentStatus.INSTALLED

        await self._sandbox_pool.shutdown()

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
        """Access the shared sandbox pool compatibility path."""
        return self._sandbox_pool

    # ── Agent Lifecycle ──

    async def define_agent(self, spec: AgentSpec) -> None:
        """Install or replace an agent spec and reset its runtime state."""
        existing = self._agents.get(spec.name)
        if existing is not None and existing.active_run_count > 0:
            msg = (
                f"Agent '{spec.name}' has {existing.active_run_count} active run(s); "
                "cannot redefine while running"
            )
            raise RuntimeError(msg)

        await self._registry.add_agent_spec(spec)
        if existing is not None:
            await self._release_managed_resources(existing)

        self._agents[spec.name] = ManagedAgent(
            name=spec.name,
            spec=spec,
            status=AgentStatus.INSTALLED,
        )
        provider = self._spec_model_provider(spec)
        warm_runtime_dependencies(
            model_providers=frozenset({provider}) if provider else frozenset(),
        )
        logger.info("Agent '%s' installed", spec.name)

    async def assemble_agent(self, name: str) -> AgentTemplate:
        """Compile an installed agent into reusable runtime resources."""
        await self.setup()

        managed = await self._get_managed(name)
        if self._has_live_runtime(managed):
            assert managed.template is not None
            return managed.template

        await self._release_managed_resources(managed)

        template, mcp_runtime = await assemble(
            managed.spec,
            self._registry,
            checkpointer=self._checkpointer,
        )

        managed.template = template
        managed.mcp_runtime = mcp_runtime
        managed.sandbox_runtime = self._create_sandbox_runtime(managed)
        managed.status = (
            AgentStatus.RUNNING
            if managed.active_run_count > 0
            else AgentStatus.COMPILED
        )

        logger.info("Agent '%s' compiled", name)
        return template

    async def unload_agent(self, name: str) -> None:
        """Release compiled runtime resources while keeping the installed spec."""
        managed = await self._get_managed(name)
        if managed.active_run_count > 0:
            msg = (
                f"Agent '{name}' has {managed.active_run_count} active run(s); "
                "unload_agent() cannot proceed"
            )
            raise RuntimeError(msg)

        await self._release_managed_resources(managed)
        managed.status = AgentStatus.INSTALLED
        logger.info("Agent '%s' unloaded", name)

    async def stop_agent(self, name: str) -> None:
        """Compatibility wrapper for callers still using stop terminology."""
        await self.unload_agent(name)

    async def remove_agent(self, name: str) -> bool:
        """Uninstall an agent by unloading runtime state and deleting its spec."""
        managed = self._agents.get(name)
        if managed is not None:
            if managed.active_run_count > 0:
                msg = (
                    f"Agent '{name}' has {managed.active_run_count} active run(s); "
                    "remove_agent() cannot proceed"
                )
                raise RuntimeError(msg)

            await self._release_managed_resources(managed)

        deleted = await self._registry.delete_agent_spec(name)
        self._agents.pop(name, None)
        if deleted or managed is not None:
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
        """Run an agent and stream events."""
        managed = await self._get_managed(name)
        if not self._has_live_runtime(managed):
            await self.assemble_agent(name)
            managed = await self._get_managed(name)

        assert managed.template is not None
        assert managed.sandbox_runtime is not None

        run_id = run_config.run_id or uuid.uuid4().hex[:12]
        thread_id = run_config.thread_id or generate_thread_id()
        config = {"configurable": {"thread_id": thread_id}}
        sandbox_pool = managed.sandbox_runtime.pool

        agent_run = AgentRun(
            agent_name=name,
            template=managed.template,
            run_id=run_id,
            thread_id=thread_id,
        )
        await agent_run.setup(sandbox_pool=sandbox_pool)

        self._active_runs[run_id] = agent_run
        managed.active_run_count += 1
        managed.status = AgentStatus.RUNNING
        managed.last_invoked = datetime.now(tz=UTC)

        try:
            async for evt in run_agent_loop(
                managed.template.graph,
                run_config.input,
                config=config,
                context=agent_run.runtime_context(),
                hitl_handler=hitl_handler,
                run_id=run_id,
                agent_name=name,
            ):
                yield evt
        finally:
            await agent_run.teardown(sandbox_pool=sandbox_pool)
            self._active_runs.pop(run_id, None)
            managed.active_run_count = max(0, managed.active_run_count - 1)
            if managed.active_run_count == 0:
                managed.status = (
                    AgentStatus.COMPILED
                    if managed.template is not None
                    else AgentStatus.INSTALLED
                )

    async def list_agents(self) -> list[AgentMeta]:
        """List all installed agents with live runtime status overlays."""
        agents = await self._registry.list_agent_specs()
        result: list[AgentMeta] = []
        for agent in agents:
            status = self._agents.get(agent.name, None)
            result.append(
                AgentMeta(
                    name=agent.name,
                    version=agent.version,
                    description=agent.description,
                    tags=agent.tags,
                    status=status.status if status is not None else agent.status,
                )
            )
        return result

    async def get_agent_status(self, name: str) -> AgentStatus:
        """Get current status of an agent."""
        if name in self._agents:
            return self._agents[name].status
        spec = await self._registry.get_agent_spec(name)
        if spec is not None:
            return AgentStatus.INSTALLED
        raise KeyError(f"Agent '{name}' not found")

    # ── Internal ──

    def _has_live_runtime(self, managed: ManagedAgent) -> bool:
        """Return whether the managed agent has reusable runtime resources."""
        if managed.template is None or managed.sandbox_runtime is None:
            return False
        if managed.spec.mcp_servers and managed.mcp_runtime is None:
            return False
        return True

    def _create_sandbox_runtime(self, managed: ManagedAgent) -> SandboxRuntime:
        """Create the sandbox runtime owner for a compiled agent."""
        if self._use_shared_sandbox_pool:
            pool = self._sandbox_pool
        else:
            workspace_dir = str(self._registry.workspace_dir(managed.name))

            async def backend_factory(_spec: Any) -> Any:
                return LocalShellBackend(
                    root_dir=workspace_dir,
                    inherit_env=True,
                    virtual_mode=False,
                )

            pool = SandboxPool(backend_factory=backend_factory)

        return SandboxRuntime(
            spec=managed.spec.sandbox or {},
            pool=pool,
        )

    async def _release_managed_resources(self, managed: ManagedAgent) -> None:
        """Release compiled runtime resources owned by a managed agent."""
        if managed.mcp_runtime is not None:
            await managed.mcp_runtime.session_manager.cleanup()
            managed.mcp_runtime = None

        if managed.sandbox_runtime is not None:
            sandbox_pool = managed.sandbox_runtime.pool
            if not self._use_shared_sandbox_pool or sandbox_pool is not self._sandbox_pool:
                await sandbox_pool.shutdown()
            managed.sandbox_runtime = None

        managed.template = None

    async def _get_managed(self, name: str) -> ManagedAgent:
        """Get or create a ManagedAgent from registry."""
        if name not in self._agents:
            spec = await self._registry.get_agent_spec(name)
            if spec is None:
                raise KeyError(f"Agent '{name}' not found in registry")
            self._agents[name] = ManagedAgent(
                name=name,
                spec=spec,
                status=AgentStatus.INSTALLED,
            )
        return self._agents[name]

    async def _installed_model_providers(self) -> frozenset[str]:
        """Collect model providers from installed specs for startup warmup."""
        providers: set[str] = set()
        for meta in await self._registry.list_agent_specs():
            spec = await self._registry.get_agent_spec(meta.name)
            if spec is None:
                continue
            provider = self._spec_model_provider(spec)
            if provider:
                providers.add(provider)
        return frozenset(providers)

    def _spec_model_provider(self, spec: AgentSpec) -> str | None:
        """Extract the resolved model provider name from an agent spec."""
        if spec.model_config and spec.model_config.get("provider"):
            return spec.model_config["provider"]
        if ":" not in spec.model:
            return None
        return spec.model.split(":", 1)[0]
