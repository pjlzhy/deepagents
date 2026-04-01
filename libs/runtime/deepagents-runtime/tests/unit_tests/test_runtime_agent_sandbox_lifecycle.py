"""Unit tests for RuntimeAgent sandbox lifecycle behavior."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage
from langchain_core.messages import AIMessageChunk

from deepagents.backends import LocalShellBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from deepagents_runtime.agent import RuntimeAgent
from deepagents_runtime.runtime_backend import ThreadRuntimeBackend
from deepagents_runtime.runtime_filesystem import RuntimeFilesystemMiddleware
from deepagents_runtime.spec import AgentSpec, RuntimeEventType, SandboxRuntime


class FakeRegistry:
    """Minimal registry stub for RuntimeAgent lifecycle tests."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def runtime_dir(self, name: str) -> Path:
        path = self._base_dir / name / "runtime"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def shared_dir(self, name: str) -> Path:
        path = self.runtime_dir(name) / "shared"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def shared_skills_dir(self, name: str) -> Path:
        path = self.shared_dir(name) / "skills"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def shared_memory_file(self, name: str) -> Path:
        path = self.shared_dir(name) / "memory" / "AGENTS.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    def threads_dir(self, name: str) -> Path:
        path = self.runtime_dir(name) / "threads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def thread_root_dir(self, name: str, thread_id: str) -> Path:
        path = self.threads_dir(name) / thread_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def thread_runtime_dir(self, name: str, thread_id: str) -> Path:
        path = self.thread_root_dir(name, thread_id) / ".runtime"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def thread_memory_file(self, name: str, thread_id: str) -> Path:
        path = self.thread_runtime_dir(name, thread_id) / "memory" / "AGENTS.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def thread_skills_dir(self, name: str, thread_id: str) -> Path:
        path = self.thread_runtime_dir(name, thread_id) / "skills"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def thread_history_dir(self, name: str, thread_id: str) -> Path:
        path = self.thread_runtime_dir(name, thread_id) / "conversation_history"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def materialize_thread_root(self, name: str, thread_id: str) -> Path:
        root = self.thread_root_dir(name, thread_id)
        memory_file = self.thread_memory_file(name, thread_id)
        skills_dir = self.thread_skills_dir(name, thread_id)
        self.thread_history_dir(name, thread_id)

        shared_memory = self.shared_memory_file(name)
        if not memory_file.exists():
            if shared_memory.exists():
                memory_file.write_text(shared_memory.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                memory_file.touch()

        shared_skills = self.shared_skills_dir(name)
        if shared_skills.exists() and not any(skills_dir.iterdir()):
            shutil.copytree(shared_skills, skills_dir, dirs_exist_ok=True)
        return root

    def delete_thread_dir(self, name: str, thread_id: str) -> None:
        shutil.rmtree(self.thread_root_dir(name, thread_id), ignore_errors=True)

    # Backward-compatible aliases used by some existing assertions.
    def skills_dir(self, name: str) -> Path:
        return self.shared_skills_dir(name)

    def memory_dir(self, name: str) -> Path:
        return self.shared_memory_file(name)


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


def _make_tool_runtime() -> ToolRuntime[Any, Any]:
    return ToolRuntime(
        state={"messages": []},
        context=None,
        tool_call_id="tool-call-1",
        store=None,
        stream_writer=lambda _: None,
        config={},
    )


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
                            "deepagents_runtime.agent.compute_summarization_defaults",
                            return_value={
                                "trigger": ("messages", 10),
                                "keep": ("messages", 2),
                                "truncate_args_settings": {"trigger": ("messages", 10)},
                            },
                        ):
                            with patch(
                                "deepagents_runtime.agent.SummarizationMiddleware",
                                return_value=object(),
                            ):
                                with patch(
                                    "deepagents_runtime.agent.SummarizationToolMiddleware",
                                    side_effect=lambda middleware: middleware,
                                ):
                                    with patch(
                                        "deepagents_runtime.agent.create_runtime_deep_agent",
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


def test_assemble_without_sandbox_uses_one_filesystem_view_for_runtime_components() -> None:
    """Assemble should wire memory, skills, tools, and prompt to one filesystem view."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    fake_graph = FakeGraph()
    captured: dict[str, Any] = {}
    model = object()

    async def fake_load_mcp_tools(_configs: Any) -> tuple[list[Any], None, list[Any]]:
        return [], None, []

    def fake_memory_middleware(**kwargs: Any) -> object:
        captured["memory_kwargs"] = kwargs
        return object()

    def fake_skills_middleware(**kwargs: Any) -> object:
        captured["skills_kwargs"] = kwargs
        return object()

    def fake_summarization_middleware(**kwargs: Any) -> object:
        captured["summarization_kwargs"] = kwargs
        return object()

    def fake_get_system_prompt(**kwargs: Any) -> str:
        captured["filesystem_view"] = kwargs["filesystem_view"]
        return "system prompt"

    def fake_create_runtime_deep_agent(**kwargs: Any) -> FakeGraph:
        captured["tool_backend"] = kwargs["backend"]
        return fake_graph

    try:
        with patch(
            "deepagents_runtime.agent.create_model",
            return_value=SimpleNamespace(
                model=model,
                model_name="gpt-5.2",
                provider="openai",
                context_limit=128000,
            ),
        ):
            with patch(
                "deepagents_runtime.agent.load_mcp_tools_from_configs",
                fake_load_mcp_tools,
            ):
                with patch(
                    "deepagents_runtime.agent.MemoryMiddleware",
                    side_effect=fake_memory_middleware,
                ):
                    with patch(
                        "deepagents_runtime.agent.RuntimeSkillsMiddleware",
                        side_effect=fake_skills_middleware,
                    ):
                        with patch(
                            "deepagents_runtime.agent.compute_summarization_defaults",
                            return_value={
                                "trigger": ("messages", 10),
                                "keep": ("messages", 2),
                                "truncate_args_settings": {"trigger": ("messages", 10)},
                            },
                        ):
                            with patch(
                                "deepagents_runtime.agent.SummarizationMiddleware",
                                side_effect=fake_summarization_middleware,
                            ):
                                with patch(
                                    "deepagents_runtime.agent.SummarizationToolMiddleware",
                                    side_effect=lambda middleware: middleware,
                                ):
                                    with patch(
                                        "deepagents_runtime.agent.create_runtime_deep_agent",
                                        side_effect=fake_create_runtime_deep_agent,
                                    ):
                                        with patch(
                                            "deepagents_runtime.agent.get_system_prompt",
                                            side_effect=fake_get_system_prompt,
                                        ):
                                            asyncio.run(agent.assemble())

        tool_backend = captured["tool_backend"]
        filesystem_view = captured["filesystem_view"]

        tool_runtime = ToolRuntime(
            state={"messages": []},
            context=None,
            tool_call_id="tool-call-1",
            store=None,
            stream_writer=lambda _: None,
            config={"configurable": {"thread_id": "thread-1"}},
        )
        thread_backend = tool_backend(tool_runtime)

        assert isinstance(thread_backend, ThreadRuntimeBackend)
        assert filesystem_view.host_runtime_dir == (
            base_dir / "demo-agent" / "runtime"
        ).resolve()
        assert filesystem_view.host_threads_dir == (
            base_dir / "demo-agent" / "runtime" / "threads"
        ).resolve()
        assert filesystem_view.host_shared_memory_file == (
            base_dir / "demo-agent" / "runtime" / "shared" / "memory" / "AGENTS.md"
        ).resolve()
        assert filesystem_view.host_shared_skills_dir == (
            base_dir / "demo-agent" / "runtime" / "shared" / "skills"
        ).resolve()
        assert filesystem_view.visible_workspace_path == "."
        assert filesystem_view.visible_skills_path == ".runtime/skills"
        assert filesystem_view.visible_memory_path == ".runtime/memory/AGENTS.md"
        assert filesystem_view.visible_history_path_prefix == ".runtime/conversation_history"
        assert captured["memory_kwargs"] == {
            "backend": tool_backend,
            "sources": [filesystem_view.visible_memory_path],
        }
        assert captured["skills_kwargs"] == {
            "backend": tool_backend,
            "sources": [filesystem_view.visible_skills_path],
        }
        assert captured["summarization_kwargs"] == {
            "model": model,
            "backend": tool_backend,
            "trigger": ("messages", 10),
            "keep": ("messages", 2),
            "trim_tokens_to_summarize": None,
            "history_path_prefix": ".runtime/conversation_history",
            "truncate_args_settings": {"trigger": ("messages", 10)},
        }
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_local_runtime_filesystem_ls_hides_runtime_dir_by_default() -> None:
    """Runtime filesystem middleware should expose workspace-relative paths."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    filesystem_view = agent._build_filesystem_view(spec=None)
    shell_backend = agent._build_local_backend(filesystem_view=filesystem_view)
    thread_backend = ThreadRuntimeBackend.for_local(
        shell_backend=shell_backend,
        thread_root_dir=agent.registry.materialize_thread_root(agent.spec.name, "thread-1"),
    )
    middleware = RuntimeFilesystemMiddleware(backend=thread_backend)
    ls_tool = next(tool for tool in middleware.tools if tool.name == "ls")

    try:
        skills_dir = agent.registry.shared_skills_dir(agent.spec.name) / "demo-skill"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "SKILL.md").write_text("# Demo Skill\n", encoding="utf-8")
        (agent.registry.thread_root_dir(agent.spec.name, "thread-1") / "A.txt").write_text(
            "hello\n",
            encoding="utf-8",
        )

        result = ls_tool.invoke(
            {
                "path": ".",
                "runtime": _make_tool_runtime(),
            }
        )

        assert "A.txt" in result
        assert ".runtime/" not in result
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_local_runtime_filesystem_reads_thread_memory_snapshot() -> None:
    """Runtime filesystem middleware should read thread-local memory snapshots."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    filesystem_view = agent._build_filesystem_view(spec=None)
    agent.registry.shared_memory_file(agent.spec.name).write_text(
        "remember this preference\n",
        encoding="utf-8",
    )
    shell_backend = agent._build_local_backend(filesystem_view=filesystem_view)
    thread_backend = ThreadRuntimeBackend.for_local(
        shell_backend=shell_backend,
        thread_root_dir=agent.registry.materialize_thread_root(agent.spec.name, "thread-1"),
    )
    middleware = RuntimeFilesystemMiddleware(backend=thread_backend)
    read_tool = next(tool for tool in middleware.tools if tool.name == "read_file")

    try:
        result = read_tool.invoke(
            {
                "file_path": ".runtime/memory/AGENTS.md",
                "runtime": _make_tool_runtime(),
            }
        )

        assert "remember this preference" in result
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_local_runtime_shell_pwd_starts_in_thread_root() -> None:
    """Thread backend execution should start in the current thread root."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    filesystem_view = agent._build_filesystem_view(spec=None)
    shell_backend = agent._build_local_backend(filesystem_view=filesystem_view)
    thread_root = agent.registry.materialize_thread_root(agent.spec.name, "thread-1")
    backend = ThreadRuntimeBackend.for_local(
        shell_backend=shell_backend,
        thread_root_dir=thread_root,
    )

    try:
        result = backend.execute("pwd")

        assert result.exit_code == 0
        assert result.output.strip() == str(thread_root)
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_local_runtime_summarization_history_offloads_under_thread_root() -> None:
    """Summarization offloads should stay within the current thread runtime dir."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    filesystem_view = agent._build_filesystem_view(spec=None)
    shell_backend = agent._build_local_backend(filesystem_view=filesystem_view)
    thread_root = agent.registry.materialize_thread_root(agent.spec.name, "thread-1")
    backend = ThreadRuntimeBackend.for_local(
        shell_backend=shell_backend,
        thread_root_dir=thread_root,
    )
    model = MagicMock()
    model.profile = {"max_input_tokens": 200_000}
    model._get_ls_params.return_value = {"ls_provider": "test"}
    response = MagicMock()
    response.text = "summary"
    response.content = "summary"
    model.invoke.return_value = response
    model.ainvoke = MagicMock(return_value=response)
    middleware = SummarizationMiddleware(
        model=model,
        backend=backend,
        trigger=("messages", 10),
        history_path_prefix=filesystem_view.visible_history_path_prefix,
    )

    try:
        with patch.object(
            middleware,
            "_get_history_path",
            return_value=".runtime/conversation_history/test-thread.md",
        ):
            path = middleware._offload_to_backend(
                backend,
                [HumanMessage(content="hello from history")],
            )

        assert path == ".runtime/conversation_history/test-thread.md"
        history_file = agent.registry.thread_history_dir(agent.spec.name, "thread-1") / "test-thread.md"
        assert history_file.exists()
        assert "hello from history" in history_file.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_astream_preserves_runtime_context() -> None:
    """astream should pass the caller-provided runtime context through unchanged."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir, sandbox={"resources": {"backend": "local"}})
    graph = FakeGraph()
    agent._graph = graph
    agent._sandbox_runtime = SandboxRuntime(
        spec={"resources": {"backend": "local"}},
        backend=object(),
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
        assert graph.contexts[0] == {"request_id": "req-1"}
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
                            "deepagents_runtime.agent.compute_summarization_defaults",
                            return_value={
                                "trigger": ("messages", 10),
                                "keep": ("messages", 2),
                                "truncate_args_settings": {"trigger": ("messages", 10)},
                            },
                        ):
                            with patch(
                                "deepagents_runtime.agent.SummarizationMiddleware",
                                return_value=object(),
                            ):
                                with patch(
                                    "deepagents_runtime.agent.SummarizationToolMiddleware",
                                    side_effect=lambda middleware: middleware,
                                ):
                                    with patch(
                                        "deepagents_runtime.agent.create_runtime_deep_agent",
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
                spec={"resources": {"backend": "local"}},
                filesystem_view=agent._build_filesystem_view(
                    spec={"resources": {"backend": "local"}}
                ),
            )
        )

        assert isinstance(runtime.backend, LocalShellBackend)
        assert runtime.backend.cwd == (base_dir / "demo-agent" / "runtime").resolve()
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_create_sandbox_runtime_uses_docker_backend() -> None:
    """Docker backend selection should route through DockerSandboxBackend."""

    base_dir = _make_base_dir()
    agent = _build_agent(base_dir)
    fake_backend = FakeManagedSandboxBackend()

    async def fake_from_spec(
        _spec: dict[str, Any],
        *,
        host_mount_dir: str | None = None,
        container_root: str = "/agent",
    ) -> FakeManagedSandboxBackend:
        del host_mount_dir, container_root
        return fake_backend

    try:
        with patch(
            "deepagents_runtime.agent.DockerSandboxBackend.from_spec",
            new=fake_from_spec,
        ):
            runtime = asyncio.run(
                agent._create_sandbox_runtime(
                    spec={"resources": {"backend": "docker"}, "image": "python:3.12"},
                    filesystem_view=agent._build_filesystem_view(
                        spec={"resources": {"backend": "docker"}, "image": "python:3.12"}
                    ),
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

    async def fake_from_spec(
        _spec: dict[str, Any],
        *,
        host_mount_dir: str | None = None,
        container_root: str = "/agent",
    ) -> FakeManagedSandboxBackend:
        del host_mount_dir, container_root
        return fake_backend

    try:
        with patch(
            "deepagents_runtime.agent.DockerSandboxBackend.from_spec",
            new=fake_from_spec,
        ):
            runtime = asyncio.run(
                agent._create_sandbox_runtime(
                    spec={"image": "python:3.12"},
                    filesystem_view=agent._build_filesystem_view(
                        spec={"image": "python:3.12"}
                    ),
                )
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
                    spec={"resources": {"backend": "modal"}},
                    filesystem_view=agent._build_filesystem_view(
                        spec={"resources": {"backend": "modal"}}
                    ),
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
                    spec={"resources": {"backend": "k8s"}, "image": "python:3.12"},
                    filesystem_view=agent._build_filesystem_view(
                        spec={"resources": {"backend": "k8s"}, "image": "python:3.12"}
                    ),
                )
            )
        except NotImplementedError as exc:
            assert "K8s sandbox is not yet implemented" in str(exc)
        else:
            raise AssertionError("expected NotImplementedError for k8s backend")
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
