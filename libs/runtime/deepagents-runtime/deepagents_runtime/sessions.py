"""Session and thread management, backed by SQLite.

Provides pure async data access for session persistence.
CLI-specific rendering (Rich tables) is NOT included here.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deepagents_runtime.spec import ThreadInfo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

logger = logging.getLogger(__name__)

_aiosqlite_patched = False
_jsonplus_serializer: JsonPlusSerializer | None = None

_DEFAULT_SESSION_PAGE_SIZE = 20
_DEFAULT_MESSAGE_PAGE_SIZE = 100
_MAX_SESSION_PAGE_SIZE = 200
_MAX_MESSAGE_PAGE_SIZE = 1000
_AGENT_NAME_SQL = """
COALESCE(
    json_extract(metadata, '$.agent_name'),
    json_extract(metadata, '$.assistant_id')
)
"""


@dataclass
class SessionSummaryRecord:
    """Runtime session summary derived from checkpoint state."""

    thread_id: str
    agent_name: str | None
    updated_at: str | None
    latest_checkpoint_id: str | None
    message_count: int
    initial_prompt: str | None
    history_mode: str = "resume_view"


@dataclass
class SessionListPage:
    """One page of runtime session summaries."""

    sessions: list[SessionSummaryRecord]
    next_page_token: str = ""


@dataclass
class SessionDetailRecord:
    """Session summary plus additional diagnostic counters."""

    summary: SessionSummaryRecord
    checkpoint_count: int


@dataclass
class SessionMessageRecord:
    """One normalized session message entry."""

    index: int
    role: str
    text: str
    tool_call_id: str = ""
    tool_name: str = ""
    is_error: bool = False
    raw: dict[str, Any] | None = None


@dataclass
class SessionMessagesPage:
    """One page of checkpoint-backed session messages."""

    thread_id: str
    resolved_checkpoint_id: str
    actual_mode: str
    total_message_count: int
    messages: list[SessionMessageRecord]
    next_page_token: str = ""


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


async def _table_exists(conn: Any, table: str) -> bool:
    """Check whether a SQLite table exists."""
    query = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?"
    async with conn.execute(query, (table,)) as cursor:
        return await cursor.fetchone() is not None


async def _get_jsonplus_serializer() -> JsonPlusSerializer:
    """Return a shared JsonPlus serializer for checkpoint decoding."""
    global _jsonplus_serializer
    if _jsonplus_serializer is None:
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

        _jsonplus_serializer = JsonPlusSerializer()
    return _jsonplus_serializer


def _encode_page_token(payload: dict[str, Any]) -> str:
    """Encode an opaque page token."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_page_token(token: str) -> dict[str, Any]:
    """Decode an opaque page token."""
    padding = "=" * (-len(token) % 4)
    try:
        data = json.loads(
            base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8")
        )
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        msg = "invalid page_token"
        raise ValueError(msg) from exc
    if not isinstance(data, dict):
        msg = "invalid page_token"
        raise ValueError(msg)
    return cast("dict[str, Any]", data)


def _resolve_page_size(raw_page_size: int, *, default: int, maximum: int) -> int:
    """Resolve a request page size with defaults and clamping."""
    if raw_page_size < 0:
        msg = "page_size cannot be negative"
        raise ValueError(msg)
    if raw_page_size == 0:
        return default
    return min(raw_page_size, maximum)


async def _list_session_rows(
    conn: Any,
    *,
    agent_name: str | None,
    limit: int,
    offset: int,
) -> list[tuple[str, str | None, str | None, str | None]]:
    """List latest checkpoint metadata rows per thread."""
    params: list[str | int] = [limit, offset]
    filter_sql = ""
    if agent_name:
        filter_sql = "AND agent_name = ?"
        params = [agent_name, limit, offset]

    query = f"""
        SELECT thread_id, agent_name, updated_at, latest_checkpoint_id
        FROM (
            SELECT thread_id,
                   COALESCE(
                       json_extract(metadata, '$.agent_name'),
                       json_extract(metadata, '$.assistant_id')
                   ) AS agent_name,
                   json_extract(metadata, '$.updated_at') AS updated_at,
                   checkpoint_id AS latest_checkpoint_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY thread_id ORDER BY checkpoint_id DESC
                   ) AS rn
            FROM checkpoints
        )
        WHERE rn = 1
        {filter_sql}
        ORDER BY updated_at DESC, latest_checkpoint_id DESC, thread_id DESC
        LIMIT ? OFFSET ?
    """  # noqa: S608  # filter_sql is selected from fixed internal clauses
    async with conn.execute(query, tuple(params)) as cursor:
        rows = await cursor.fetchall()
    return [
        (str(row[0]), row[1], row[2], row[3])
        for row in rows
    ]


