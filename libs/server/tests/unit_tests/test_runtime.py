from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import pytest

from deepagents_server.runtime import (
    CliRuntimeAdapter,
    ExecutionRequest,
    ExecutionService,
    RuntimeContext,
    RuntimeEvent,
    RuntimeServiceError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True)
class FakeInterrupt:
    id: str
    value: dict[str, object]


@dataclass(frozen=True)
class FakeAIMessage:
    content_blocks: list[dict[str, object]]


@dataclass(frozen=True)
class FakeToolMessage:
    tool_call_id: str
    content: str
    name: str | None = None


class FakeAgent:
    def __init__(self, passes: list[list[object]]) -> None:
        self._passes = passes
        self.calls: list[object] = []

    async def astream(
        self,
        stream_input: object,
        *,
        stream_mode: list[str],
        subgraphs: bool,
        config: dict[str, object],
        durability: str,
    ) -> AsyncIterator[object]:
        del stream_mode, subgraphs, config, durability
        self.calls.append(stream_input)
        current_pass = self._passes[len(self.calls) - 1]
        for chunk in current_pass:
            yield chunk


class FakeRuntimeAdapter:
    def __init__(
        self,
        passes: list[list[object]],
        *,
        thread_id: str = "thread-123",
        model: str = "test-model",
        shell_allow_list: list[str] | None = None,
    ) -> None:
        self.agent = FakeAgent(passes)
        self.thread_id = thread_id
        self.model = model
        self.shell_allow_list = shell_allow_list
        self.resume_inputs: list[object] = []
        self.last_checkpointer: object | None = None

    @asynccontextmanager
    async def open_runtime(self, request: ExecutionRequest) -> AsyncIterator[RuntimeContext]:
        self.last_checkpointer = request.checkpointer
        yield RuntimeContext(
            agent=self.agent,
            config={"configurable": {"thread_id": request.thread_id or self.thread_id}},
            assistant_id=request.assistant_id,
            thread_id=request.thread_id or self.thread_id,
            model=request.model or self.model,
            shell_allow_list=self.shell_allow_list,
        )

    def build_initial_input(self, request: ExecutionRequest) -> object:
        return {"messages": [{"role": "user", "content": request.input}]}

    def build_resume_input(self, resume_payload: object) -> object:
        self.resume_inputs.append(resume_payload)
        return {"resume": resume_payload}

    def is_shell_command_allowed(
        self,
        command: str,
        allow_list: list[str] | None,
    ) -> bool:
        if not allow_list:
            return False
        executable = command.split(maxsplit=1)[0] if command else ""
        return executable in set(allow_list)


class _FakeCliModelResult:
    def __init__(self, model_name: str | None) -> None:
        self.model = object()
        self.model_name = model_name

    def apply_to_settings(self) -> None:
        return None


class _FakeCliSettings:
    has_tavily = False
    shell_allow_list: ClassVar[list[str]] = ["ls"]


class RecordingCliRuntimeAdapter(CliRuntimeAdapter):
    def __init__(self) -> None:
        self.last_agent_kwargs: dict[str, object] | None = None
        self.get_checkpointer_calls = 0
        self.create_sandbox_error: Exception | None = None

    def _load_dependencies(self) -> dict[str, object]:
        def create_model(
            model: str | None,
            *,
            extra_kwargs: dict[str, object] | None,
            profile_overrides: dict[str, object] | None,
        ) -> _FakeCliModelResult:
            assert extra_kwargs is None
            assert profile_overrides is None
            return _FakeCliModelResult(model)

        def create_cli_agent(**kwargs: object) -> tuple[FakeAgent, object]:
            self.last_agent_kwargs = kwargs
            return FakeAgent([]), object()

        @asynccontextmanager
        async def get_checkpointer() -> AsyncIterator[object]:
            self.get_checkpointer_calls += 1
            yield "local-checkpointer"

        def create_sandbox(
            sandbox_type: str,
            *,
            sandbox_id: str | None,
            setup_script_path: str | None,
        ) -> object:
            del sandbox_type, sandbox_id, setup_script_path
            if self.create_sandbox_error is not None:
                raise self.create_sandbox_error
            return _NullContext()

        return {
            "create_cli_agent": create_cli_agent,
            "create_model": create_model,
            "settings": _FakeCliSettings(),
            "generate_thread_id": lambda: "thread-generated",
            "get_checkpointer": get_checkpointer,
            "fetch_url": object(),
            "http_request": object(),
            "web_search": object(),
            "create_sandbox": create_sandbox,
        }


class _NullContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb


def test_run_collects_text_and_preserves_thread_id() -> None:
    adapter = FakeRuntimeAdapter(
        passes=[
            [
                (
                    (),
                    "messages",
                    (
                        FakeAIMessage(
                            content_blocks=[
                                {"type": "text", "text": "hello "},
                                {"type": "text", "text": "world"},
                            ]
                        ),
                        {},
                    ),
                )
            ]
        ],
        thread_id="thread-run-1",
    )
    service = ExecutionService(adapter=adapter)

    result = asyncio.run(
        service.run(
            ExecutionRequest(
                assistant_id="assistant-alpha",
                input="say hello",
                thread_id="thread-run-1",
                checkpointer=object(),
            )
        )
    )

    assert result.assistant_id == "assistant-alpha"
    assert result.thread_id == "thread-run-1"
    assert result.output == "hello world"
    assert adapter.last_checkpointer is not None


