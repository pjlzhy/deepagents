"""Unit tests for the RuntimeAgent-based AgentManager."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from deepagents_runtime import events as runtime_events
from deepagents_runtime.manager.manager import AgentManager
from deepagents_runtime.spec import (
    AgentMeta,
    AgentSpec,
    AgentStatus,
    RunConfig,
    RuntimeEventType,
)


class FakeRegistry:
    """Minimal registry stub for manager tests."""

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

    def runtime_dir(self, name: str) -> Path:
        path = self._base_dir / name / "runtime"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def shared_dir(self, name: str) -> Path:
        path = self.runtime_dir(name) / "shared"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def shared_memory_file(self, name: str) -> Path:
        path = self.shared_dir(name) / "memory" / "AGENTS.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    def shared_skills_dir(self, name: str) -> Path:
        path = self.shared_dir(name) / "skills"
        path.mkdir(parents=True, exist_ok=True)
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
        if not memory_file.exists():
            memory_file.write_text(self.shared_memory_file(name).read_text(encoding="utf-8"), encoding="utf-8")
        shared_skills = self.shared_skills_dir(name)
        if shared_skills.exists() and not any(skills_dir.iterdir()):
            shutil.copytree(shared_skills, skills_dir, dirs_exist_ok=True)
        return root

    def delete_thread_dir(self, name: str, thread_id: str) -> None:
        shutil.rmtree(self.thread_root_dir(name, thread_id), ignore_errors=True)


def _make_base_dir() -> Path:
    base_dir = Path.cwd() / ".codex_tmp" / "manager-runtime-agent" / uuid.uuid4().hex
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _build_spec(*, model: str = "openai:gpt-5.2") -> AgentSpec:
    return AgentSpec(
        name="demo-agent",
        description="demo",
        model=model,
    )


@asynccontextmanager
async def _fake_checkpointer() -> AsyncIterator[object]:
    yield object()


def test_define_agent_installs_without_compiling_and_invalidates_runtime() -> None:
    """define_agent should persist the spec and unload stale runtime."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> tuple[AgentSpec, AgentSpec, AgentStatus, bool]:
                first_spec = _build_spec(model="openai:gpt-5.2")
                second_spec = _build_spec(model="anthropic:claude-sonnet-4-6")

                await manager.define_agent(first_spec)
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()

                await manager.define_agent(second_spec)
                stored = await registry.get_agent_spec("demo-agent")
                return agent.spec, stored, agent.status(), agent.has_runtime()

            in_memory_spec, stored_spec, status, has_runtime = asyncio.run(scenario())

        assert in_memory_spec.model == "anthropic:claude-sonnet-4-6"
        assert stored_spec is not None
        assert stored_spec.model == "anthropic:claude-sonnet-4-6"
        assert status == AgentStatus.INSTALLED
        assert has_runtime is False
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_assemble_agent_safe_recompile_releases_old_runtime_first() -> None:
    """assemble_agent should release old runtime and compile the latest stored spec."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    calls: list[tuple[str, str]] = []

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> tuple[str, AgentStatus]:
                await manager.define_agent(_build_spec(model="openai:gpt-5.2"))
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()

                await registry.add_agent_spec(_build_spec(model="anthropic:claude-sonnet-4-6"))

                async def fake_release() -> None:
                    calls.append(("release", agent.spec.model))
                    agent._graph = None

                async def fake_assemble(*, checkpointer: Any = None) -> None:
                    del checkpointer
                    calls.append(("assemble", agent.spec.model))
                    agent._graph = object()

                with patch.object(agent, "release", fake_release):
                    with patch.object(agent, "assemble", fake_assemble):
                        await manager.assemble_agent("demo-agent")
                return agent.spec.model, agent.status()

            model, status = asyncio.run(scenario())

        assert calls == [
            ("release", "openai:gpt-5.2"),
            ("assemble", "anthropic:claude-sonnet-4-6"),
        ]
        assert model == "anthropic:claude-sonnet-4-6"
        assert status == AgentStatus.COMPILED
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_invoke_passes_message_thread_id_and_run_id() -> None:
    """invoke should forward the user input and both identifiers to RuntimeAgent."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    captured: dict[str, Any] = {}

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> list[Any]:
                await manager.define_agent(_build_spec())
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()

                async def fake_astream(
                        *,
                        context: Any = None,
                        message: str,
                        config: dict[str, Any],
                        hitl_handler: Any = None,
                ) -> AsyncIterator[dict[str, str]]:
                    del context, hitl_handler
                    captured["message"] = message
                    captured["config"] = config
                    yield {"event": "ok"}

                with patch.object(agent, "astream", fake_astream):
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
                    captured["last_invoked"] = agent.last_invoked
                    return events

            events = asyncio.run(scenario())

        assert events == [{"event": "ok"}]
        assert captured["message"] == "hello"
        assert captured["config"]["configurable"] == {
            "thread_id": "thread-1",
            "run_id": "run-1",
        }
        assert captured["config"]["metadata"]["agent_name"] == "demo-agent"
        updated_at = datetime.fromisoformat(captured["config"]["metadata"]["updated_at"])
        assert updated_at.tzinfo == UTC
        assert captured["last_invoked"] is not None
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_upload_workspace_files_generates_thread_and_delegates_to_runtime_agent() -> None:
    """upload_workspace_files should generate a thread ID and call the runtime agent."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    captured: dict[str, Any] = {}

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> tuple[str, list[Any]]:
                await manager.define_agent(_build_spec())
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()

                async def fake_upload_workspace_files(
                        *,
                        thread_id: str,
                        files: list[tuple[str, bytes]],
                ) -> list[Any]:
                    captured["thread_id"] = thread_id
                    captured["files"] = files
                    return [SimpleNamespace(path="report.txt", error=None)]

                with patch.object(agent, "upload_workspace_files", fake_upload_workspace_files):
                    return await manager.upload_workspace_files(
                        name="demo-agent",
                        thread_id="",
                        files=[("report.txt", b"hello")],
                    )

            thread_id, responses = asyncio.run(scenario())

        assert len(thread_id) == 8
        assert captured["thread_id"] == thread_id
        assert captured["files"] == [("report.txt", b"hello")]
        assert responses[0].path == "report.txt"
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_list_agents_overlays_runtime_status() -> None:
    """list_agents should overlay compiled and running status from the pool."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> tuple[AgentStatus, AgentStatus, AgentStatus]:
                await manager.define_agent(_build_spec())
                installed = await manager.list_agents()

                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()
                compiled = await manager.list_agents()

                agent._runtime_status = "running"
                running = await manager.list_agents()
                return installed[0].status, compiled[0].status, running[0].status

            installed_status, compiled_status, running_status = asyncio.run(scenario())

        assert installed_status == AgentStatus.INSTALLED
        assert compiled_status == AgentStatus.COMPILED
        assert running_status == AgentStatus.RUNNING
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_define_agent_rejects_invalid_update_without_releasing_runtime() -> None:
    """Invalid redefinition should fail before unloading the current runtime."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    calls: list[str] = []

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> tuple[str, bool, str]:
                await manager.define_agent(_build_spec(model="openai:gpt-5.2"))
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()

                async def fake_release() -> None:
                    calls.append("release")
                    agent._graph = None

                with patch.object(agent, "release", fake_release):
                    try:
                        await manager.define_agent(_build_spec(model="invalid-model"))
                    except ValueError as exc:
                        return str(exc), agent.has_runtime(), agent.spec.model
                raise AssertionError("Expected ValueError")

            message, has_runtime, model = asyncio.run(scenario())

        assert "provider:model format" in message
        assert calls == []
        assert has_runtime is True
        assert model == "openai:gpt-5.2"
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_assemble_agent_rejects_invalid_stored_spec_without_releasing_runtime() -> None:
    """Invalid stored specs should fail before replacing the current runtime."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    calls: list[str] = []

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> tuple[str, bool, str]:
                await manager.define_agent(_build_spec(model="openai:gpt-5.2"))
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()
                registry._specs["demo-agent"] = _build_spec(model="invalid-model")

                async def fake_release() -> None:
                    calls.append("release")
                    agent._graph = None

                with patch.object(agent, "release", fake_release):
                    try:
                        await manager.assemble_agent("demo-agent")
                    except ValueError as exc:
                        return str(exc), agent.has_runtime(), agent.spec.model
                raise AssertionError("Expected ValueError")

            message, has_runtime, model = asyncio.run(scenario())

        assert "provider:model format" in message
        assert calls == []
        assert has_runtime is True
        assert model == "openai:gpt-5.2"
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_invoke_emits_run_canceled_and_cleans_up_runtime_task() -> None:
    """Cancel requests should terminate the run via the manager lifecycle."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    cleanup_calls: list[str] = []

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> list[Any]:
                await manager.define_agent(_build_spec())
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()
                cancel_event = asyncio.Event()

                async def fake_astream(
                        *,
                        context: Any = None,
                        message: str,
                        config: dict[str, Any],
                        hitl_handler: Any = None,
                ) -> AsyncIterator[Any]:
                    del context, message, hitl_handler
                    configurable = config["configurable"]
                    try:
                        yield runtime_events.run_start(
                            run_id=str(configurable["run_id"]),
                            agent_name="demo-agent",
                            thread_id=str(configurable["thread_id"]),
                        )
                        await asyncio.Event().wait()
                    finally:
                        cleanup_calls.append("canceled")

                with patch.object(agent, "astream", fake_astream):
                    emitted: list[Any] = []
                    async for event in manager.invoke(
                        "demo-agent",
                        RunConfig(
                            input="hello",
                            thread_id="thread-1",
                            run_id="run-1",
                        ),
                        cancel_event=cancel_event,
                        cancel_reason="user requested cancel",
                    ):
                        emitted.append(event)
                        if event.type == RuntimeEventType.RUN_START:
                            cancel_event.set()
                    return emitted

            emitted = asyncio.run(scenario())

        assert [event.type for event in emitted] == [
            RuntimeEventType.RUN_START,
            RuntimeEventType.RUN_CANCELED,
        ]
        assert emitted[-1].data == {"reason": "user requested cancel"}
        assert cleanup_calls == ["canceled"]
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_invoke_emits_timeout_error_and_cleans_up_runtime_task() -> None:
    """Run timeout should end with an error event and cancel the producer task."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    cleanup_calls: list[str] = []

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> list[Any]:
                await manager.define_agent(_build_spec())
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()

                async def fake_astream(
                        *,
                        context: Any = None,
                        message: str,
                        config: dict[str, Any],
                        hitl_handler: Any = None,
                ) -> AsyncIterator[Any]:
                    del context, message, hitl_handler
                    configurable = config["configurable"]
                    try:
                        yield runtime_events.run_start(
                            run_id=str(configurable["run_id"]),
                            agent_name="demo-agent",
                            thread_id=str(configurable["thread_id"]),
                        )
                        await asyncio.Event().wait()
                    finally:
                        cleanup_calls.append("timed_out")

                with patch.object(agent, "astream", fake_astream):
                    emitted: list[Any] = []
                    async for event in manager.invoke(
                        "demo-agent",
                        RunConfig(
                            input="hello",
                            thread_id="thread-1",
                            run_id="run-1",
                            timeout_seconds=0.01,
                        ),
                    ):
                        emitted.append(event)
                    return emitted

            emitted = asyncio.run(scenario())

        assert [event.type for event in emitted] == [
            RuntimeEventType.RUN_START,
            RuntimeEventType.ERROR,
        ]
        assert emitted[-1].data["error_type"] == "timeout"
        assert "timed out" in emitted[-1].data["message"]
        assert cleanup_calls == ["timed_out"]
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_invoke_normalizes_runtime_exceptions_into_error_events() -> None:
    """Execution failures should surface as terminal runtime error events."""

    base_dir = _make_base_dir()
    registry = FakeRegistry(base_dir)
    manager = AgentManager(registry=registry)
    cleanup_calls: list[str] = []

    try:
        with patch("deepagents_runtime.manager.manager.get_checkpointer", _fake_checkpointer):
            async def scenario() -> list[Any]:
                await manager.define_agent(_build_spec())
                agent = await manager.agent_pool.get("demo-agent")  # type: ignore[union-attr]
                agent._graph = object()

                async def fake_astream(
                        *,
                        context: Any = None,
                        message: str,
                        config: dict[str, Any],
                        hitl_handler: Any = None,
                ) -> AsyncIterator[Any]:
                    del context, message, hitl_handler
                    configurable = config["configurable"]
                    try:
                        yield runtime_events.run_start(
                            run_id=str(configurable["run_id"]),
                            agent_name="demo-agent",
                            thread_id=str(configurable["thread_id"]),
                        )
                        raise RuntimeError("graph exploded")
                    finally:
                        cleanup_calls.append("errored")

                with patch.object(agent, "astream", fake_astream):
                    emitted: list[Any] = []
                    async for event in manager.invoke(
                        "demo-agent",
                        RunConfig(
                            input="hello",
                            thread_id="thread-1",
                            run_id="run-1",
                        ),
                    ):
                        emitted.append(event)
                    return emitted

            emitted = asyncio.run(scenario())

        assert [event.type for event in emitted] == [
            RuntimeEventType.RUN_START,
            RuntimeEventType.ERROR,
        ]
        assert emitted[-1].data == {
            "message": "graph exploded",
            "error_type": "runtime_error",
        }
        assert cleanup_calls == ["errored"]
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