def _checkpoint_agent_filter(
    agent_name: str | None,
) -> tuple[str, tuple[str, ...]]:
    """Return one fixed SQL fragment and args for agent-scoped checkpoint queries."""
    if not agent_name:
        return "", ()
    return f" AND {_AGENT_NAME_SQL} = ?", (agent_name,)


async def _load_checkpoint_row(
    conn: Any,
    *,
    thread_id: str,
    agent_name: str | None = None,
    checkpoint_id: str | None = None,
) -> tuple[str, str, bytes, str | None] | None:
    """Load one checkpoint row for a thread."""
    agent_filter_sql, agent_params = _checkpoint_agent_filter(agent_name)
    if checkpoint_id:
        query = f"""
            SELECT checkpoint_id, type, checkpoint, metadata
            FROM checkpoints
            WHERE thread_id = ? {agent_filter_sql} AND checkpoint_id = ?
            LIMIT 1
        """  # noqa: S608  # agent_filter_sql is selected from a fixed internal clause
        params: tuple[str, ...] = (thread_id, *agent_params, checkpoint_id)
    else:
        query = f"""
            SELECT checkpoint_id, type, checkpoint, metadata
            FROM checkpoints
            WHERE thread_id = ? {agent_filter_sql}
            ORDER BY checkpoint_id DESC
            LIMIT 1
        """  # noqa: S608  # agent_filter_sql is selected from a fixed internal clause
        params = (thread_id, *agent_params)

    async with conn.execute(query, params) as cursor:
        row = await cursor.fetchone()
    if not row or not row[0] or not row[1] or not row[2]:
        return None

    return str(row[0]), str(row[1]), cast(bytes, row[2]), row[3]


def _checkpoint_messages(data: object) -> list[object]:
    """Return checkpoint messages when the decoded payload has the expected shape."""
    if not isinstance(data, dict):
        return []

    payload = cast("dict[str, object]", data)
    channel_values = payload.get("channel_values")
    if not isinstance(channel_values, dict):
        return []

    channel_values_dict = cast("dict[str, object]", channel_values)
    messages = channel_values_dict.get("messages")
    if not isinstance(messages, list):
        return []

    return cast("list[object]", messages)


def _checkpoint_artifacts(data: object) -> dict[str, object]:
    """Return artifacts channel when the decoded checkpoint has the expected shape."""
    if not isinstance(data, dict):
        return {}
    payload = cast("dict[str, object]", data)
    channel_values = payload.get("channel_values")
    if not isinstance(channel_values, dict):
        return {}
    channel_values_dict = cast("dict[str, object]", channel_values)
    artifacts = channel_values_dict.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return cast("dict[str, object]", artifacts)


def _message_type_name(message: object) -> str:
    """Return the logical type name for a checkpoint message object."""
    if isinstance(message, dict):
        type_name = message.get("type")
        return type_name if isinstance(type_name, str) else ""
    type_name = getattr(message, "type", "")
    return type_name if isinstance(type_name, str) else ""


def _message_content(message: object) -> object:
    """Extract message content from a checkpoint message object."""
    if isinstance(message, dict):
        return message.get("content")
    return getattr(message, "content", None)


