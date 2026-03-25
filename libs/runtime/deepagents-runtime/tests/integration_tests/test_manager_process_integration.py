"""Process-local integration tests for the runtime manager stack."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import aiosqlite
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from grpc import aio as grpc_aio

from deepagents_runtime import sessions as runtime_sessions
from deepagents_runtime.entry.server import AgentExecutorServicer, ResourceSyncServicer
from deepagents_runtime.generated import runtime_pb2 as pb2
from deepagents_runtime.generated import runtime_pb2_grpc
from deepagents_runtime.manager.manager import AgentManager
from deepagents_runtime.registry import Registry
from deepagents_runtime.spec import AgentSpec, AgentStatus, RunConfig, RuntimeEventType


class FakeGraph:
    """Minimal compiled graph stub for process-local integration tests."""

    def __init__(self, *, response_text: str) -> None:
        self.response_text = response_text
        self.contexts: list[Any] = []
        self.inputs: list[Any] = []
        self.configs: list[dict[str, Any]] = []
        self.stream_modes: list[list[str]] = []
        self.versions: list[str] = []

    async def astream(
        self,
        stream_input: Any,
        *,
        config: dict[str, Any],
        context: Any = None,
        stream_mode: list[str],
        subgraphs: bool,
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        del subgraphs
        self.inputs.append(stream_input)
        self.configs.append(config)
        self.contexts.append(context)
        self.stream_modes.append(list(stream_mode))
        self.versions.append(version)
        yield {
            "type": "messages",
            "ns": (),
            "data": (
                AIMessageChunk(content=self.response_text),
                {"langgraph_node": "model"},
            ),
        }


class FakeMCPSessionManager:
    """Tracks cleanup for a releasable MCP runtime."""

    def __init__(self) -> None:
        self.cleanup_calls = 0

    async def cleanup(self) -> None:
        self.cleanup_calls += 1


class CheckpointAwareGraph:
    """Fake graph that persists turn history through the provided checkpointer."""

    def __init__(self, *, checkpointer: Any) -> None:
        self.checkpointer = checkpointer
        self.calls: list[tuple[str, str]] = []

    async def astream(
        self,
        stream_input: Any,
        *,
        config: dict[str, Any],
        context: Any = None,
        stream_mode: list[str],
        subgraphs: bool,
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        del context, stream_mode, subgraphs, version

        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        user_text = str(stream_input["messages"][0]["content"])
        self.calls.append((thread_id, user_text))

        load_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        prior = await self.checkpointer.aget_tuple(load_config)
        prior_messages: list[dict[str, str]] = []
        parent_checkpoint_id = ""
        if prior is not None:
            parent_checkpoint_id = str(prior.config["configurable"]["checkpoint_id"])
            prior_messages = list(
                prior.checkpoint.get("channel_values", {}).get("messages", [])
            )

        turn_index = (len(prior_messages) // 2) + 1
        if turn_index == 1:
            reply_text = f"turn 1: {user_text}"
        else:
            reply_text = f"turn {turn_index} after {len(prior_messages)} msgs: {user_text}"

        updated_messages = [
            *prior_messages,
            {"type": "human", "content": user_text},
            {"type": "ai", "content": reply_text},
        ]
        checkpoint = empty_checkpoint()
        checkpoint["id"] = f"cp-{turn_index:03d}"
        checkpoint["channel_values"] = {"messages": updated_messages}
        checkpoint["channel_versions"] = {}
        checkpoint["versions_seen"] = {}

        save_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            },
            "metadata": dict(config.get("metadata", {})),
        }
        if parent_checkpoint_id:
            save_config["configurable"]["checkpoint_id"] = parent_checkpoint_id

        await self.checkpointer.aput(
            save_config,
            checkpoint,
            {},
            {},
        )

        yield {
            "type": "messages",
            "ns": (),
            "data": (
                AIMessageChunk(content=reply_text),
                {"langgraph_node": "model"},
            ),
        }


def _make_base_dir() -> Path:
    """Create an isolated on-disk registry root for integration tests."""
    base_dir = (
        Path.cwd()
        / ".codex_tmp"
        / "manager-process-integration"
        / uuid.uuid4().hex
    )
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _cleanup_base_dir(base_dir: Path) -> None:
    """Remove the test registry root and collapse empty parent scratch dirs."""
    shutil.rmtree(base_dir, ignore_errors=True)

    current = base_dir.parent
    while current.name in {"manager-process-integration", ".codex_tmp"}:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _build_spec(name: str = "demo-agent") -> AgentSpec:
    """Build a realistic agent spec for process-local integration tests."""
    return AgentSpec(
        name=name,
        description="process-local integration test agent",
        model="openai:gpt-5.2",
        prompt={"system": "You are a test agent."},
        skills=[
            {
                "name": "demo-skill",
                "content": "# Demo Skill\n\nUse the helper script when needed.\n",
                "files": [
                    {
                        "path": "scripts/init_skill.py",
                        "content": "print('skill initialized')\n",
                    }
                ],
            }
        ],
    )


@asynccontextmanager
async def _fake_checkpointer() -> AsyncIterator[object]:
    """Return a lightweight async checkpointer context manager."""
    yield object()


def _shared_checkpointer_factory(
    checkpointer: Any,
) -> Callable[[], AsyncIterator[Any]]:
    """Build a no-op async context manager that reuses one checkpointer."""

    @asynccontextmanager
    async def _checkpointer() -> AsyncIterator[Any]:
        yield checkpointer

    return _checkpointer


def _patched_session_connect(conn: aiosqlite.Connection) -> Callable[..., AsyncIterator[Any]]:
    """Route session queries to a shared in-memory SQLite connection."""

    @asynccontextmanager
    async def _connect(_: Any = None) -> AsyncIterator[Any]:
        yield conn

    return _connect


def _build_sync_agent_spec_request(name: str = "grpc-agent") -> pb2.SyncAgentSpecRequest:
    """Build a protobuf SyncAgentSpec request for gRPC integration tests."""
    return pb2.SyncAgentSpecRequest(
        name=name,
        version="1.0.0",
        description="process-local gRPC integration test agent",
        tags=["grpc"],
        model="openai:gpt-5.2",
        prompt=pb2.PromptSpec(system="You are a gRPC test agent."),
        skills=[
            pb2.SkillContent(
                name="demo-skill",
                content="# Demo Skill\n\nUse the helper script when needed.\n",
                files=[
                    pb2.SkillFile(
                        path="scripts/init_skill.py",
                        content="print('skill initialized')\n",
                    )
                ],
            )
        ],
    )


@asynccontextmanager
async def _grpc_runtime_server(
    manager: AgentManager,
) -> AsyncIterator[tuple[Any, Any]]:
    """Start an in-process gRPC runtime server and return typed stubs."""
    await manager.setup()

    server = grpc_aio.server()
    runtime_pb2_grpc.add_AgentExecutorServicer_to_server(
        AgentExecutorServicer(manager),
        server,
    )
    runtime_pb2_grpc.add_ResourceSyncServicer_to_server(
        ResourceSyncServicer(manager),
        server,
    )

    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    channel = grpc_aio.insecure_channel(f"127.0.0.1:{port}")
    await channel.channel_ready()
    try:
        yield (
            runtime_pb2_grpc.AgentExecutorStub(channel),
            runtime_pb2_grpc.ResourceSyncStub(channel),
        )
    finally:
        await channel.close()
        await server.stop(grace=0)
        await manager.shutdown()


@contextmanager
def _patch_runtime_dependencies(
    *,
    graph: FakeGraph | None = None,
    graph_factory: Callable[..., Any] | None = None,
    mcp_session_manager: Any | None = None,
    checkpointer_factory: Callable[[], AsyncIterator[Any]] = _fake_checkpointer,
) -> Iterator[None]:
    """Patch heavy runtime dependencies while keeping manager/runtime real."""

    if (graph is None) == (graph_factory is None):
        msg = "provide exactly one of graph or graph_factory"
        raise ValueError(msg)

    async def fake_load_mcp_tools(
        _configs: Any,
    ) -> tuple[list[Any], Any | None, list[Any]]:
        return [], mcp_session_manager, []

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "deepagents_runtime.manager.manager.get_checkpointer",
                checkpointer_factory,
            )
        )
        stack.enter_context(
            patch(
                "deepagents_runtime.agent.create_model",
                return_value=SimpleNamespace(
                    model=object(),
                    model_name="gpt-5.2",
                    provider="openai",
                    context_limit=128000,
                ),
            )
        )
        stack.enter_context(
            patch(
                "deepagents_runtime.agent.load_mcp_tools_from_configs",
                fake_load_mcp_tools,
            )
        )
        stack.enter_context(
            patch(
                "deepagents_runtime.agent.create_summarization_middleware",
                return_value=object(),
            )
        )
        stack.enter_context(
            patch(
                "deepagents_runtime.agent.SummarizationToolMiddleware",
                side_effect=lambda middleware: middleware,
            )
        )
        if graph_factory is not None:
            stack.enter_context(
                patch(
                    "deepagents_runtime.agent.create_deep_agent",
                    side_effect=graph_factory,
                )
            )
        else:
            stack.enter_context(
                patch(
                    "deepagents_runtime.agent.create_deep_agent",
                    return_value=graph,
                )
            )
        yield


def test_define_assemble_and_invoke_use_real_registry_and_runtime_chain() -> None:
    """Manager should drive a real define -> assemble -> invoke process locally."""

    base_dir = _make_base_dir()
    registry = Registry(base_dir=base_dir)
    manager = AgentManager(registry=registry)
    graph = FakeGraph(response_text="hello from compiled graph")

    try:
        with _patch_runtime_dependencies(graph=graph):
            async def scenario() -> tuple[list[Any], AgentSpec | None, AgentStatus]:
                spec = _build_spec()

                await manager.define_agent(spec)
                stored = await registry.get_agent_spec(spec.name)

                agent_dir = registry.agent_dir(spec.name)
                assert (agent_dir / "agent.yaml").exists()
                assert registry.memory_dir(spec.name).exists()
                assert registry.memory_dir(spec.name).is_file()
                assert registry.workspace_dir(spec.name).exists()
                assert (
                    registry.skills_dir(spec.name)
                    / "demo-skill"
                    / "SKILL.md"
                ).exists()
                assert (
                    registry.skills_dir(spec.name)
                    / "demo-skill"
                    / "scripts"
                    / "init_skill.py"
                ).exists()

                await manager.assemble_agent(spec.name)
                agent = await manager.agent_pool.get(spec.name)  # type: ignore[union-attr]
                assert agent.status() == AgentStatus.COMPILED
                assert agent.has_runtime() is True

                listed = await manager.list_agents()
                assert [meta.status for meta in listed] == [AgentStatus.COMPILED]

                emitted: list[Any] = []
                async for event in manager.invoke(
                    spec.name,
                    RunConfig(
                        input="hello manager",
                        thread_id="thread-1",
                        run_id="run-1",
                    ),
                ):
                    emitted.append(event)

                status_after_run = agent.status()
                await manager.shutdown()
                return emitted, stored, status_after_run

            emitted, stored, status_after_run = asyncio.run(scenario())

        assert stored is not None
        assert stored.prompt == {"system": "You are a test agent."}
        assert stored.skills[0]["name"] == "demo-skill"
        assert stored.skills[0]["files"][0]["path"] == "scripts/init_skill.py"

        assert [event.type for event in emitted] == [
            RuntimeEventType.RUN_START,
            RuntimeEventType.TEXT_DELTA,
            RuntimeEventType.TEXT_DONE,
            RuntimeEventType.RUN_END,
        ]
        assert all(event.run_id == "run-1" for event in emitted)
        assert all(event.agent_name == "demo-agent" for event in emitted)
        assert emitted[0].data == {"thread_id": "thread-1"}
        assert emitted[1].data == {"text": "hello from compiled graph"}
        assert emitted[2].data == {"text": "hello from compiled graph"}
        assert status_after_run == AgentStatus.COMPILED

        assert graph.inputs == [{"messages": [{"role": "user", "content": "hello manager"}]}]
        assert graph.contexts == [None]
        assert graph.stream_modes == [["messages", "updates"]]
        assert graph.versions == ["v2"]
        assert graph.configs[0]["configurable"] == {
            "thread_id": "thread-1",
            "run_id": "run-1",
        }
        assert graph.configs[0]["metadata"]["agent_name"] == "demo-agent"
    finally:
        _cleanup_base_dir(base_dir)


def test_shutdown_releases_compiled_runtime_resources_in_process() -> None:
    """Manager shutdown should release compiled runtime resources locally."""

    base_dir = _make_base_dir()
    registry = Registry(base_dir=base_dir)
    manager = AgentManager(registry=registry)
    graph = FakeGraph(response_text="ignored")
    mcp_session_manager = FakeMCPSessionManager()

    try:
        with _patch_runtime_dependencies(
            graph=graph,
            mcp_session_manager=mcp_session_manager,
        ):
            async def scenario() -> tuple[AgentStatus, bool, bool]:
                spec = _build_spec(name="cleanup-agent")
                await manager.define_agent(spec)
                await manager.assemble_agent(spec.name)
                agent = await manager.agent_pool.get(spec.name)  # type: ignore[union-attr]

                assert agent.has_runtime() is True
                assert agent.status() == AgentStatus.COMPILED

                await manager.shutdown()
                return agent.status(), agent.has_runtime(), manager._checkpointer is None

            status_after_shutdown, has_runtime_after_shutdown, checkpointer_closed = (
                asyncio.run(scenario())
            )

        assert mcp_session_manager.cleanup_calls == 1
        assert status_after_shutdown == AgentStatus.INSTALLED
        assert has_runtime_after_shutdown is False
        assert checkpointer_closed is True
    finally:
        _cleanup_base_dir(base_dir)


def test_checkpoint_resume_and_session_continuity_survive_manager_restart() -> None:
    """A persisted thread should resume after shutdown and re-assembly."""

    base_dir = _make_base_dir()
    registry = Registry(base_dir=base_dir)
    manager_one = AgentManager(registry=registry)
    manager_two = AgentManager(registry=Registry(base_dir=base_dir))

    def build_graph(*, checkpointer: Any = None, **_kwargs: Any) -> CheckpointAwareGraph:
        assert checkpointer is not None
        return CheckpointAwareGraph(checkpointer=checkpointer)

    try:
        async def scenario() -> tuple[list[Any], list[Any], Any, Any]:
            runtime_sessions._patch_aiosqlite()
            conn = await aiosqlite.connect(":memory:")
            checkpointer = AsyncSqliteSaver(conn)
            try:
                spec = _build_spec(name="resume-agent")
                with patch.object(
                    runtime_sessions,
                    "_connect",
                    _patched_session_connect(conn),
                ):
                    with _patch_runtime_dependencies(
                        graph_factory=build_graph,
                        checkpointer_factory=_shared_checkpointer_factory(checkpointer),
                    ):
                        await manager_one.define_agent(spec)
                        await manager_one.assemble_agent(spec.name)

                        first_events: list[Any] = []
                        async for event in manager_one.invoke(
                            spec.name,
                            RunConfig(
                                input="hello",
                                thread_id="thread-resume-1",
                                run_id="run-1",
                            ),
                        ):
                            first_events.append(event)

                        await manager_one.shutdown()

                        await manager_two.assemble_agent(spec.name)
                        second_events: list[Any] = []
                        async for event in manager_two.invoke(
                            spec.name,
                            RunConfig(
                                input="followup",
                                thread_id="thread-resume-1",
                                run_id="run-2",
                            ),
                        ):
                            second_events.append(event)

                        await manager_two.shutdown()
                        session_detail = await runtime_sessions.get_session(
                            "thread-resume-1",
                        )
                        session_messages = await runtime_sessions.get_session_messages(
                            "thread-resume-1",
                        )
                        return (
                            first_events,
                            second_events,
                            session_detail,
                            session_messages,
                        )
            finally:
                await conn.close()

        first_events, second_events, session_detail, session_messages = asyncio.run(
            scenario()
        )

        assert [event.type for event in first_events] == [
            RuntimeEventType.RUN_START,
            RuntimeEventType.TEXT_DELTA,
            RuntimeEventType.TEXT_DONE,
            RuntimeEventType.RUN_END,
        ]
        assert [event.type for event in second_events] == [
            RuntimeEventType.RUN_START,
            RuntimeEventType.TEXT_DELTA,
            RuntimeEventType.TEXT_DONE,
            RuntimeEventType.RUN_END,
        ]
        assert first_events[2].data == {"text": "turn 1: hello"}
        assert second_events[2].data == {"text": "turn 2 after 2 msgs: followup"}

        assert session_detail is not None
        assert session_detail.summary.thread_id == "thread-resume-1"
        assert session_detail.summary.agent_name == "resume-agent"
        assert session_detail.summary.initial_prompt == "hello"
        assert session_detail.summary.message_count == 4
        assert session_detail.summary.latest_checkpoint_id == "cp-002"
        assert session_detail.checkpoint_count == 2

        assert session_messages is not None
        assert session_messages.thread_id == "thread-resume-1"
        assert session_messages.resolved_checkpoint_id == "cp-002"
        assert session_messages.actual_mode == "resume_view"
        assert session_messages.total_message_count == 4
        assert [(message.role, message.text) for message in session_messages.messages] == [
            ("human", "hello"),
            ("ai", "turn 1: hello"),
            ("human", "followup"),
            ("ai", "turn 2 after 2 msgs: followup"),
        ]
    finally:
        _cleanup_base_dir(base_dir)


def test_grpc_resource_sync_and_run_main_path_work_in_process() -> None:
    """ResourceSync and AgentExecutor.Run should work over a real in-process gRPC server."""

    base_dir = _make_base_dir()
    registry = Registry(base_dir=base_dir)
    manager = AgentManager(registry=registry)
    graph = FakeGraph(response_text="hello from grpc graph")

    try:
        with _patch_runtime_dependencies(graph=graph):
            async def scenario() -> tuple[Any, Any, Any, list[Any], bool]:
                async with _grpc_runtime_server(manager) as (executor_stub, resource_stub):
                    sync_response = await resource_stub.SyncAgentSpec(
                        _build_sync_agent_spec_request(name="grpc-agent")
                    )
                    stored = await registry.get_agent_spec("grpc-agent")
                    installed_before_remove = stored is not None
                    agent_dir_exists_before_remove = (
                        registry.agent_dir("grpc-agent") / "agent.yaml"
                    ).exists()

                    assemble_response = await resource_stub.Assemble(
                        pb2.AssembleRequest(agent_name="grpc-agent")
                    )
                    health_compiled = await resource_stub.Health(pb2.HealthRequest())

                    call = executor_stub.Run()
                    await call.write(
                        pb2.ClientMessage(
                            run_request=pb2.RunRequest(
                                agent_name="grpc-agent",
                                message="hello grpc",
                                thread_id="thread-grpc-1",
                            )
                        )
                    )
                    await call.done_writing()
                    events = [event async for event in call]
                    return (
                        sync_response,
                        assemble_response,
                        health_compiled,
                        events,
                        installed_before_remove and agent_dir_exists_before_remove,
                    )

            (
                sync_response,
                assemble_response,
                health_compiled,
                events,
                lifecycle_files_verified,
            ) = asyncio.run(scenario())

        assert sync_response.ok is True
        assert "installed" in sync_response.message
        assert assemble_response.ok is True
        assert assemble_response.status == "compiled"

        assert health_compiled.status == "ok"
        assert health_compiled.ready is True
        assert health_compiled.installed_agent_count == 1
        assert health_compiled.assembled_agent_count == 1
        assert health_compiled.running_agent_count == 0

        assert [event.WhichOneof("payload") for event in events] == [
            "run_started",
            "text_delta",
            "text_done",
            "run_ended",
        ]
        assert all(event.agent_name == "grpc-agent" for event in events)
        assert len({event.run_id for event in events}) == 1
        assert events[0].run_started.thread_id == "thread-grpc-1"
        assert events[1].text_delta.text == "hello from grpc graph"
        assert events[2].text_done.text == "hello from grpc graph"
        assert lifecycle_files_verified is True
    finally:
        _cleanup_base_dir(base_dir)
