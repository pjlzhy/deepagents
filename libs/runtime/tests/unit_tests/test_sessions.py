import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from deepagents_runtime.sessions import (
    SessionStore,
    format_timestamp,
    generate_thread_id,
)


class TestGenerateThreadId:
    def test_length(self):
        assert len(generate_thread_id()) == 8

    def test_hex(self):
        int(generate_thread_id(), 16)


class TestFormatTimestamp:
    def test_valid_timestamp(self):
        result = format_timestamp("2024-12-30T21:18:00+00:00")

        assert result
        assert "dec" in result.lower()

    def test_invalid_timestamp(self):
        assert not format_timestamp("not-a-timestamp")


class TestSessionStore:
    @pytest.fixture
    def temp_db(self, tmp_path):
        db_path = tmp_path / "test_sessions.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB,
                metadata BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                value BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            )
        """)

        now = datetime.now(UTC).isoformat()
        earlier = "2024-01-01T10:00:00+00:00"

        threads = [
            ("thread1", "agent1", now),
            ("thread2", "agent2", earlier),
            ("thread3", "agent1", earlier),
        ]

        for thread_id, agent_name, updated_at in threads:
            metadata = json.dumps({"agent_name": agent_name, "updated_at": updated_at})
            conn.execute(
                "INSERT INTO checkpoints "
                "(thread_id, checkpoint_ns, checkpoint_id, metadata) "
                "VALUES (?, '', ?, ?)",
                (thread_id, f"cp_{thread_id}", metadata),
            )

        conn.commit()
        conn.close()

        return db_path

    def test_list_threads(self, temp_db):
        store = SessionStore(lambda: temp_db)

        threads = asyncio.run(store.list_threads())

        assert len(threads) == 3

    def test_list_threads_filter_by_agent(self, temp_db):
        store = SessionStore(lambda: temp_db)

        threads = asyncio.run(store.list_threads(agent_name="agent1"))

        assert len(threads) == 2
        assert all(thread["agent_name"] == "agent1" for thread in threads)

    def test_get_most_recent(self, temp_db):
        store = SessionStore(lambda: temp_db)

        thread_id = asyncio.run(store.get_most_recent())

        assert thread_id is not None

    def test_get_thread_agent(self, temp_db):
        store = SessionStore(lambda: temp_db)

        agent_name = asyncio.run(store.get_thread_agent("thread1"))

        assert agent_name == "agent1"

    def test_thread_exists(self, temp_db):
        store = SessionStore(lambda: temp_db)

        assert asyncio.run(store.thread_exists("thread2")) is True
        assert asyncio.run(store.thread_exists("missing")) is False

    def test_find_similar_threads(self, temp_db):
        store = SessionStore(lambda: temp_db)

        similar = asyncio.run(store.find_similar_threads("thread"))

        assert similar == ["thread1", "thread2", "thread3"]

    def test_delete_thread(self, temp_db):
        store = SessionStore(lambda: temp_db)

        deleted = asyncio.run(store.delete_thread("thread1"))

        assert deleted is True
        assert asyncio.run(store.thread_exists("thread1")) is False

    def test_cached_threads_round_trip(self, temp_db):
        store = SessionStore(lambda: temp_db)

        asyncio.run(store.list_threads(limit=2))
        cached = store.get_cached_threads(limit=2)

        assert cached is not None
        assert len(cached) == 2

    def test_get_checkpointer(self, temp_db):
        store = SessionStore(lambda: temp_db)

        async def _assert() -> None:
            async with store.get_checkpointer() as checkpointer:
                assert "AsyncSqliteSaver" in type(checkpointer).__name__

        asyncio.run(_assert())


class TestSessionStoreMessageCounts:
    @pytest.fixture
    def temp_db_with_messages(self, tmp_path):
        db_path = tmp_path / "test_sessions.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB,
                metadata BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                value BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            )
        """)

        serde = JsonPlusSerializer()
        checkpoint_data = {
            "v": 1,
            "ts": "2024-01-01T00:00:00+00:00",
            "id": "test-checkpoint-id",
            "channel_values": {
                "messages": [
                    {"type": "human", "content": "msg1"},
                    {"type": "ai", "content": "msg2"},
                    {"type": "human", "content": "msg3"},
                ]
            },
            "channel_versions": {},
            "versions_seen": {},
            "updated_channels": [],
        }
        type_str, checkpoint_blob = serde.dumps_typed(checkpoint_data)
        metadata = json.dumps({"agent_name": "agent1", "updated_at": "2024-01-01"})
        conn.execute(
            "INSERT INTO checkpoints "
            "(thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, metadata) "
            "VALUES (?, '', ?, ?, ?, ?)",
            ("thread1", "cp_1", type_str, checkpoint_blob, metadata),
        )

        conn.commit()
        conn.close()
        return db_path

    def test_includes_message_count(self, temp_db_with_messages):
        store = SessionStore(lambda: temp_db_with_messages)

        threads = asyncio.run(store.list_threads(include_message_count=True))

        assert len(threads) == 1
        assert threads[0]["message_count"] == 3

    def test_get_thread_history_returns_messages(self, temp_db_with_messages):
        store = SessionStore(lambda: temp_db_with_messages)

        messages = asyncio.run(store.get_thread_history("thread1"))

        assert messages == [
            {"type": "human", "content": "msg1"},
            {"type": "ai", "content": "msg2"},
            {"type": "human", "content": "msg3"},
        ]

    def test_get_thread_history_applies_limit(self, temp_db_with_messages):
        store = SessionStore(lambda: temp_db_with_messages)

        messages = asyncio.run(store.get_thread_history("thread1", limit=2))

        assert messages == [
            {"type": "ai", "content": "msg2"},
            {"type": "human", "content": "msg3"},
        ]

    def test_get_thread_history_returns_empty_for_missing_thread(
        self,
        temp_db_with_messages,
    ):
        store = SessionStore(lambda: temp_db_with_messages)

        messages = asyncio.run(store.get_thread_history("missing"))

        assert messages == []

    def test_get_thread_history_returns_empty_for_non_positive_limit(
        self,
        temp_db_with_messages,
    ):
        store = SessionStore(lambda: temp_db_with_messages)

        messages = asyncio.run(store.get_thread_history("thread1", limit=0))

        assert messages == []

    def test_message_count_uses_cache_for_unchanged_thread(self, temp_db_with_messages):
        store = SessionStore(lambda: temp_db_with_messages)

        with (
            patch.object(
                store,
                "_get_jsonplus_serializer",
                new_callable=AsyncMock,
                return_value=object(),
            ),
            patch.object(
                store,
                "_count_messages_from_checkpoint",
                new_callable=AsyncMock,
                return_value=3,
            ) as mock_count,
        ):
            first = asyncio.run(store.list_threads(include_message_count=True))
            second = asyncio.run(store.list_threads(include_message_count=True))

        assert first[0]["message_count"] == 3
        assert second[0]["message_count"] == 3
        assert mock_count.await_count == 1

    def test_message_count_cache_invalidates_on_new_checkpoint(
        self,
        temp_db_with_messages,
    ):
        store = SessionStore(lambda: temp_db_with_messages)

        with (
            patch.object(
                store,
                "_get_jsonplus_serializer",
                new_callable=AsyncMock,
                return_value=object(),
            ),
            patch.object(
                store,
                "_count_messages_from_checkpoint",
                new_callable=AsyncMock,
                side_effect=[3, 4],
            ) as mock_count,
        ):
            first = asyncio.run(store.list_threads(include_message_count=True))
            assert first[0]["message_count"] == 3

            conn = sqlite3.connect(str(temp_db_with_messages))
            type_str, checkpoint_blob, metadata = conn.execute(
                "SELECT type, checkpoint, metadata FROM checkpoints "
                "WHERE thread_id = ? AND checkpoint_id = ?",
                ("thread1", "cp_1"),
            ).fetchone()
            conn.execute(
                "INSERT INTO checkpoints "
                "(thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, "
                "metadata) "
                "VALUES (?, '', ?, ?, ?, ?)",
                ("thread1", "cp_2", type_str, checkpoint_blob, metadata),
            )
            conn.commit()
            conn.close()

            second = asyncio.run(store.list_threads(include_message_count=True))

        assert second[0]["message_count"] == 4
        assert mock_count.await_count == 2

    def test_apply_cached_thread_message_counts(self, temp_db_with_messages):
        store = SessionStore(lambda: temp_db_with_messages)
        store._message_count_cache["thread-a"] = ("cp_1", 7)
        threads = [
            {
                "thread_id": "thread-a",
                "agent_name": "agent1",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "latest_checkpoint_id": "cp_1",
            },
            {
                "thread_id": "thread-b",
                "agent_name": "agent2",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "latest_checkpoint_id": "cp_1",
            },
        ]

        populated = store.apply_cached_thread_message_counts(threads)

        assert populated == 1
        assert threads[0]["message_count"] == 7
        assert "message_count" not in threads[1]

    async def test_prewarm_thread_message_counts_logs_warning_on_unexpected_error(
        self,
        temp_db_with_messages,
    ):
        store = SessionStore(lambda: temp_db_with_messages)

        with (
            patch.object(
                store,
                "list_threads",
                new_callable=AsyncMock,
                side_effect=RuntimeError("unexpected type mismatch"),
            ),
            patch("deepagents_runtime.sessions.logger.warning") as mock_warning,
        ):
            await store.prewarm_thread_message_counts(limit=3)

        mock_warning.assert_called_once()
