"""Unit tests for runtime session metadata and history queries."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import Any
from unittest.mock import patch

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from deepagents_runtime import sessions as runtime_sessions
from deepagents_runtime.sessions import (
    delete_thread,
    get_most_recent,
    get_session,
    get_session_messages,
    get_thread_agent,
    list_threads,
    thread_exists,
)


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


def _checkpoint_payload(messages: list[dict[str, object]], checkpoint_id: str) -> tuple[str, bytes]:
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
    return serde.dumps_typed(checkpoint_data)


async def _insert_checkpoint(
    conn: aiosqlite.Connection,
    *,
    thread_id: str,
    checkpoint_id: str,
    metadata: dict[str, str],
    messages: list[dict[str, object]],
) -> None:
    type_str, checkpoint_blob = _checkpoint_payload(messages, checkpoint_id)
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


async def _insert_write(
    conn: aiosqlite.Connection,
    *,
    thread_id: str,
    value: str,
) -> None:
    await conn.execute(
        "INSERT INTO writes(thread_id, value) VALUES (?, ?)",
        (thread_id, value),
    )
    await conn.commit()


def _patched_connect(conn: aiosqlite.Connection):
    @asynccontextmanager
    async def _connect(_: Any = None):
        yield conn

    return _connect


def test_list_threads_reads_checkpoint_metadata_and_message_count() -> None:
    """Thread listing should use latest checkpoint metadata and message state."""

    async def scenario() -> tuple[
        list[dict[str, object]],
        str | None,
        str | None,
        str | None,
    ]:
        conn = await _open_memory_conn()
        try:
            await _insert_checkpoint(
                conn,
                thread_id="thread-a",
                checkpoint_id="cp-001",
                metadata={
                    "agent_name": "alpha",
                    "updated_at": "2026-03-24T10:00:00+00:00",
                },
                messages=[
                    {"type": "human", "content": "start"},
                    {"type": "ai", "content": "first reply"},
                ],
            )
            await _insert_checkpoint(
                conn,
                thread_id="thread-a",
                checkpoint_id="cp-002",
                metadata={
                    "agent_name": "alpha",
                    "updated_at": "2026-03-24T10:05:00+00:00",
                },
                messages=[
                    {"type": "human", "content": "start"},
                    {"type": "ai", "content": "first reply"},
                    {"type": "human", "content": "followup"},
                    {"type": "ai", "content": "second reply"},
                ],
            )
            await _insert_checkpoint(
                conn,
                thread_id="thread-b",
                checkpoint_id="cp-003",
                metadata={
                    "assistant_id": "beta",
                    "updated_at": "2026-03-24T10:03:00+00:00",
                },
                messages=[
                    {"type": "human", "content": "beta ask"},
                    {"type": "ai", "content": "beta answer"},
                ],
            )

            with patch.object(runtime_sessions, "_connect", _patched_connect(conn)):
                threads = await list_threads(
                    limit=10,
                    include_message_count=True,
                )
                alpha_recent = await get_most_recent(agent_name="alpha")
                beta_recent = await get_most_recent(agent_name="beta")
                beta_agent = await get_thread_agent("thread-b")
            return threads, alpha_recent, beta_recent, beta_agent
        finally:
            await conn.close()

    threads, alpha_recent, beta_recent, beta_agent = asyncio.run(scenario())

    assert [thread["thread_id"] for thread in threads] == ["thread-a", "thread-b"]
    assert threads[0]["agent_name"] == "alpha"
    assert threads[0]["updated_at"] == "2026-03-24T10:05:00+00:00"
    assert threads[0]["latest_checkpoint_id"] == "cp-002"
    assert threads[0]["message_count"] == 4
    assert threads[1]["agent_name"] == "beta"
    assert threads[1]["message_count"] == 2
    assert alpha_recent == "thread-a"
    assert beta_recent == "thread-b"
    assert beta_agent == "beta"


def test_get_session_and_messages_use_latest_checkpoint_view() -> None:
    """Session detail and message history should be derived from latest checkpoint state."""

    async def scenario() -> tuple[object, object, object]:
        conn = await _open_memory_conn()
        try:
            await _insert_checkpoint(
                conn,
                thread_id="thread-a",
                checkpoint_id="cp-001",
                metadata={
                    "agent_name": "alpha",
                    "updated_at": "2026-03-24T10:00:00+00:00",
                },
                messages=[
                    {"type": "human", "content": "start"},
                    {"type": "ai", "content": "first reply"},
                ],
            )
            await _insert_checkpoint(
                conn,
                thread_id="thread-a",
                checkpoint_id="cp-002",
                metadata={
                    "agent_name": "alpha",
                    "updated_at": "2026-03-24T10:05:00+00:00",
                },
                messages=[
                    {"type": "human", "content": "start"},
                    {"type": "ai", "content": "first reply"},
                    {"type": "human", "content": "followup"},
                    {"type": "ai", "content": "second reply"},
                ],
            )

            with patch.object(runtime_sessions, "_connect", _patched_connect(conn)):
                detail = await get_session("thread-a")
                first_page = await get_session_messages(
                    "thread-a",
                    page_size=2,
                    include_raw=True,
                )
                second_page = await get_session_messages(
                    "thread-a",
                    page_token=first_page.next_page_token if first_page else "",
                    page_size=2,
                    include_raw=True,
                )
            return detail, first_page, second_page
        finally:
            await conn.close()

    detail, first_page, second_page = asyncio.run(scenario())

    assert detail is not None
    assert detail.summary.thread_id == "thread-a"
    assert detail.summary.latest_checkpoint_id == "cp-002"
    assert detail.summary.message_count == 4
    assert detail.summary.initial_prompt == "start"
    assert detail.checkpoint_count == 2

    assert first_page is not None
    assert first_page.resolved_checkpoint_id == "cp-002"
    assert first_page.actual_mode == "resume_view"
    assert first_page.total_message_count == 4
    assert [message.role for message in first_page.messages] == ["human", "ai"]
    assert [message.text for message in first_page.messages] == [
        "start",
        "first reply",
    ]
    assert first_page.messages[0].raw is not None
    assert first_page.next_page_token

    assert second_page is not None
    assert second_page.resolved_checkpoint_id == "cp-002"
    assert [message.role for message in second_page.messages] == ["human", "ai"]
    assert [message.text for message in second_page.messages] == [
        "followup",
        "second reply",
    ]
    assert second_page.next_page_token == ""


def test_delete_thread_removes_checkpoint_and_write_rows() -> None:
    """Deleting a thread should clean both checkpoints and writes."""

    async def scenario() -> tuple[bool, bool, bool, bool, int, int]:
        conn = await _open_memory_conn()
        try:
            await _insert_checkpoint(
                conn,
                thread_id="thread-a",
                checkpoint_id="cp-001",
                metadata={
                    "agent_name": "alpha",
                    "updated_at": "2026-03-24T10:00:00+00:00",
                },
                messages=[{"type": "human", "content": "a"}],
            )
            await _insert_checkpoint(
                conn,
                thread_id="thread-b",
                checkpoint_id="cp-002",
                metadata={
                    "agent_name": "beta",
                    "updated_at": "2026-03-24T10:01:00+00:00",
                },
                messages=[{"type": "human", "content": "b"}],
            )
            await _insert_write(conn, thread_id="thread-a", value="a")
            await _insert_write(conn, thread_id="thread-b", value="b")

            with patch.object(runtime_sessions, "_connect", _patched_connect(conn)):
                deleted = await delete_thread("thread-a")
                missing = await delete_thread("missing")
                exists_a = await thread_exists("thread-a")
                exists_b = await thread_exists("thread-b")

            async with conn.execute(
                "SELECT COUNT(*) FROM writes WHERE thread_id = ?",
                ("thread-a",),
            ) as cursor_a:
                thread_a_writes_row = await cursor_a.fetchone()
            async with conn.execute(
                "SELECT COUNT(*) FROM writes WHERE thread_id = ?",
                ("thread-b",),
            ) as cursor_b:
                thread_b_writes_row = await cursor_b.fetchone()

            return (
                deleted,
                missing,
                exists_a,
                exists_b,
                int(thread_a_writes_row[0]),
                int(thread_b_writes_row[0]),
            )
        finally:
            await conn.close()

    deleted, missing, exists_a, exists_b, thread_a_writes, thread_b_writes = (
        asyncio.run(scenario())
    )

    assert deleted is True
    assert missing is False
    assert exists_a is False
    assert exists_b is True
    assert thread_a_writes == 0
    assert thread_b_writes == 1
