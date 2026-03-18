"""Session and thread management, backed by SQLite.

Provides pure async data access for session persistence.
CLI-specific rendering (Rich tables) is NOT included here.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents_runtime.spec import ThreadInfo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_aiosqlite_patched = False


def _patch_aiosqlite() -> None:
    """Patch aiosqlite.Connection with ``is_alive()`` if missing.

    Required by langgraph-checkpoint >= 2.1.0.
    """
    global _aiosqlite_patched
    if _aiosqlite_patched:
        return
    import aiosqlite as _aiosqlite

    if not hasattr(_aiosqlite.Connection, "is_alive"):

        def _is_alive(self: Any) -> bool:
            return bool(self._running and self._connection is not None)

        _aiosqlite.Connection.is_alive = _is_alive  # type: ignore[attr-defined]
    _aiosqlite_patched = True


def get_db_path(base_dir: Path | None = None) -> Path:
    """Get path to sessions database.

    Args:
        base_dir: Override base directory. Defaults to ``~/.deepagents/``.
    """
    db_dir = base_dir or (Path.home() / ".deepagents")
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "sessions.db"


def generate_thread_id() -> str:
    """Generate a new 8-char hex thread ID."""
    return uuid.uuid4().hex[:8]


@asynccontextmanager
async def _connect(db_path: Path | None = None) -> AsyncIterator[Any]:
    """Open an aiosqlite connection with patching applied."""
    import aiosqlite

    _patch_aiosqlite()
    async with aiosqlite.connect(str(db_path or get_db_path()), timeout=30.0) as conn:
        yield conn


async def list_threads(
    agent_name: str | None = None,
    limit: int = 20,
    include_message_count: bool = False,
    db_path: Path | None = None,
) -> list[ThreadInfo]:
    """List threads from checkpoints table.

    Args:
        agent_name: Optional filter by agent name.
        limit: Maximum threads to return.
        include_message_count: Whether to compute message counts (expensive).
        db_path: Override database path.

    Returns:
        List of ThreadInfo dicts ordered by most recent first.
    """
    async with _connect(db_path) as conn:
        # Check if checkpoints table exists
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        ) as cursor:
            if not await cursor.fetchone():
                return []

        query = (
            "SELECT DISTINCT thread_id FROM checkpoints "
            "ORDER BY rowid DESC LIMIT ?"
        )
        async with conn.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()

    threads: list[ThreadInfo] = []
    for (thread_id,) in rows:
        info: ThreadInfo = {
            "thread_id": thread_id,
            "agent_name": agent_name,
            "updated_at": None,
        }
        threads.append(info)

    return threads


async def get_most_recent(
    agent_name: str | None = None,
    db_path: Path | None = None,
) -> str | None:
    """Get most recent thread_id."""
    threads = await list_threads(agent_name=agent_name, limit=1, db_path=db_path)
    return threads[0]["thread_id"] if threads else None


async def thread_exists(thread_id: str, db_path: Path | None = None) -> bool:
    """Check if a thread exists in checkpoints."""
    async with _connect(db_path) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        ) as cursor:
            if not await cursor.fetchone():
                return False

        async with conn.execute(
            "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1",
            (thread_id,),
        ) as cursor:
            return await cursor.fetchone() is not None


async def delete_thread(thread_id: str, db_path: Path | None = None) -> bool:
    """Delete thread checkpoints.

    Returns:
        True if the thread existed and was deleted.
    """
    async with _connect(db_path) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        ) as cursor:
            if not await cursor.fetchone():
                return False

        cursor = await conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,)
        )
        await conn.commit()
        return cursor.rowcount > 0


async def get_thread_agent(
    thread_id: str, db_path: Path | None = None
) -> str | None:
    """Get agent_name for a thread from checkpoint metadata."""
    # The agent name is stored in checkpoint metadata; this is a simplified
    # implementation that returns None until full metadata parsing is added.
    return None


@asynccontextmanager
async def get_checkpointer(
    db_path: Path | None = None,
) -> AsyncIterator[Any]:
    """Get AsyncSqliteSaver for checkpoint persistence.

    Yields:
        AsyncSqliteSaver instance.
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    _patch_aiosqlite()
    path = db_path or get_db_path()
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        yield checkpointer
