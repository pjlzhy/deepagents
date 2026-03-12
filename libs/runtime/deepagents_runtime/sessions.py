"""Shared session and thread persistence services."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    import aiosqlite
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

_MAX_MESSAGE_COUNT_CACHE = 4096
_MAX_RECENT_THREADS_CACHE_KEYS = 16


class ThreadInfo(TypedDict):
    """Thread metadata returned by session queries."""

    thread_id: str
    agent_name: str | None
    updated_at: str | None
    message_count: NotRequired[int]
    latest_checkpoint_id: NotRequired[str | None]


def format_timestamp(iso_timestamp: str | None) -> str:
    """Format ISO timestamp for display (for example `Dec 30, 6:10pm`).

    Returns:
        Formatted timestamp string, or an empty string if unavailable.
    """
    if not iso_timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(iso_timestamp).astimezone()
        date_part = dt.strftime("%b %d")
        time_part = dt.strftime("%I:%M%p").lstrip("0")
        return f"{date_part}, {time_part}".lower()
    except (ValueError, TypeError):
        logger.debug(
            "Failed to parse timestamp %r; displaying as blank",
            iso_timestamp,
            exc_info=True,
        )
        return ""


def generate_thread_id() -> str:
    """Generate a new 8-character hexadecimal thread ID.

    Returns:
        Newly generated thread ID string.
    """
    return uuid.uuid4().hex[:8]


class SessionStore:
    """Cache-aware thread/session store backed by LangGraph checkpoints."""

    def __init__(self, db_path_provider: Callable[[], Path]) -> None:
        """Initialize the store.

        Args:
            db_path_provider: Callable that returns the SQLite database path.
        """
        self._db_path_provider = db_path_provider
        self._aiosqlite_patched = False
        self._jsonplus_serializer: JsonPlusSerializer | None = None
        self._message_count_cache: dict[str, tuple[str | None, int]] = {}
        self._recent_threads_cache: dict[tuple[str | None, int], list[ThreadInfo]] = {}

    @property
    def db_path(self) -> Path:
        """Return the current database path."""
        return self._db_path_provider()

    def clear_caches(self) -> None:
        """Clear in-memory caches used for fast thread listing."""
        self._jsonplus_serializer = None
        self._message_count_cache.clear()
        self._recent_threads_cache.clear()

    def get_cached_threads(
        self,
        agent_name: str | None = None,
        *,
        limit: int,
    ) -> list[ThreadInfo] | None:
        """Get cached recent threads, if available.

        Returns:
            Cached recent threads with cached message counts applied, or `None`
            when no suitable cached entry is available.
        """

        def _copy_with_cached_counts(rows: list[ThreadInfo]) -> list[ThreadInfo]:
            copied_rows = self._copy_threads(rows)
            self.apply_cached_thread_message_counts(copied_rows)
            return copied_rows

        if limit < 1:
            return None

        exact = self._recent_threads_cache.get((agent_name, limit))
        if exact is not None:
            return _copy_with_cached_counts(exact)

        best_key: tuple[str | None, int] | None = None
        for key in self._recent_threads_cache:
            cache_agent, cache_limit = key
            if cache_agent != agent_name or cache_limit < limit:
                continue
            if best_key is None or cache_limit < best_key[1]:
                best_key = key

        if best_key is None:
            return None

        return _copy_with_cached_counts(self._recent_threads_cache[best_key][:limit])

    def apply_cached_thread_message_counts(self, threads: list[ThreadInfo]) -> int:
        """Apply cached message counts onto thread rows when freshness matches.

        Returns:
            Number of threads updated with cached counts.
        """
        populated = 0
        for thread in threads:
            if "message_count" in thread:
                continue
            thread_id = thread["thread_id"]
            freshness = self._thread_freshness(thread)
            cached = self._message_count_cache.get(thread_id)
            if cached is None or cached[0] != freshness:
                continue
            thread["message_count"] = cached[1]
            populated += 1
        return populated

    async def list_threads(
        self,
        agent_name: str | None = None,
        *,
        limit: int = 20,
        include_message_count: bool = False,
    ) -> list[ThreadInfo]:
        """List threads from the checkpoints table.

        Returns:
            Thread rows sorted by most recently updated.
        """
        async with self._connect() as conn:
            if not await self._table_exists(conn, "checkpoints"):
                return []

            if agent_name:
                query = """
                    SELECT thread_id,
                           json_extract(metadata, '$.agent_name') as agent_name,
                           MAX(json_extract(metadata, '$.updated_at')) as updated_at,
                           MAX(checkpoint_id) as latest_checkpoint_id
                    FROM checkpoints
                    WHERE json_extract(metadata, '$.agent_name') = ?
                    GROUP BY thread_id
                    ORDER BY updated_at DESC
                    LIMIT ?
                """
                params: tuple[str | int, ...] = (agent_name, limit)
            else:
                query = """
                    SELECT thread_id,
                           json_extract(metadata, '$.agent_name') as agent_name,
                           MAX(json_extract(metadata, '$.updated_at')) as updated_at,
                           MAX(checkpoint_id) as latest_checkpoint_id
                    FROM checkpoints
                    GROUP BY thread_id
                    ORDER BY updated_at DESC
                    LIMIT ?
                """
                params = (limit,)

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                threads: list[ThreadInfo] = [
                    ThreadInfo(
                        thread_id=row[0],
                        agent_name=row[1],
                        updated_at=row[2],
                        latest_checkpoint_id=row[3],
                    )
                    for row in rows
                ]

            if include_message_count and threads:
                await self._populate_message_counts(conn, threads)

            self._cache_recent_threads(agent_name, limit, threads)
            return threads

    async def populate_thread_message_counts(
        self,
        threads: list[ThreadInfo],
    ) -> list[ThreadInfo]:
        """Populate `message_count` for an existing thread list.

        Returns:
            The input list (mutated in-place) for convenience.
        """
        if not threads:
            return threads

        async with self._connect() as conn:
            await self._populate_message_counts(conn, threads)
        return threads

    async def prewarm_thread_message_counts(self, *, limit: int) -> None:
        """Prewarm thread message-count cache for faster thread-list startup."""
        if limit < 1:
            return

        try:
            threads = await self.list_threads(limit=limit, include_message_count=False)
            if threads:
                await self.populate_thread_message_counts(threads)
            self._cache_recent_threads(None, limit, threads)
        except (OSError, sqlite3.Error):
            logger.debug("Could not prewarm thread message counts", exc_info=True)
        except Exception:
            logger.warning(
                "Unexpected error while prewarming thread message counts",
                exc_info=True,
            )

    async def get_most_recent(self, agent_name: str | None = None) -> str | None:
        """Get the most recent thread ID, optionally filtered by agent.

        Returns:
            Thread ID string, or `None` if no checkpoints exist.
        """
        async with self._connect() as conn:
            if not await self._table_exists(conn, "checkpoints"):
                return None

            if agent_name:
                query = """
                    SELECT thread_id FROM checkpoints
                    WHERE json_extract(metadata, '$.agent_name') = ?
                    ORDER BY checkpoint_id DESC
                    LIMIT 1
                """
                params: tuple[str, ...] = (agent_name,)
            else:
                query = (
                    "SELECT thread_id FROM checkpoints "
                    "ORDER BY checkpoint_id DESC LIMIT 1"
                )
                params = ()

            async with conn.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def get_thread_agent(self, thread_id: str) -> str | None:
        """Get the agent name associated with a thread.

        Returns:
            Agent name string, or `None` if unavailable.
        """
        async with self._connect() as conn:
            if not await self._table_exists(conn, "checkpoints"):
                return None

            query = """
                SELECT json_extract(metadata, '$.agent_name')
                FROM checkpoints
                WHERE thread_id = ?
                LIMIT 1
            """
            async with conn.execute(query, (thread_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def thread_exists(self, thread_id: str) -> bool:
        """Check if a thread exists in checkpoints.

        Returns:
            `True` when the thread exists, `False` otherwise.
        """
        async with self._connect() as conn:
            if not await self._table_exists(conn, "checkpoints"):
                return False

            query = "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1"
            async with conn.execute(query, (thread_id,)) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def find_similar_threads(
        self,
        thread_id: str,
        *,
        limit: int = 3,
    ) -> list[str]:
        """Find threads whose IDs start with the given prefix.

        Returns:
            Matching thread IDs (sorted), up to `limit`.
        """
        async with self._connect() as conn:
            if not await self._table_exists(conn, "checkpoints"):
                return []

            query = """
                SELECT DISTINCT thread_id
                FROM checkpoints
                WHERE thread_id LIKE ?
                ORDER BY thread_id
                LIMIT ?
            """
            prefix = thread_id + "%"
            async with conn.execute(query, (prefix, limit)) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def get_thread_history(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
    ) -> list[object]:
        """Load stored messages for the most recent checkpoint of a thread.

        This helper reads the latest checkpoint row directly from the sessions
        SQLite database, deserializes it via LangGraph's JsonPlus serializer,
        and returns the `messages` channel values.

        Args:
            thread_id: Thread ID to load history for.
            limit: Optional maximum number of message objects to return. When
                provided, returns the most recent `limit` messages.

        Returns:
            List of stored message objects, or an empty list when history is
            unavailable.
        """
        if not thread_id:
            return []
        if limit is not None and limit < 1:
            return []

        async with self._connect() as conn:
            if not await self._table_exists(conn, "checkpoints"):
                return []

            query = """
                SELECT type, checkpoint
                FROM checkpoints
                WHERE thread_id = ?
                ORDER BY checkpoint_id DESC
                LIMIT 1
            """
            async with conn.execute(query, (thread_id,)) as cursor:
                row = await cursor.fetchone()
                if not row or not row[0] or not row[1]:
                    return []

            type_str, checkpoint_blob = row
            serde = await self._get_jsonplus_serializer()
            try:
                data = serde.loads_typed((type_str, checkpoint_blob))
                if not isinstance(data, dict):
                    return []
                channel_values = data.get("channel_values", {})
                if not isinstance(channel_values, dict):
                    return []
                messages = channel_values.get("messages", [])
            except (ValueError, TypeError, KeyError):
                logger.warning(
                    "Failed to deserialize checkpoint history for thread %s",
                    thread_id,
                    exc_info=True,
                )
                return []

            if isinstance(messages, tuple):
                messages = list(messages)
            if not isinstance(messages, list):
                return []

            if limit is None:
                return list(messages)
            return list(messages[-limit:])

    async def delete_thread(self, thread_id: str) -> bool:
        """Delete a thread and its related writes.

        Returns:
            `True` when at least one checkpoint row was deleted, `False` otherwise.
        """
        async with self._connect() as conn:
            if not await self._table_exists(conn, "checkpoints"):
                return False

            cursor = await conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ?",
                (thread_id,),
            )
            deleted = cursor.rowcount > 0
            if await self._table_exists(conn, "writes"):
                await conn.execute(
                    "DELETE FROM writes WHERE thread_id = ?",
                    (thread_id,),
                )
            await conn.commit()
            if deleted:
                self._message_count_cache.pop(thread_id, None)
                for key, rows in list(self._recent_threads_cache.items()):
                    filtered = [row for row in rows if row["thread_id"] != thread_id]
                    self._recent_threads_cache[key] = filtered
            return deleted

    @asynccontextmanager
    async def get_checkpointer(self) -> AsyncIterator[AsyncSqliteSaver]:
        """Yield an `AsyncSqliteSaver` for the configured database."""
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        self._patch_aiosqlite()

        async with AsyncSqliteSaver.from_conn_string(str(self.db_path)) as checkpointer:
            yield checkpointer

    def _patch_aiosqlite(self) -> None:
        """Patch `aiosqlite.Connection` with `is_alive()` if missing."""
        if self._aiosqlite_patched:
            return

        import aiosqlite as _aiosqlite

        if not hasattr(_aiosqlite.Connection, "is_alive"):

            def _is_alive(self: _aiosqlite.Connection) -> bool:
                return bool(self._running and self._connection is not None)

            _aiosqlite.Connection.is_alive = _is_alive  # type: ignore[attr-defined]

        self._aiosqlite_patched = True

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """Connect to the configured SQLite database.

        Yields:
            Connected SQLite database handle.
        """
        import aiosqlite as _aiosqlite

        self._patch_aiosqlite()

        async with _aiosqlite.connect(str(self.db_path), timeout=30.0) as conn:
            yield conn

    @staticmethod
    async def _table_exists(conn: aiosqlite.Connection, table: str) -> bool:
        """Check if a table exists in the database.

        Returns:
            `True` if the table exists, `False` otherwise.
        """
        query = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?"
        async with conn.execute(query, (table,)) as cursor:
            return await cursor.fetchone() is not None

    async def _populate_message_counts(
        self,
        conn: aiosqlite.Connection,
        threads: list[ThreadInfo],
    ) -> None:
        """Fill `message_count` on thread rows with cache-aware lookup."""
        serde = await self._get_jsonplus_serializer()
        for thread in threads:
            thread_id = thread["thread_id"]
            freshness = self._thread_freshness(thread)
            cached = self._message_count_cache.get(thread_id)
            if cached is not None and cached[0] == freshness:
                thread["message_count"] = cached[1]
                continue

            count = await self._count_messages_from_checkpoint(conn, thread_id, serde)
            thread["message_count"] = count
            self._cache_message_count(thread_id, freshness, count)

    async def _get_jsonplus_serializer(self) -> JsonPlusSerializer:
        """Return a cached JsonPlus serializer, loading it off the UI loop."""
        if self._jsonplus_serializer is not None:
            return self._jsonplus_serializer

        loop = asyncio.get_running_loop()
        self._jsonplus_serializer = await loop.run_in_executor(
            None,
            self._create_jsonplus_serializer,
        )
        return self._jsonplus_serializer

    @staticmethod
    def _create_jsonplus_serializer() -> JsonPlusSerializer:
        """Import and create a `JsonPlusSerializer`.

        Returns:
            JsonPlus serializer instance.
        """
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

        return JsonPlusSerializer()

    def _cache_message_count(
        self,
        thread_id: str,
        freshness: str | None,
        count: int,
    ) -> None:
        """Cache a thread's message count with a freshness token."""
        if len(self._message_count_cache) >= _MAX_MESSAGE_COUNT_CACHE and (
            thread_id not in self._message_count_cache
        ):
            oldest = next(iter(self._message_count_cache))
            self._message_count_cache.pop(oldest, None)
        self._message_count_cache[thread_id] = (freshness, count)

    @staticmethod
    def _thread_freshness(thread: ThreadInfo) -> str | None:
        """Return a cache freshness token for a thread row."""
        return thread.get("latest_checkpoint_id") or thread.get("updated_at")

    def _cache_recent_threads(
        self,
        agent_name: str | None,
        limit: int,
        threads: list[ThreadInfo],
    ) -> None:
        """Store a copy of recent thread rows for fast selector startup."""
        key = (agent_name, max(1, limit))
        if len(self._recent_threads_cache) >= _MAX_RECENT_THREADS_CACHE_KEYS and (
            key not in self._recent_threads_cache
        ):
            self._recent_threads_cache.clear()
        self._recent_threads_cache[key] = self._copy_threads(threads)

    @staticmethod
    def _copy_threads(threads: list[ThreadInfo]) -> list[ThreadInfo]:
        """Return shallow-copied thread rows."""
        return [ThreadInfo(**thread) for thread in threads]

    @staticmethod
    async def _count_messages_from_checkpoint(
        conn: aiosqlite.Connection,
        thread_id: str,
        serde: JsonPlusSerializer,
    ) -> int:
        """Count messages from the most recent checkpoint blob.

        Returns:
            Message count for the most recent checkpoint, or `0` if unavailable.
        """
        query = """
            SELECT type, checkpoint
            FROM checkpoints
            WHERE thread_id = ?
            ORDER BY checkpoint_id DESC
            LIMIT 1
        """
        async with conn.execute(query, (thread_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or not row[0] or not row[1]:
                return 0

            type_str, checkpoint_blob = row
            try:
                data = serde.loads_typed((type_str, checkpoint_blob))
                channel_values = data.get("channel_values", {})
                messages = channel_values.get("messages", [])
                return len(messages)
            except (ValueError, TypeError, KeyError):
                logger.warning(
                    "Failed to deserialize checkpoint for thread %s; "
                    "message count will show as 0",
                    thread_id,
                    exc_info=True,
                )
                return 0
