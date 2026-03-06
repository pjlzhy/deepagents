"""Thread state storage for the Deep Agents HTTP server."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Callable

from deepagents_server.config import RuntimeDefaults


def utc_now() -> datetime:
    """Return the current UTC time.

    Returns:
        Current UTC timestamp.
    """
    return datetime.now(UTC)


def format_timestamp(value: datetime) -> str:
    """Format a UTC timestamp for API responses.

    Args:
        value: Datetime to format.

    Returns:
        ISO 8601 string with a `Z` UTC suffix.
    """
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ThreadRecord:
    """Persisted thread metadata stored by the server.

    Args:
        thread_id: Stable thread identifier.
        assistant_id: Default assistant identifier for the thread.
        model: Optional default model for the thread.
        created_at: Creation timestamp in ISO 8601 format.
        updated_at: Last mutation timestamp in ISO 8601 format.
        run_count: Number of successful runs recorded on the thread.
        last_run_id: Most recent run identifier recorded on the thread.
        runtime_defaults: Default runtime context reused by future runs.
    """

    thread_id: str
    assistant_id: str
    model: str | None
    created_at: str
    updated_at: str
    run_count: int = 0
    last_run_id: str | None = None
    runtime_defaults: RuntimeDefaults = field(default_factory=RuntimeDefaults, repr=False)

    def to_payload(self) -> dict[str, object]:
        """Serialize the thread record into an API payload.

        Returns:
            JSON-serializable thread payload.
        """
        return {
            "assistant_id": self.assistant_id,
            "thread_id": self.thread_id,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_count": self.run_count,
        }


class InMemoryThreadStore:
    """Thread-safe in-memory thread store for the MVP server."""

    def __init__(
        self,
        *,
        generate_thread_id: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
        default_runtime_defaults: RuntimeDefaults | None = None,
    ) -> None:
        """Create the in-memory thread store.

        Args:
            generate_thread_id: Optional thread ID generator for tests.
            now: Optional clock override for deterministic timestamps.
            default_runtime_defaults: Default session context for new threads.
        """
        self._generate_thread_id = generate_thread_id or self._default_thread_id
        self._now = now or utc_now
        self._default_runtime_defaults = default_runtime_defaults or RuntimeDefaults()
        self._records: dict[str, ThreadRecord] = {}
        self._lock = Lock()

    def create_thread(
        self,
        *,
        assistant_id: str,
        model: str | None,
        runtime_defaults: RuntimeDefaults | None = None,
    ) -> ThreadRecord:
        """Create and persist a new thread.

        Args:
            assistant_id: Assistant identifier bound to the thread.
            model: Optional default model for the thread.
            runtime_defaults: Optional runtime defaults to store on the thread.

        Returns:
            Newly created thread record.
        """
        timestamp = format_timestamp(self._now())
        record = ThreadRecord(
            thread_id=self._generate_thread_id(),
            assistant_id=assistant_id,
            model=model,
            created_at=timestamp,
            updated_at=timestamp,
            runtime_defaults=runtime_defaults or self._default_runtime_defaults,
        )
        with self._lock:
            self._records[record.thread_id] = record
        return record

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """Load a thread by identifier.

        Args:
            thread_id: Thread identifier to retrieve.

        Returns:
            Stored thread record, if present.
        """
        with self._lock:
            return self._records.get(thread_id)

    def record_run(
        self,
        thread_id: str,
        *,
        assistant_id: str,
        model: str | None,
        run_id: str | None = None,
    ) -> ThreadRecord | None:
        """Update a thread after a successful run.

        Args:
            thread_id: Thread identifier to update.
            assistant_id: Effective assistant used for the run.
            model: Effective model used for the run.
            run_id: Optional run identifier to persist on the thread.

        Returns:
            Updated thread record, if the thread exists.
        """
        with self._lock:
            existing = self._records.get(thread_id)
            if existing is None:
                return None
            updated = replace(
                existing,
                assistant_id=assistant_id,
                model=model,
                updated_at=format_timestamp(self._now()),
                run_count=existing.run_count + 1,
                last_run_id=run_id,
            )
            self._records[thread_id] = updated
            return updated

    def _default_thread_id(self) -> str:
        return f"thread_{uuid4().hex}"
