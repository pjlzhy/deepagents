"""Unit tests for RuntimeAgent sandbox lifecycle behavior."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessageChunk

from deepagents.backends import LocalShellBackend
from deepagents_runtime.agent import RuntimeAgent
from deepagents_runtime.spec import AgentSpec, RuntimeEventType, SandboxRuntime


class FakeRegistry:
    """Minimal registry stub for RuntimeAgent lifecycle tests."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def workspace_dir(self, name: str) -> Path:
        path = self._base_dir / name / "workspace"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def memory_dir(self, name: str) -> Path:
        path = self._base_dir / name / "memory"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def skills_dir(self, name: str) -> Path:
        path = self._base_dir / name / "skills"
        path.mkdir(parents=True, exist_ok=True)
        return path


class FakeSandboxBackend:
    """Tracks cleanup for an agent-owned sandbox backend."""

    def __init__(self) -> None:
        self.cleanup_calls = 0

    async def cleanup(self) -> None:
        self.cleanup_calls += 1


class FakeManagedSandboxBackend:
    """Minimal async backend stub for sandbox selection tests."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.cleanup_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def cleanup(self) -> None:
        self.cleanup_calls += 1


class FakeGraph:
    """Minimal compiled graph stub that captures invocation context."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []
        self.messages: list[str] = []
        self.versions: list[str] = []

    async def astream(
            self,
            stream_input: dict[str, Any],
            *,
            config: dict[str, Any],
            context: Any = None,
            stream_mode: list[str],
            subgraphs: bool,
            version: str,
    ):
        del config, stream_mode, subgraphs
        self.contexts.append(context)
        self.messages.append(stream_input["messages"][0]["content"])
        self.versions.append(version)
        if False:
            yield None


class FakeInterruptGraph:
    """Compiled graph stub that interrupts once, then resumes successfully."""

    def __init__(self) -> None:
        self.calls = 0

    async def astream(
            self,
            stream_input: Any,
            *,
            config: dict[str, Any],
            context: Any = None,
            stream_mode: list[str],
            subgraphs: bool,
            version: str,
    ):
        del config, context, stream_mode, subgraphs, version
        self.calls += 1
        if self.calls == 1:
            yield {
                "type": "updates",
                "ns": (),
                "data": {
                    "__interrupt__": [
                        SimpleNamespace(
                            id="interrupt-1",
                            value={
                                "action_requests": [
                                    {
                                        "name": "execute",
                                        "args": {"command": "pwd"},
                                        "description": "Run pwd",
                                    }
                                ],
                                "review_configs": [
                                    {
                                        "action_name": "execute",
                                        "allowed_decisions": ["approve", "reject"],
                                    }
                                ],
                            },
                        )
                    ]
                },
            }
            return

        yield {
            "type": "messages",
            "ns": (),
            "data": (
                AIMessageChunk(content="approved"),
                {"langgraph_node": "model"},
            ),
        }


def _make_base_dir() -> Path:
    base_dir = Path.cwd() / ".codex_tmp" / "runtime-agent-lifecycle" / uuid.uuid4().hex
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _build_agent(base_dir: Path, *, sandbox: dict[str, Any] | None = None) -> RuntimeAgent:
    agent = RuntimeAgent(
        spec=AgentSpec(
            name="demo-agent",
            description="demo",
            sandbox=sandbox or {},
        ),
        reg=FakeRegistry(base_dir),
    )
    return agent


