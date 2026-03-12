from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

from langchain_core.messages import ToolMessage

from deepagents_runtime.inputs import InputEnvelope
from deepagents_runtime.run_service import (
    AgentRunConfig,
    BashRunConfig,
    CommandRunConfig,
    stream_run_events,
)
from deepagents_runtime.streams import validate_hitl_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pytest


def _make_hitl_request() -> object:
    return validate_hitl_request(
        {
            "action_requests": [
                {
                    "name": "execute",
                    "args": {"command": "echo hi"},
                    "description": "Run command",
                }
            ],
            "review_configs": [
                {
                    "action_name": "execute",
                    "allowed_decisions": ["approve", "reject"],
                }
            ],
        }
    )


class _FakeAgent:
    def __init__(self, passes: list[list[object]]) -> None:
        self._passes = passes
        self.inputs: list[object] = []

    async def astream(self, stream_input: object, **_: object) -> AsyncIterator[object]:
        self.inputs.append(stream_input)
        pass_index = len(self.inputs) - 1
        for chunk in self._passes[pass_index]:
            yield chunk


def test_stream_run_events_normal_emits_required_message_events() -> None:
    async def _run() -> None:
        agent = _FakeAgent(
            [
                [
                    (
                        (),
                        "messages",
                        (
                            SimpleNamespace(
                                content_blocks=[{"type": "text", "text": "hello"}],
                                chunk_position="last",
                            ),
                            {},
                        ),
                    )
                ]
            ]
        )
        envelope = InputEnvelope(thread_id="thread-1", mode="normal", text="hi")
        cfg = AgentRunConfig(model_name="fake-model")

        events = [
            event
            async for event in stream_run_events(
                envelope, agent=agent, agent_config=cfg
            )
        ]

        assert [event.type for event in events] == [
            "run.started",
            "message.user.created",
            "message.assistant.started",
            "message.assistant.delta",
            "message.assistant.completed",
            "run.completed",
        ]

    asyncio.run(_run())


def test_stream_run_events_normal_accepts_user_message_content_override() -> None:
    async def _run() -> None:
        agent = _FakeAgent(
            [
                [
                    (
                        (),
                        "messages",
                        (
                            SimpleNamespace(
                                content_blocks=[{"type": "text", "text": "hello"}],
                                chunk_position="last",
                            ),
                            {},
                        ),
                    )
                ]
            ]
        )
        envelope = InputEnvelope(thread_id="thread-1", mode="normal", text="hi")
        cfg = AgentRunConfig(model_name="fake-model")
        user_content = [
            {"type": "text", "text": "override"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,AAAA"},
            },
        ]

        _ = [
            event
            async for event in stream_run_events(
                envelope,
                agent=agent,
                agent_config=cfg,
                user_message_content=user_content,
            )
        ]

        assert agent.inputs
        assert isinstance(agent.inputs[0], dict)
        messages = agent.inputs[0].get("messages", [])
        assert isinstance(messages, list)
        assert messages[0]["content"] == user_content

    asyncio.run(_run())


