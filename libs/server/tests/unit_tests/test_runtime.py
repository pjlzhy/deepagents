from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from deepagents_server.runtime import (
    ExecutionRequest,
    ExecutionService,
    RuntimeContext,
    RuntimeEvent,
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
                                        {"name": "fetch_url", "args": {"url": "https://example.com"}},
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