def _coerce_text_content(content: object) -> str:
    """Normalize checkpoint message content into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content_dict = cast("dict[str, object]", content)
        if content_dict.get("type") in {"text", "output_text"}:
            text = content_dict.get("text")
            return text if isinstance(text, str) else ""
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if isinstance(part, dict):
                part_dict = cast("dict[str, object]", part)
                if part_dict.get("type") in {"text", "output_text"}:
                    text = part_dict.get("text")
                    parts.append(text if isinstance(text, str) else "")
            elif part is not None:
                parts.append(str(part))
        return "".join(parts).strip()
    if content is None:
        return ""
    return str(content)


def _initial_prompt_from_messages(messages: list[object]) -> str | None:
    """Return the first human message content from a checkpoint message list."""
    for message in messages:
        if _message_type_name(message) == "human":
            text = _coerce_text_content(_message_content(message))
            return text or None
    return None


def _summarize_checkpoint(data: object) -> tuple[int, str | None]:
    """Extract message count and initial prompt from one checkpoint payload."""
    messages = _checkpoint_messages(data)
    return len(messages), _initial_prompt_from_messages(messages)


async def _summarize_checkpoint_row(
    conn: Any,
    *,
    thread_id: str,
    agent_name: str | None = None,
    checkpoint_id: str | None = None,
) -> tuple[str | None, int, str | None]:
    """Summarize the resolved checkpoint for a thread."""
    row = await _load_checkpoint_row(
        conn,
        thread_id=thread_id,
        agent_name=agent_name,
        checkpoint_id=checkpoint_id,
    )
    if row is None:
        return None, 0, None

    resolved_checkpoint_id, type_str, checkpoint_blob, _ = row
    serde = await _get_jsonplus_serializer()
    try:
        data = serde.loads_typed((type_str, checkpoint_blob))
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.warning(
            "Failed to deserialize checkpoint for thread %s",
            thread_id,
            exc_info=True,
        )
        return resolved_checkpoint_id, 0, None

    message_count, initial_prompt = _summarize_checkpoint(data)
    return resolved_checkpoint_id, message_count, initial_prompt


async def _checkpoint_count(
    conn: Any,
    *,
    thread_id: str,
    agent_name: str | None = None,
) -> int:
    """Count persisted checkpoint rows for a thread."""
    agent_filter_sql, agent_params = _checkpoint_agent_filter(agent_name)
    query = f"SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?{agent_filter_sql}"
    async with conn.execute(
        query,  # noqa: S608  # agent_filter_sql is selected from a fixed internal clause
        (thread_id, *agent_params),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


def _coerce_checkpoint_messages(messages: list[object]) -> list[object]:
    """Convert raw checkpoint message payloads into LangChain messages when needed."""
    if messages and isinstance(messages[0], dict):
        from langchain_core.messages.utils import convert_to_messages

        try:
            return list(convert_to_messages(messages))
        except Exception:
            logger.warning("Failed to convert checkpoint messages", exc_info=True)
            return messages
    return messages


def _safe_raw_payload(message: object) -> dict[str, Any] | None:
    """Best-effort JSON-serializable raw payload for one message."""
    if isinstance(message, dict):
        return cast("dict[str, Any]", message)

    model_dump = getattr(message, "model_dump", None)
    if callable(model_dump):
        try:
            data = model_dump(mode="json")
        except TypeError:
            data = model_dump()
        if isinstance(data, dict):
            return cast("dict[str, Any]", data)

    return None


def _normalize_session_messages(
    messages: list[object],
    *,
    include_raw: bool,
) -> list[SessionMessageRecord]:
    """Normalize checkpoint messages into stable session message entries."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    normalized_messages = _coerce_checkpoint_messages(messages)
    result: list[SessionMessageRecord] = []
    pending_tool_indices: dict[str, int] = {}

    for message in normalized_messages:
        raw_payload = _safe_raw_payload(message) if include_raw else None

        if isinstance(message, SystemMessage):
            result.append(
                SessionMessageRecord(
                    index=len(result),
                    role="system",
                    text=_coerce_text_content(message.content),
                    raw=raw_payload,
                )
            )
            continue

        if isinstance(message, HumanMessage):
            result.append(
                SessionMessageRecord(
                    index=len(result),
                    role="human",
                    text=_coerce_text_content(message.content),
                    raw=raw_payload,
                )
            )
            continue

        if isinstance(message, AIMessage):
            text = _coerce_text_content(message.content)
            if text:
                result.append(
                    SessionMessageRecord(
                        index=len(result),
                        role="ai",
                        text=text,
                        raw=raw_payload,
                    )
                )

            for tool_call in getattr(message, "tool_calls", []):
                tool_call_id = str(tool_call.get("id", ""))
                tool_name = str(tool_call.get("name", ""))
                tool_raw = cast("dict[str, Any]", tool_call) if include_raw else None
                result.append(
                    SessionMessageRecord(
                        index=len(result),
                        role="tool",
                        text="",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        is_error=False,
                        raw=tool_raw,
                    )
                )
                if tool_call_id:
                    pending_tool_indices[tool_call_id] = len(result) - 1
            continue

        if isinstance(message, ToolMessage):
            tool_call_id = getattr(message, "tool_call_id", "") or ""
            text = _coerce_text_content(message.content)
            is_error = getattr(message, "status", "success") != "success"
            pending_index = pending_tool_indices.pop(tool_call_id, None)
            if pending_index is not None:
                pending_message = result[pending_index]
                pending_message.text = text
                pending_message.is_error = is_error
                if include_raw and pending_message.raw is None:
                    pending_message.raw = raw_payload
            else:
                result.append(
                    SessionMessageRecord(
                        index=len(result),
                        role="tool",
                        text=text,
                        tool_call_id=tool_call_id,
                        is_error=is_error,
                        raw=raw_payload,
                    )
                )
            continue

        role = _message_type_name(message)
        if role:
            result.append(
                SessionMessageRecord(
                    index=len(result),
                    role=role,
                    text=_coerce_text_content(_message_content(message)),
                    raw=raw_payload,
                )
            )

    for index, message in enumerate(result):
        message.index = index

    return result