def test_stream_run_events_normal_builds_multimodal_from_image_attachments() -> None:
    async def _run() -> None:
        agent = _FakeAgent(
            [
                [
                    (
                        (),
                        "messages",
                        (
                            SimpleNamespace(
                                content_blocks=[{"type": "text", "text": "hello"}],
                                chunk_position="last",
                            ),
                            {},
                        ),
                    )
                ]
            ]
        )
        envelope = InputEnvelope(
            thread_id="thread-1",
            mode="normal",
            text="hi",
            attachments=(
                {"kind": "image", "data_url": "data:image/png;base64,AAAA"},
            ),
        )
        cfg = AgentRunConfig(model_name="fake-model")

        _ = [
            event
            async for event in stream_run_events(
                envelope, agent=agent, agent_config=cfg
            )
        ]

        assert agent.inputs
        assert isinstance(agent.inputs[0], dict)
        messages = agent.inputs[0].get("messages", [])
        assert isinstance(messages, list)
        assert messages[0]["content"] == [
            {"type": "text", "text": "hi"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]

    asyncio.run(_run())


def test_stream_run_events_normal_appends_file_attachments_to_text() -> None:
    async def _run() -> None:
        agent = _FakeAgent(
            [
                [
                    (
                        (),
                        "messages",
                        (
                            SimpleNamespace(
                                content_blocks=[{"type": "text", "text": "hello"}],
                                chunk_position="last",
                            ),
                            {},
                        ),
                    )
                ]
            ]
        )
        envelope = InputEnvelope(
            thread_id="thread-1",
            mode="normal",
            text="hi",
            attachments=(
                {"kind": "file", "path": "/workspace/example.txt", "inject": True},
            ),
        )
        cfg = AgentRunConfig(model_name="fake-model")

        _ = [
            event
            async for event in stream_run_events(
                envelope, agent=agent, agent_config=cfg
            )
        ]

        assert agent.inputs
        assert isinstance(agent.inputs[0], dict)
        messages = agent.inputs[0].get("messages", [])
        assert isinstance(messages, list)
        assert messages[0]["content"] == (
            "hi\n\n## Attachments\n- /workspace/example.txt (inject=True)"
        )

    asyncio.run(_run())


def test_stream_run_events_normal_expands_tool_events() -> None:
    async def _run() -> None:
        agent = _FakeAgent(
            [
                [
                    (
                        (),
                        "messages",
                        (
                            SimpleNamespace(
                                content_blocks=[
                                    {
                                        "type": "tool_call",
                                        "name": "execute",
                                        "args": {"command": "echo hi"},
                                        "id": "call-1",
                                    }
                                ]
                            ),
                            {},
                        ),
                    ),
                    (
                        (),
                        "messages",
                        (
                            ToolMessage(
                                content="ok",
                                tool_call_id="call-1",
                                name="execute",
                            ),
                            {},
                        ),
                    ),
                ]
            ]
        )
        envelope = InputEnvelope(thread_id="thread-1", mode="normal", text="run tool")
        cfg = AgentRunConfig(model_name="fake-model")

        events = [
            event
            async for event in stream_run_events(
                envelope, agent=agent, agent_config=cfg
            )
        ]
        event_types = [event.type for event in events]

        assert "tool.started" in event_types
        assert "tool.output" in event_types
        assert "tool.completed" in event_types

    asyncio.run(_run())


def test_stream_run_events_emits_approval_events_and_cancels_on_reject() -> None:
    async def _run() -> None:
        agent = _FakeAgent(
            [
                [
                    (
                        (),
                        "updates",
                        {
                            "__interrupt__": [
                                SimpleNamespace(
                                    id="interrupt-1", value=_make_hitl_request()
                                )
                            ]
                        },
                    )
                ]
            ]
        )
        envelope = InputEnvelope(thread_id="thread-1", mode="normal", text="hi")

        def resolve_approvals(_pending: dict[str, object]) -> dict[str, object]:
            return {}

        cfg = AgentRunConfig(
            model_name="fake-model", resolve_approvals=resolve_approvals
        )

        events = [
            event
            async for event in stream_run_events(
                envelope, agent=agent, agent_config=cfg
            )
        ]

        assert "approval.requested" in [event.type for event in events]
        assert "approval.resolved" in [event.type for event in events]
        assert events[-1].type == "run.cancelled"
        assert not any(event.type == "run.completed" for event in events)

        requested = next(
            event for event in events if event.type == "approval.requested"
        )
        assert requested.payload["interrupt_ids"] == ["interrupt-1"]
        assert "interrupt-1" in requested.payload["interrupts"]
        interrupt_payload = requested.payload["interrupts"]["interrupt-1"]
        assert interrupt_payload["action_requests"][0]["name"] == "execute"

    asyncio.run(_run())


def test_stream_run_events_command_emits_command_result() -> None:
    async def _run() -> None:
        envelope = InputEnvelope(thread_id="thread-1", mode="command", text="/unknown")
        cfg = CommandRunConfig(docs_url="https://example.com/docs")

        events = [
            event async for event in stream_run_events(envelope, command_config=cfg)
        ]
        event_types = [event.type for event in events]

        assert event_types[0] == "run.started"
        assert "command.result" in event_types
        assert event_types[-1] == "run.completed"

    asyncio.run(_run())


def test_stream_run_events_bash_runs_command_and_emits_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        class _FakeProc:
            def __init__(self) -> None:
                self.returncode = 0
                self.pid = 1234

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"hello\n", b""

            async def wait(self) -> int:
                return self.returncode

            def terminate(self) -> None:
                return None

            def kill(self) -> None:
                return None

        async def _fake_create_subprocess_shell(*_: object, **__: object) -> _FakeProc:
            await asyncio.sleep(0)
            return _FakeProc()

        monkeypatch.setattr(
            asyncio, "create_subprocess_shell", _fake_create_subprocess_shell
        )

        envelope = InputEnvelope(thread_id="thread-1", mode="bash", text="echo hello")
        events = [
            event
            async for event in stream_run_events(
                envelope,
                bash_config=BashRunConfig(timeout_seconds=5.0),
            )
        ]

        assert [event.type for event in events][:3] == [
            "run.started",
            "message.user.created",
            "bash.started",
        ]
        assert any(event.type == "bash.output" for event in events)
        output = next(
            event.payload["output"] for event in events if event.type == "bash.output"
        )
        assert "hello" in output
        assert events[-1].type == "run.completed"

    asyncio.run(_run())