def test_assemble_creates_sandbox_runtime_once() -> None:
    """Assemble should create the sandbox runtime owner once per agent."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir, sandbox={"resources": {"backend": "local"}})
    fake_graph = FakeGraph()

    async def fake_load_mcp_tools(_configs: Any) -> tuple[list[Any], None, list[Any]]:
        return [], None, []

    try:
        with patch(
            "deepagents_runtime.agent.create_model",
            return_value=SimpleNamespace(model=object()),
        ):
            with patch(
                "deepagents_runtime.agent.load_mcp_tools_from_configs",
                fake_load_mcp_tools,
            ):
                with patch(
                    "deepagents_runtime.agent.MemoryMiddleware",
                    side_effect=lambda **_kwargs: object(),
                ):
                    with patch(
                        "deepagents_runtime.agent.RuntimeSkillsMiddleware",
                        side_effect=lambda **_kwargs: object(),
                    ):
                        with patch(
                            "deepagents_runtime.agent.create_summarization_middleware",
                            return_value=object(),
                        ):
                            with patch(
                                "deepagents_runtime.agent.SummarizationToolMiddleware",
                                side_effect=lambda middleware: middleware,
                            ):
                                with patch(
                                    "deepagents_runtime.agent.create_deep_agent",
                                    return_value=fake_graph,
                                ):
                                    with patch(
                                        "deepagents_runtime.agent.get_system_prompt",
                                        return_value="system prompt",
                                    ):
                                        async def scenario() -> tuple[Any, Any]:
                                            await agent.assemble()
                                            first_runtime = agent._sandbox_runtime
                                            await agent.assemble()
                                            second_runtime = agent._sandbox_runtime
                                            return first_runtime, second_runtime

                                        first_runtime, second_runtime = asyncio.run(scenario())

        assert first_runtime is not None
        assert first_runtime is second_runtime
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_astream_uses_agent_owned_sandbox_context() -> None:
    """astream should inject the agent-owned sandbox backend into runtime context."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir, sandbox={"resources": {"backend": "local"}})
    sandbox_backend = object()
    graph = FakeGraph()
    agent._graph = graph
    agent._sandbox_runtime = SandboxRuntime(
        spec={"resources": {"backend": "local"}},
        backend=sandbox_backend,
    )

    try:
        async def scenario() -> list[Any]:
            emitted: list[Any] = []
            async for event in agent.astream(
                context={"request_id": "req-1"},
                message="hello sandbox",
                config={"configurable": {"thread_id": "thread-1", "run_id": "run-1"}},
            ):
                emitted.append(event)
            return emitted

        events = asyncio.run(scenario())

        assert len(events) == 2
        assert graph.messages == ["hello sandbox"]
        assert graph.versions == ["v2"]
        assert graph.contexts[0]["request_id"] == "req-1"
        assert graph.contexts[0]["sandbox_backend"] is sandbox_backend
        assert agent._runtime_status == "assembled"
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_assemble_without_sandbox_spec_skips_sandbox_runtime() -> None:
    """Agents without a sandbox spec should not materialize a dedicated sandbox."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    fake_graph = FakeGraph()

    async def fake_load_mcp_tools(_configs: Any) -> tuple[list[Any], None, list[Any]]:
        return [], None, []

    try:
        with patch(
            "deepagents_runtime.agent.create_model",
            return_value=SimpleNamespace(model=object()),
        ):
            with patch(
                "deepagents_runtime.agent.load_mcp_tools_from_configs",
                fake_load_mcp_tools,
            ):
                with patch(
                    "deepagents_runtime.agent.MemoryMiddleware",
                    side_effect=lambda **_kwargs: object(),
                ):
                    with patch(
                        "deepagents_runtime.agent.RuntimeSkillsMiddleware",
                        side_effect=lambda **_kwargs: object(),
                    ):
                        with patch(
                            "deepagents_runtime.agent.create_summarization_middleware",
                            return_value=object(),
                        ):
                            with patch(
                                "deepagents_runtime.agent.SummarizationToolMiddleware",
                                side_effect=lambda middleware: middleware,
                            ):
                                with patch(
                                    "deepagents_runtime.agent.create_deep_agent",
                                    return_value=fake_graph,
                                ):
                                    with patch(
                                        "deepagents_runtime.agent.get_system_prompt",
                                        return_value="system prompt",
                                    ):
                                        asyncio.run(agent.assemble())

        assert agent._sandbox_runtime is None
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_astream_handles_hitl_with_local_interrupt_buffer() -> None:
    """astream should resume after HITL without storing interrupts on parser state."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    agent._graph = FakeInterruptGraph()

    try:
        async def scenario() -> list[Any]:
            emitted: list[Any] = []
            async for event in agent.astream(
                message="needs approval",
                config={"configurable": {"thread_id": "thread-1", "run_id": "run-1"}},
            ):
                emitted.append(event)
            return emitted

        emitted = asyncio.run(scenario())
        event_types = [event.type for event in emitted]

        assert event_types == [
            RuntimeEventType.RUN_START,
            RuntimeEventType.HITL_REQUEST,
            RuntimeEventType.TEXT_DELTA,
            RuntimeEventType.TEXT_DONE,
            RuntimeEventType.RUN_END,
        ]
        assert agent._graph.calls == 2
        assert agent._runtime_status == "assembled"
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_release_cleans_up_agent_owned_sandbox() -> None:
    """release should clean up the agent-owned sandbox backend."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    sandbox_backend = FakeSandboxBackend()
    agent._sandbox_runtime = SandboxRuntime(spec={}, backend=sandbox_backend)

    try:
        asyncio.run(agent.release())

        assert sandbox_backend.cleanup_calls == 1
        assert agent._sandbox_runtime is None
        assert agent._runtime_status == "released"
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_create_sandbox_runtime_uses_local_backend() -> None:
    """Explicit local sandbox specs should build a LocalShellBackend."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)

    try:
        runtime = asyncio.run(
            agent._create_sandbox_runtime(
                spec={"resources": {"backend": "local"}}
            )
        )

        assert isinstance(runtime.backend, LocalShellBackend)
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_create_sandbox_runtime_uses_docker_backend() -> None:
    """Docker backend selection should route through DockerSandboxBackend."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    fake_backend = FakeManagedSandboxBackend()

    async def fake_from_spec(_spec: dict[str, Any]) -> FakeManagedSandboxBackend:
        return fake_backend

    try:
        with patch(
            "deepagents_runtime.agent.DockerSandboxBackend.from_spec",
            new=fake_from_spec,
        ):
            runtime = asyncio.run(
                agent._create_sandbox_runtime(
                    spec={"resources": {"backend": "docker"}, "image": "python:3.12"}
                )
            )

        assert runtime.backend is fake_backend
        assert fake_backend.start_calls == 1
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_create_sandbox_runtime_uses_image_as_docker_signal() -> None:
    """An image-only sandbox spec should default to the Docker backend."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    fake_backend = FakeManagedSandboxBackend()

    async def fake_from_spec(_spec: dict[str, Any]) -> FakeManagedSandboxBackend:
        return fake_backend

    try:
        with patch(
            "deepagents_runtime.agent.DockerSandboxBackend.from_spec",
            new=fake_from_spec,
        ):
            runtime = asyncio.run(
                agent._create_sandbox_runtime(spec={"image": "python:3.12"})
            )

        assert runtime.backend is fake_backend
        assert fake_backend.start_calls == 1
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_create_sandbox_runtime_rejects_unknown_backend() -> None:
    """Unknown sandbox backends should fail fast during runtime creation."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)

    try:
        try:
            asyncio.run(
                agent._create_sandbox_runtime(
                    spec={"resources": {"backend": "modal"}}
                )
            )
        except ValueError as exc:
            assert "sandbox backend 'modal'" in str(exc)
        else:
            raise AssertionError("expected ValueError for unknown backend")
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_create_sandbox_runtime_rejects_k8s_backend_until_implemented() -> None:
    """K8s backend requests should surface the current not-implemented error."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)

    try:
        try:
            asyncio.run(
                agent._create_sandbox_runtime(
                    spec={"resources": {"backend": "k8s"}, "image": "python:3.12"}
                )
            )
        except NotImplementedError as exc:
            assert "K8s sandbox is not yet implemented" in str(exc)
        else:
            raise AssertionError("expected NotImplementedError for k8s backend")
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