async def list_sessions(
    *,
    agent_name: str | None = None,
    page_size: int = _DEFAULT_SESSION_PAGE_SIZE,
    page_token: str = "",
    db_path: Path | None = None,
) -> SessionListPage:
    """List session summaries backed by latest checkpoint state."""
    resolved_page_size = _resolve_page_size(
        page_size,
        default=_DEFAULT_SESSION_PAGE_SIZE,
        maximum=_MAX_SESSION_PAGE_SIZE,
    )
    offset = 0
    if page_token:
        token_data = _decode_page_token(page_token)
        token_offset = token_data.get("offset", 0)
        if not isinstance(token_offset, int) or token_offset < 0:
            msg = "invalid page_token"
            raise ValueError(msg)
        offset = token_offset

    async with _connect(db_path) as conn:
        if not await _table_exists(conn, "checkpoints"):
            return SessionListPage(sessions=[])

        rows = await _list_session_rows(
            conn,
            agent_name=agent_name,
            limit=resolved_page_size + 1,
            offset=offset,
        )
        has_more = len(rows) > resolved_page_size
        rows = rows[:resolved_page_size]

        sessions: list[SessionSummaryRecord] = []
        for thread_id, resolved_agent_name, updated_at, latest_checkpoint_id in rows:
            _, message_count, initial_prompt = await _summarize_checkpoint_row(
                conn,
                thread_id=thread_id,
                checkpoint_id=latest_checkpoint_id,
            )
            sessions.append(
                SessionSummaryRecord(
                    thread_id=thread_id,
                    agent_name=resolved_agent_name,
                    updated_at=updated_at,
                    latest_checkpoint_id=latest_checkpoint_id,
                    message_count=message_count,
                    initial_prompt=initial_prompt,
                )
            )

        next_page_token = ""
        if has_more:
            next_page_token = _encode_page_token(
                {"offset": offset + resolved_page_size}
            )

        return SessionListPage(
            sessions=sessions,
            next_page_token=next_page_token,
        )


async def get_latest_session(
    *,
    agent_name: str | None = None,
    db_path: Path | None = None,
) -> SessionSummaryRecord | None:
    """Return the latest session summary, optionally filtered by agent."""
    page = await list_sessions(
        agent_name=agent_name,
        page_size=1,
        db_path=db_path,
    )
    return page.sessions[0] if page.sessions else None


