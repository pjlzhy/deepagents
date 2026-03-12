"""Thread management using LangGraph's built-in checkpoint persistence."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from deepagents_runtime.sessions import (
    SessionStore,
    ThreadInfo,
    format_timestamp,
    generate_thread_id as _generate_thread_id,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

_DEFAULT_THREAD_LIMIT = 20
_MAX_MESSAGE_COUNT_CACHE = 4096


def get_db_path() -> Path:
    """Get path to global database.

    Returns:
        Path to the SQLite database file.
    """
    db_dir = Path.home() / ".deepagents"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "sessions.db"


def _resolve_db_path() -> Path:
    """Resolve the current sessions database path.

    Returns:
        Path to the sessions database currently used by the CLI.
    """
    return get_db_path()


def generate_thread_id() -> str:
    """Generate a new 8-character hexadecimal thread ID.

    Returns:
        New thread identifier.
    """
    return _generate_thread_id()


_SESSION_STORE = SessionStore(_resolve_db_path)

# Compatibility aliases kept for existing tests and thread-selector code that
# expect to inspect or clear the CLI session caches directly.
_message_count_cache = _SESSION_STORE._message_count_cache
_recent_threads_cache = _SESSION_STORE._recent_threads_cache


def _get_session_store() -> SessionStore:
    """Return the shared CLI session store instance."""
    return _SESSION_STORE


async def list_threads(
    agent_name: str | None = None,
    limit: int = 20,
    include_message_count: bool = False,
) -> list[ThreadInfo]:
    """List threads from checkpoints table.

    Args:
        agent_name: Optional filter by agent name.
        limit: Maximum number of threads to return.
        include_message_count: Whether to include message counts.

    Returns:
        List of `ThreadInfo` rows.
    """
    return await _get_session_store().list_threads(
        agent_name,
        limit=limit,
        include_message_count=include_message_count,
    )


async def populate_thread_message_counts(threads: list[ThreadInfo]) -> list[ThreadInfo]:
    """Populate `message_count` for an existing thread list.

    Args:
        threads: Thread rows to enrich in place.

    Returns:
        The same list object with `message_count` values populated.
    """
    return await _get_session_store().populate_thread_message_counts(threads)


async def prewarm_thread_message_counts(limit: int | None = None) -> None:
    """Prewarm thread message-count cache for faster `/threads` open.

    Args:
        limit: Maximum threads to prewarm. Uses `get_thread_limit()` when `None`.
    """
    thread_limit = limit if limit is not None else get_thread_limit()
    await _get_session_store().prewarm_thread_message_counts(limit=thread_limit)


def get_cached_threads(
    agent_name: str | None = None,
    limit: int | None = None,
) -> list[ThreadInfo] | None:
    """Get cached recent threads, if available.

    Args:
        agent_name: Optional agent-name filter key.
        limit: Maximum rows requested. Uses `get_thread_limit()` when `None`.

    Returns:
        Copy of cached rows when available, otherwise `None`.
    """
    thread_limit = limit if limit is not None else get_thread_limit()
    return _get_session_store().get_cached_threads(agent_name, limit=thread_limit)


def apply_cached_thread_message_counts(threads: list[ThreadInfo]) -> int:
    """Apply cached message counts onto thread rows when freshness matches.

    Args:
        threads: Thread rows to mutate in place.

    Returns:
        Number of rows that were populated from cache.
    """
    return _get_session_store().apply_cached_thread_message_counts(threads)


def _cache_message_count(thread_id: str, freshness: str | None, count: int) -> None:
    """Cache a thread's message count with a freshness token.

    This thin compatibility helper exists for legacy CLI tests that exercise
    cache eviction behavior directly on the CLI module.
    """
    if len(_message_count_cache) >= _MAX_MESSAGE_COUNT_CACHE and (
        thread_id not in _message_count_cache
    ):
        oldest = next(iter(_message_count_cache))
        _message_count_cache.pop(oldest, None)
    _message_count_cache[thread_id] = (freshness, count)


async def get_most_recent(agent_name: str | None = None) -> str | None:
    """Get most recent thread ID, optionally filtered by agent.

    Returns:
        Most recent thread ID, or `None` when no threads exist.
    """
    return await _get_session_store().get_most_recent(agent_name)


async def get_thread_agent(thread_id: str) -> str | None:
    """Get agent name for a thread.

    Returns:
        Agent name associated with the thread, or `None` when not found.
    """
    return await _get_session_store().get_thread_agent(thread_id)


async def thread_exists(thread_id: str) -> bool:
    """Check if a thread exists in checkpoints.

    Returns:
        `True` when the thread exists, otherwise `False`.
    """
    return await _get_session_store().thread_exists(thread_id)


async def find_similar_threads(thread_id: str, limit: int = 3) -> list[str]:
    """Find threads whose IDs start with the given prefix.

    Returns:
        Matching thread IDs in sorted order.
    """
    return await _get_session_store().find_similar_threads(thread_id, limit=limit)


async def delete_thread(thread_id: str) -> bool:
    """Delete thread checkpoints.

    Returns:
        `True` when the thread was deleted, otherwise `False`.
    """
    return await _get_session_store().delete_thread(thread_id)


async def get_thread_history(
    thread_id: str,
    *,
    limit: int | None = None,
) -> list[object]:
    """Load stored messages for the most recent checkpoint of a thread.

    This is a thin compatibility wrapper around `deepagents_runtime.sessions`.

    Args:
        thread_id: Thread identifier.
        limit: Optional maximum number of messages to return. When provided,
            returns the most recent `limit` messages.

    Returns:
        List of stored message objects, or an empty list when unavailable.
    """
    return await _get_session_store().get_thread_history(thread_id, limit=limit)


@asynccontextmanager
async def get_checkpointer() -> AsyncIterator[AsyncSqliteSaver]:
    """Get `AsyncSqliteSaver` for the global database.

    Yields:
        Checkpointer bound to the shared sessions database.
    """
    async with _get_session_store().get_checkpointer() as checkpointer:
        yield checkpointer


def get_thread_limit() -> int:
    """Read the thread listing limit from `DA_CLI_RECENT_THREADS`.

    Falls back to `_DEFAULT_THREAD_LIMIT` when the variable is unset or contains
    a non-integer value. The result is clamped to a minimum of 1.

    Returns:
        Number of threads to display.
    """
    raw = os.environ.get("DA_CLI_RECENT_THREADS")
    if raw is None:
        return _DEFAULT_THREAD_LIMIT
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "Invalid DA_CLI_RECENT_THREADS value %r, using default %d",
            raw,
            _DEFAULT_THREAD_LIMIT,
        )
        return _DEFAULT_THREAD_LIMIT


async def list_threads_command(
    agent_name: str | None = None,
    limit: int | None = None,
) -> None:
    """CLI handler for `deepagents threads list`.

    Fetches and displays a table of recent conversation threads, optionally
    filtered by agent name.

    Args:
        agent_name: Only show threads belonging to this agent.

            When `None`, threads for all agents are shown.
        limit: Maximum number of threads to display.

            When `None`, reads from `DA_CLI_RECENT_THREADS` or falls back to
            the default.
    """
    from rich.table import Table

    from deepagents_cli.config import COLORS, console

    limit = get_thread_limit() if limit is None else max(1, limit)

    threads = await list_threads(agent_name, limit=limit, include_message_count=True)

    if not threads:
        if agent_name:
            console.print(
                f"[yellow]No threads found for agent '{agent_name}'.[/yellow]"
            )
        else:
            console.print("[yellow]No threads found.[/yellow]")
        console.print("[dim]Start a conversation with: deepagents[/dim]")
        return

    title = (
        f"Recent threads for '{agent_name}' (last {limit})"
        if agent_name
        else f"Recent Threads (last {limit})"
    )

    table = Table(
        title=title, show_header=True, header_style=f"bold {COLORS['primary']}"
    )
    table.add_column("Thread ID", style="bold")
    table.add_column("Agent")
    table.add_column("Messages", justify="right")
    table.add_column("Last Used", style="dim")

    for t in threads:
        table.add_row(
            t["thread_id"],
            t["agent_name"] or "unknown",
            str(t.get("message_count", 0)),
            format_timestamp(t.get("updated_at")),
        )

    console.print()
    console.print(table)
    console.print()


async def delete_thread_command(thread_id: str) -> None:
    """CLI handler for: deepagents threads delete."""
    from deepagents_cli.config import console

    deleted = await delete_thread(thread_id)

    if deleted:
        console.print(f"[green]Thread '{thread_id}' deleted.[/green]")
    else:
        console.print(f"[red]Thread '{thread_id}' not found.[/red]")
