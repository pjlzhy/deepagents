"""Unit tests for AgentManager runtime lifecycle behavior."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from deepagents_runtime.manager.manager import AgentManager
from deepagents_runtime.spec import (
    AgentMeta,
    AgentSpec,
    AgentStatus,
    AgentTemplate,
    MCPRuntime,
    RunConfig,
    SandboxRuntime,
)


class FakeRegistry:
    """Minimal registry stub for manager lifecycle tests."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._specs: dict[str, AgentSpec] = {}

    async def add_agent_spec(self, spec: AgentSpec) -> None:
        self._specs[spec.name] = spec

    async def get_agent_spec(self, name: str) -> AgentSpec | None:
        return self._specs.get(name)

    async def list_agent_specs(self) -> list[AgentMeta]:
        return [
            AgentMeta(
                name=spec.name,
                version=spec.version,
                description=spec.description,
                tags=spec.tags,
                status=AgentStatus.INSTALLED,
            )
            for spec in self._specs.values()
        ]

    async def delete_agent_spec(self, name: str) -> bool:
        return self._specs.pop(name, None) is not None

    def workspace_dir(self, name: str) -> Path:
        path = self._base_dir / name / "workspace"
        path.mkdir(parents=True, exist_ok=True)
        return path


class FakeSessionManager:
    """Tracks MCP cleanup calls."""

    def __init__(self) -> None:
        self.cleanup_calls = 0

    async def cleanup(self) -> None:
        self.cleanup_calls += 1


class FakeSandboxPool:
    """Tracks sandbox acquire / release / shutdown behavior."""

    def __init__(self, sandbox: Any) -> None:
        self._sandbox = sandbox
        self.acquire_specs: list[dict[str, Any]] = []
        self.release_calls = 0
        self.shutdown_calls = 0

    async def acquire(self, spec: dict[str, Any]) -> Any:
        self.acquire_specs.append(spec)
        return self._sandbox

    async def release(self, sandbox: Any) -> None:
        assert sandbox is self._sandbox
        self.release_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


@dataclass
class AssembleFixtures:
    """Reusable fixtures returned by the fake assembler."""

    template: AgentTemplate
    session_manager: FakeSessionManager
    sandbox_pool: FakeSandboxPool
    sandbox_backend: Any


def _build_spec() -> AgentSpec:
    return AgentSpec(
        name="demo-agent",
        description="demo",
    )


def _build_assemble_fixtures() -> AssembleFixtures:
    sandbox_backend = object()
    session_manager = FakeSessionManager()
    sandbox_pool = FakeSandboxPool(sandbox_backend)
    template = AgentTemplate(
        graph=object(),
        sandbox_spec={},
        mcp_configs=[],
        resolved_spec=_build_spec(),
    )
    return AssembleFixtures(
        template=template,
        session_manager=session_manager,
        sandbox_pool=sandbox_pool,
        sandbox_backend=sandbox_backend,
    )