async def get_session(
    thread_id: str,
    *,
    agent_name: str | None = None,
    db_path: Path | None = None,
) -> SessionDetailRecord | None:
    """Get one session summary plus checkpoint count."""
    async with _connect(db_path) as conn:
        if not await _table_exists(conn, "checkpoints"):
            return None

        agent_filter_sql, agent_params = _checkpoint_agent_filter(agent_name)
        query = f"""
            SELECT thread_id,
                   COALESCE(
                       json_extract(metadata, '$.agent_name'),
                       json_extract(metadata, '$.assistant_id')
                   ) AS agent_name,
                   json_extract(metadata, '$.updated_at') AS updated_at,
                   checkpoint_id AS latest_checkpoint_id
            FROM checkpoints
            WHERE thread_id = ?{agent_filter_sql}
            ORDER BY checkpoint_id DESC
            LIMIT 1
        """  # noqa: S608  # agent_filter_sql is selected from a fixed internal clause
        async with conn.execute(query, (thread_id, *agent_params)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None

        latest_checkpoint_id = str(row[3]) if row[3] is not None else None
        _, message_count, initial_prompt = await _summarize_checkpoint_row(
            conn,
            thread_id=thread_id,
            agent_name=agent_name,
            checkpoint_id=latest_checkpoint_id,
        )
        checkpoint_count = await _checkpoint_count(
            conn,
            thread_id=thread_id,
            agent_name=agent_name,
        )

        summary = SessionSummaryRecord(
            thread_id=str(row[0]),
            agent_name=row[1],
            updated_at=row[2],
            latest_checkpoint_id=latest_checkpoint_id,
            message_count=message_count,
            initial_prompt=initial_prompt,
        )
        return SessionDetailRecord(
            summary=summary,
            checkpoint_count=checkpoint_count,
        )


async def get_session_messages(
    thread_id: str,
    *,
    agent_name: str | None = None,
    checkpoint_id: str | None = None,
    page_size: int = _DEFAULT_MESSAGE_PAGE_SIZE,
    page_token: str = "",
    include_raw: bool = False,
    db_path: Path | None = None,
) -> SessionMessagesPage | None:
    """Get checkpoint-backed session messages for one thread."""
    resolved_page_size = _resolve_page_size(
        page_size,
        default=_DEFAULT_MESSAGE_PAGE_SIZE,
        maximum=_MAX_MESSAGE_PAGE_SIZE,
    )
    offset = 0
    token_checkpoint_id: str | None = None
    if page_token:
        token_data = _decode_page_token(page_token)
        token_offset = token_data.get("offset", 0)
        token_checkpoint_id_raw = token_data.get("checkpoint_id", "")
        if not isinstance(token_offset, int) or token_offset < 0:
            msg = "invalid page_token"
            raise ValueError(msg)
        if not isinstance(token_checkpoint_id_raw, str):
            msg = "invalid page_token"
            raise ValueError(msg)
        offset = token_offset
        token_checkpoint_id = token_checkpoint_id_raw or None

    if checkpoint_id and token_checkpoint_id and checkpoint_id != token_checkpoint_id:
        msg = "checkpoint_id does not match page_token"
        raise ValueError(msg)
    resolved_checkpoint_id = checkpoint_id or token_checkpoint_id

    async with _connect(db_path) as conn:
        if not await _table_exists(conn, "checkpoints"):
            return None

        row = await _load_checkpoint_row(
            conn,
            thread_id=thread_id,
            agent_name=agent_name,
            checkpoint_id=resolved_checkpoint_id,
        )
        if row is None:
            return None

        resolved_checkpoint_id, type_str, checkpoint_blob, _ = row
        serde = await _get_jsonplus_serializer()
        try:
            data = serde.loads_typed((type_str, checkpoint_blob))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            msg = f"failed to deserialize checkpoint for thread '{thread_id}'"
            raise RuntimeError(msg) from exc

        messages = _checkpoint_messages(data)
        normalized_messages = _normalize_session_messages(
            messages,
            include_raw=include_raw,
        )
        total_message_count = len(normalized_messages)
        paged_messages = normalized_messages[offset : offset + resolved_page_size]

        next_page_token = ""
        next_offset = offset + resolved_page_size
        if next_offset < total_message_count:
            next_page_token = _encode_page_token(
                {
                    "checkpoint_id": resolved_checkpoint_id,
                    "offset": next_offset,
                }
            )

        return SessionMessagesPage(
            thread_id=thread_id,
            resolved_checkpoint_id=resolved_checkpoint_id,
            actual_mode="resume_view",
            total_message_count=total_message_count,
            messages=paged_messages,
            next_page_token=next_page_token,
        )


async def get_thread_artifacts(
    thread_id: str,
    *,
    agent_name: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, str]] | None:
    """Read artifact entries from the latest checkpoint for one thread.

    Returns a list of artifact dicts (each with an ``id`` key) or ``None``
    if the thread/checkpoint cannot be found.
    """
    # resolved_db_path = db_path or default_db_path()

    async with _connect(db_path) as conn:
        row = await _load_checkpoint_row(
            conn,
            thread_id=thread_id,
            agent_name=agent_name,
        )
        if row is None:
            return None

        _, type_str, blob, _ = row
        serde = await _get_jsonplus_serializer()
        data = serde.loads_typed((type_str, blob))
        artifacts = _checkpoint_artifacts(data)
        return [{"id": k, **(v if isinstance(v, dict) else {})} for k, v in artifacts.items()]


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
    page = await list_sessions(
        agent_name=agent_name,
        page_size=limit,
        db_path=db_path,
    )
    threads: list[ThreadInfo] = []
    for session in page.sessions:
        info: ThreadInfo = {
            "thread_id": session.thread_id,
            "agent_name": session.agent_name,
            "updated_at": session.updated_at,
            "latest_checkpoint_id": session.latest_checkpoint_id,
        }
        if include_message_count:
            info["message_count"] = session.message_count
        threads.append(info)
    return threads


