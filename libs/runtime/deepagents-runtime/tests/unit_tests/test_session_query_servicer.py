"""Unit tests for the SessionQuery gRPC servicer."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import Any
from unittest.mock import patch

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from deepagents_runtime import sessions as runtime_sessions
from deepagents_runtime.entry.server import SessionQueryServicer
from deepagents_runtime.generated import runtime_pb2 as pb2
from deepagents_runtime.spec import AgentMeta, AgentStatus


async def _open_memory_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute(
        """
        CREATE TABLE checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint BLOB,
            metadata TEXT,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE writes (
            thread_id TEXT NOT NULL,
            value TEXT
        )
        """
    )
    await conn.commit()
    return conn


async def _insert_checkpoint(
    conn: aiosqlite.Connection,
    *,
    thread_id: str,
    checkpoint_id: str,
    metadata: dict[str, str],
    messages: list[dict[str, object]],
) -> None:
    serde = JsonPlusSerializer()
    checkpoint_data = {
        "v": 1,
        "ts": "2026-03-24T10:00:00+00:00",
        "id": checkpoint_id,
        "channel_values": {"messages": messages},
        "channel_versions": {},
        "versions_seen": {},
        "updated_channels": [],
    }
    type_str, checkpoint_blob = serde.dumps_typed(checkpoint_data)

    await conn.execute(
        """
        INSERT INTO checkpoints(
            thread_id,
            checkpoint_ns,
            checkpoint_id,
            type,
            checkpoint,
            metadata
        )
        VALUES (?, '', ?, ?, ?, ?)
        """,
        (
            thread_id,
            checkpoint_id,
            type_str,
            checkpoint_blob,
            json.dumps(metadata),
        ),
    )
    await conn.commit()


def _patched_connect(conn: aiosqlite.Connection):
    @asynccontextmanager
    async def _connect(_: Any = None):
        yield conn

    return _connect


class _FakeManager:
    """Minimal manager stub for session status overlay tests."""

    def __init__(self, agents: list[AgentMeta]) -> None:
        self._agents = agents
        self.registry = _FakeRegistry()

    async def list_agents(self) -> list[AgentMeta]:
        return self._agents


class _FakeRegistry:
    """Minimal registry stub for thread cleanup hooks."""

    def __init__(self) -> None:
        self.deleted_threads: list[tuple[str, str]] = []

    def delete_thread_dir(self, agent_name: str, thread_id: str) -> None:
        self.deleted_threads.append((agent_name, thread_id))


def test_list_sessions_and_get_messages_return_proto_payloads() -> None:
    """SessionQuery should expose summary and message history over protobuf."""

    async def scenario() -> tuple[
        pb2.ListSessionsResponse,
        pb2.GetSessionResponse,
        pb2.GetSessionMessagesResponse,
        pb2.GetSessionMessagesResponse,
    ]:
        conn = await _open_memory_conn()
        try:
            await _insert_checkpoint(
                conn,
                thread_id="thread-a",
                checkpoint_id="cp-001",
                metadata={
                    "agent_name": "alpha",
                    "updated_at": "2026-03-24T10:05:00+00:00",
                },
                messages=[
                    {"type": "human", "content": "hello"},
                    {"type": "ai", "content": "world"},
                ],
            )
            servicer = SessionQueryServicer(
                _FakeManager(
                    [
                        AgentMeta(
                            "alpha",
                            "1.0.0",
                            "",
                            [],
                            AgentStatus.COMPILED,
                        )
                    ]
                )
            )
            with patch.object(runtime_sessions, "_connect", _patched_connect(conn)):
                list_response = await servicer.ListSessions(
                    pb2.ListSessionsRequest(page_size=10),
                    None,
                )
                session_response = await servicer.GetSession(
                    pb2.GetSessionRequest(
                        thread_id="thread-a",
                        agent_name="alpha",
                    ),
                    None,
                )
                messages_response = await servicer.GetSessionMessages(
                    pb2.GetSessionMessagesRequest(
                        thread_id="thread-a",
                        agent_name="alpha",
                        page_size=1,
                        include_raw=True,
                    ),
                    None,
                )
                next_messages_response = await servicer.GetSessionMessages(
                    pb2.GetSessionMessagesRequest(
                        thread_id="thread-a",
                        agent_name="alpha",
                        page_size=1,
                        page_token=messages_response.next_page_token,
                    ),
                    None,
                )
            return (
                list_response,
                session_response,
                messages_response,
                next_messages_response,
            )
        finally:
            await conn.close()

    list_response, session_response, messages_response, next_messages_response = asyncio.run(
        scenario()
    )

    assert len(list_response.sessions) == 1
    assert list_response.sessions[0].thread_id == "thread-a"
    assert list_response.sessions[0].agent_name == "alpha"
    assert list_response.sessions[0].message_count == 2
    assert list_response.sessions[0].agent_status == pb2.AGENT_RUNTIME_STATUS_COMPILED
    assert (
        list_response.sessions[0].history_mode
        == pb2.SESSION_HISTORY_MODE_RESUME_VIEW
    )
    assert session_response.found is True
    assert session_response.session.summary.agent_status == pb2.AGENT_RUNTIME_STATUS_COMPILED

    assert messages_response.thread_id == "thread-a"
    assert messages_response.resolved_checkpoint_id == "cp-001"
    assert messages_response.total_message_count == 2
    assert len(messages_response.messages) == 1
    assert messages_response.messages[0].role == pb2.SESSION_MESSAGE_ROLE_HUMAN
    assert messages_response.messages[0].text == "hello"
    assert messages_response.messages[0].raw.fields
    assert messages_response.next_page_token

    assert len(next_messages_response.messages) == 1
    assert next_messages_response.messages[0].role == pb2.SESSION_MESSAGE_ROLE_AI
    assert next_messages_response.messages[0].text == "world"
    assert next_messages_response.next_page_token == ""


def test_delete_session_and_get_latest_session_follow_runtime_state() -> None:
    """Deleting a session should affect subsequent latest-session queries."""

    async def scenario() -> tuple[
        pb2.GetLatestSessionResponse,
        pb2.DeleteSessionResponse,
        pb2.GetLatestSessionResponse,
    ]:
        conn = await _open_memory_conn()
        try:
            await _insert_checkpoint(
                conn,
                thread_id="thread-a",
                checkpoint_id="cp-001",
                metadata={
                    "agent_name": "alpha",
                    "updated_at": "2026-03-24T10:05:00+00:00",
                },
                messages=[{"type": "human", "content": "hello"}],
            )
            servicer = SessionQueryServicer(
                _FakeManager(
                    [
                        AgentMeta(
                            "alpha",
                            "1.0.0",
                            "",
                            [],
                            AgentStatus.RUNNING,
                        )
                    ]
                )
            )
            with patch.object(runtime_sessions, "_connect", _patched_connect(conn)):
                latest_before = await servicer.GetLatestSession(
                    pb2.GetLatestSessionRequest(agent_name="alpha"),
                    None,
                )
                delete_response = await servicer.DeleteSession(
                    pb2.DeleteSessionRequest(
                        thread_id="thread-a",
                        agent_name="alpha",
                    ),
                    None,
                )
                latest_after = await servicer.GetLatestSession(
                    pb2.GetLatestSessionRequest(agent_name="alpha"),
                    None,
                )
            return latest_before, delete_response, latest_after
        finally:
            await conn.close()

    latest_before, delete_response, latest_after = asyncio.run(scenario())

    assert latest_before.found is True
    assert latest_before.session.thread_id == "thread-a"
    assert latest_before.session.agent_status == pb2.AGENT_RUNTIME_STATUS_RUNNING
    assert delete_response.deleted is True
    assert latest_after.found is False