def _make_base_dir() -> Path:
    base_dir = Path.cwd() / ".codex_tmp" / "manager-lifecycle" / uuid.uuid4().hex
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def test_invoke_uses_sandbox_context_and_restores_status() -> None:
    """Invoke should borrow a sandbox lease and return to COMPILED."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    fixtures = _build_assemble_fixtures()
    captured: dict[str, Any] = {}

    async def fake_setup() -> None:
        return None

    async def fake_assemble(
        spec: AgentSpec,
        _registry: Any,
        *,
        checkpointer: Any = None,
        _assembling: frozenset[str] = frozenset(),
    ) -> tuple[AgentTemplate, MCPRuntime]:
        del spec, _registry, checkpointer, _assembling
        return fixtures.template, MCPRuntime(session_manager=fixtures.session_manager)

    async def fake_run_agent_loop(
        agent: Any,
        message: str,
        *,
        config: dict[str, Any],
        context: Any = None,
        hitl_handler: Any = None,
        run_id: str = "",
        agent_name: str = "",
    ) -> AsyncIterator[dict[str, str]]:
        del agent, hitl_handler
        captured["message"] = message
        captured["config"] = config
        captured["context"] = context
        captured["run_id"] = run_id
        captured["agent_name"] = agent_name
        yield {"event": "ok"}

    try:
        with patch.object(manager, "setup", fake_setup):
            with patch("deepagents_runtime.manager.manager.assemble", fake_assemble):
                with patch.object(
                    AgentManager,
                    "_create_sandbox_runtime",
                    lambda self, managed: SandboxRuntime(
                        spec=managed.spec.sandbox or {},
                        pool=fixtures.sandbox_pool,
                    ),
                ):
                    with patch(
                        "deepagents_runtime.manager.manager.run_agent_loop",
                        fake_run_agent_loop,
                    ):
                        async def scenario() -> tuple[list[Any], AgentManager]:
                            await manager.define_agent(_build_spec())
                            events: list[Any] = []
                            async for event in manager.invoke(
                                "demo-agent",
                                RunConfig(
                                    input="hello",
                                    thread_id="thread-1",
                                    run_id="run-1",
                                ),
                            ):
                                events.append(event)
                            return events, manager

                        events, _manager = asyncio.run(scenario())
                        managed = _manager._agents["demo-agent"]

                        assert events == [{"event": "ok"}]
                        assert captured["message"] == "hello"
                        assert captured["config"] == {
                            "configurable": {"thread_id": "thread-1"}
                        }
                        assert captured["context"] == {
                            "sandbox_backend": fixtures.sandbox_backend
                        }
                        assert captured["run_id"] == "run-1"
                        assert captured["agent_name"] == "demo-agent"
                        assert fixtures.sandbox_pool.acquire_specs == [{}]
                        assert fixtures.sandbox_pool.release_calls == 1
                        assert managed.status == AgentStatus.COMPILED
                        assert managed.active_run_count == 0
                        assert managed.last_invoked is not None
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_unload_agent_releases_compiled_resources() -> None:
    """unload_agent should clean up compiled runtime resources."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    fixtures = _build_assemble_fixtures()

    async def fake_setup() -> None:
        return None

    async def fake_assemble(
        spec: AgentSpec,
        _registry: Any,
        *,
        checkpointer: Any = None,
        _assembling: frozenset[str] = frozenset(),
    ) -> tuple[AgentTemplate, MCPRuntime]:
        del spec, _registry, checkpointer, _assembling
        return fixtures.template, MCPRuntime(session_manager=fixtures.session_manager)

    try:
        with patch.object(manager, "setup", fake_setup):
            with patch("deepagents_runtime.manager.manager.assemble", fake_assemble):
                with patch.object(
                    AgentManager,
                    "_create_sandbox_runtime",
                    lambda self, managed: SandboxRuntime(
                        spec=managed.spec.sandbox or {},
                        pool=fixtures.sandbox_pool,
                    ),
                ):
                    async def scenario() -> AgentManager:
                        await manager.define_agent(_build_spec())
                        await manager.assemble_agent("demo-agent")
                        await manager.unload_agent("demo-agent")
                        return manager

                    _manager = asyncio.run(scenario())
                    managed = _manager._agents["demo-agent"]

                    assert fixtures.session_manager.cleanup_calls == 1
                    assert fixtures.sandbox_pool.shutdown_calls == 1
                    assert managed.template is None
                    assert managed.mcp_runtime is None
                    assert managed.sandbox_runtime is None
                    assert managed.status == AgentStatus.INSTALLED
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_remove_agent_uninstalls_spec_and_runtime() -> None:
    """remove_agent should unload runtime state and delete the installed spec."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    fixtures = _build_assemble_fixtures()

    async def fake_setup() -> None:
        return None

    async def fake_assemble(
        spec: AgentSpec,
        _registry: Any,
        *,
        checkpointer: Any = None,
        _assembling: frozenset[str] = frozenset(),
    ) -> tuple[AgentTemplate, MCPRuntime]:
        del spec, _registry, checkpointer, _assembling
        return fixtures.template, MCPRuntime(session_manager=fixtures.session_manager)

    try:
        with patch.object(manager, "setup", fake_setup):
            with patch("deepagents_runtime.manager.manager.assemble", fake_assemble):
                with patch.object(
                    AgentManager,
                    "_create_sandbox_runtime",
                    lambda self, managed: SandboxRuntime(
                        spec=managed.spec.sandbox or {},
                        pool=fixtures.sandbox_pool,
                    ),
                ):
                    async def scenario() -> bool:
                        await manager.define_agent(_build_spec())
                        await manager.assemble_agent("demo-agent")
                        return await manager.remove_agent("demo-agent")

                    removed = asyncio.run(scenario())

                    assert removed is True
                    assert fixtures.session_manager.cleanup_calls == 1
                    assert fixtures.sandbox_pool.shutdown_calls == 1
                    assert "demo-agent" not in manager._agents
                    assert asyncio.run(registry.get_agent_spec("demo-agent")) is None
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_setup_warms_runtime_dependencies_once() -> None:
    """setup should warm the runtime stack only on first initialization."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)

    @asynccontextmanager
    async def fake_get_checkpointer() -> AsyncIterator[object]:
        yield object()

    try:
        with patch(
            "deepagents_runtime.manager.manager.get_checkpointer",
            fake_get_checkpointer,
        ):
            with patch(
                "deepagents_runtime.manager.manager.warm_runtime_dependencies",
            ) as warmup:
                async def scenario() -> None:
                    await manager.setup()
                    await manager.setup()
                    await manager.shutdown()

                asyncio.run(scenario())

                warmup.assert_called_once_with(model_providers=frozenset())
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_define_agent_warms_model_provider_dependencies() -> None:
    """define_agent should prewarm the installed spec's model provider."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    spec = AgentSpec(
        name="demo-agent",
        description="demo",
        model="openai:gpt-5.2",
    )

    try:
        with patch(
            "deepagents_runtime.manager.manager.warm_runtime_dependencies",
        ) as warmup:
            asyncio.run(manager.define_agent(spec))

            warmup.assert_called_once_with(
                model_providers=frozenset({"openai"}),
            )
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