async def get_most_recent(
    agent_name: str | None = None,
    db_path: Path | None = None,
) -> str | None:
    """Get most recent thread_id."""
    session = await get_latest_session(agent_name=agent_name, db_path=db_path)
    return session.thread_id if session is not None else None


async def thread_exists(
    thread_id: str,
    *,
    agent_name: str | None = None,
    db_path: Path | None = None,
) -> bool:
    """Check if a thread exists in checkpoints."""
    async with _connect(db_path) as conn:
        if not await _table_exists(conn, "checkpoints"):
            return False

        agent_filter_sql, agent_params = _checkpoint_agent_filter(agent_name)
        async with conn.execute(
            f"SELECT 1 FROM checkpoints WHERE thread_id = ?{agent_filter_sql} LIMIT 1",  # noqa: S608  # agent_filter_sql is selected from a fixed internal clause
            (thread_id, *agent_params),
        ) as cursor:
            return await cursor.fetchone() is not None


async def delete_thread(
    thread_id: str,
    *,
    agent_name: str | None = None,
    db_path: Path | None = None,
) -> bool:
    """Delete thread checkpoints.

    Returns:
        True if the thread existed and was deleted.
    """
    async with _connect(db_path) as conn:
        if not await _table_exists(conn, "checkpoints"):
            return False

        agent_filter_sql, agent_params = _checkpoint_agent_filter(agent_name)
        cursor = await conn.execute(
            f"DELETE FROM checkpoints WHERE thread_id = ?{agent_filter_sql}",  # noqa: S608  # agent_filter_sql is selected from a fixed internal clause
            (thread_id, *agent_params),
        )
        deleted = cursor.rowcount > 0
        if deleted and await _table_exists(conn, "writes"):
            async with conn.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1",
                (thread_id,),
            ) as remaining_cursor:
                remaining = await remaining_cursor.fetchone() is not None
            if not remaining:
                await conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        await conn.commit()
        return deleted


async def get_thread_agent(
    thread_id: str, db_path: Path | None = None
) -> str | None:
    """Get agent_name for a thread from checkpoint metadata."""
    async with _connect(db_path) as conn:
        if not await _table_exists(conn, "checkpoints"):
            return None

        query = """
            SELECT COALESCE(
                json_extract(metadata, '$.agent_name'),
                json_extract(metadata, '$.assistant_id')
            )
            FROM checkpoints
            WHERE thread_id = ?
            ORDER BY checkpoint_id DESC
            LIMIT 1
        """
        async with conn.execute(query, (thread_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


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