def test_stream_emits_tool_and_completion_events() -> None:
    adapter = FakeRuntimeAdapter(
        passes=[
            [
                (
                    (),
                    "messages",
                    (
                        FakeAIMessage(
                            content_blocks=[
                                {"type": "text", "text": "partial"},
                                {
                                    "type": "tool_call",
                                    "name": "fetch_url",
                                    "id": "tool-1",
                                    "index": 0,
                                },
                            ]
                        ),
                        {},
                    ),
                ),
                (
                    (),
                    "messages",
                    (FakeToolMessage(tool_call_id="tool-1", content="ok", name="fetch_url"), {}),
                ),
            ]
        ],
    )
    service = ExecutionService(adapter=adapter)

    async def _collect_events() -> list[RuntimeEvent]:
        return [
            event
            async for event in service.stream(
                ExecutionRequest(assistant_id="assistant-beta", input="fetch something")
            )
        ]

    events = asyncio.run(_collect_events())

    assert [event.type for event in events] == [
        "message.delta",
        "tool.call",
        "tool.result",
        "run.completed",
    ]
    assert events[-1].payload["output"] == "partial"


def test_interrupt_decisions_follow_shell_allow_list_semantics() -> None:
    adapter = FakeRuntimeAdapter(
        passes=[
            [
                (
                    (),
                    "updates",
                    {
                        "__interrupt__": [
                            FakeInterrupt(
                                id="interrupt-1",
                                value={
                                    "action_requests": [
                                        {"name": "execute", "args": {"command": "ls -la"}},
                                        {
                                            "name": "fetch_url",
                                            "args": {"url": "https://example.com"},
                                        },
                                    ]
                                },
                            )
                        ]
                    },
                )
            ],
            [
                (
                    (),
                    "messages",
                    (
                        FakeAIMessage(content_blocks=[{"type": "text", "text": "done"}]),
                        {},
                    ),
                )
            ],
        ],
        shell_allow_list=["ls"],
    )
    service = ExecutionService(adapter=adapter)

    result = asyncio.run(
        service.run(
            ExecutionRequest(assistant_id="assistant-gamma", input="list files then continue")
        )
    )

    assert result.output == "done"
    assert adapter.resume_inputs == [
        {
            "interrupt-1": {
                "decisions": [
                    {"type": "approve"},
                    {"type": "approve"},
                ]
            }
        }
    ]


def test_stream_emits_interrupt_required_before_completion() -> None:
    adapter = FakeRuntimeAdapter(
        passes=[
            [
                (
                    (),
                    "updates",
                    {
                        "__interrupt__": [
                            FakeInterrupt(
                                id="interrupt-1",
                                value={
                                    "action_requests": [
                                        {
                                            "name": "fetch_url",
                                            "args": {"url": "https://example.com"},
                                        }
                                    ]
                                },
                            )
                        ]
                    },
                )
            ],
            [
                (
                    (),
                    "messages",
                    (
                        FakeAIMessage(content_blocks=[{"type": "text", "text": "done"}]),
                        {},
                    ),
                )
            ],
        ],
    )
    service = ExecutionService(adapter=adapter)

    async def _collect_events() -> list[RuntimeEvent]:
        return [
            event
            async for event in service.stream(
                ExecutionRequest(assistant_id="assistant-interrupt", input="need interrupt")
            )
        ]

    events = asyncio.run(_collect_events())

    assert [event.type for event in events] == [
        "interrupt.required",
        "message.delta",
        "run.completed",
    ]
    assert events[0].payload["interrupt_id"] == "interrupt-1"
    assert events[-1].payload["output"] == "done"


def test_cli_runtime_adapter_uses_memory_checkpointer_backend() -> None:
    adapter = RecordingCliRuntimeAdapter()

    async def _open_runtime() -> None:
        async with adapter.open_runtime(
            ExecutionRequest(
                assistant_id="assistant-memory",
                input="hello",
                checkpointer_backend="memory",
            )
        ):
            pass

    asyncio.run(_open_runtime())

    assert adapter.get_checkpointer_calls == 0
    assert adapter.last_agent_kwargs is not None
    assert adapter.last_agent_kwargs["checkpointer"] is None


def test_cli_runtime_adapter_uses_local_checkpointer_backend() -> None:
    adapter = RecordingCliRuntimeAdapter()

    async def _open_runtime() -> None:
        async with adapter.open_runtime(
            ExecutionRequest(
                assistant_id="assistant-local",
                input="hello",
                checkpointer_backend="local",
            )
        ):
            pass

    asyncio.run(_open_runtime())

    assert adapter.get_checkpointer_calls == 1
    assert adapter.last_agent_kwargs is not None
    assert adapter.last_agent_kwargs["checkpointer"] == "local-checkpointer"


def test_cli_runtime_adapter_reports_unsupported_sandbox_clearly() -> None:
    adapter = RecordingCliRuntimeAdapter()
    adapter.create_sandbox_error = RuntimeError("provider missing")

    async def _open_runtime() -> None:
        async with adapter.open_runtime(
            ExecutionRequest(
                assistant_id="assistant-sandbox",
                input="hello",
                sandbox_type="modal",
            )
        ):
            pass

    with pytest.raises(RuntimeServiceError) as exc_info:
        asyncio.run(_open_runtime())

    assert "Sandbox type 'modal' is not supported" in str(exc_info.value)
