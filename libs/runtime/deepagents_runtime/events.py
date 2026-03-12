"""Shared runtime event primitives."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

EventPayload = dict[str, Any]
"""JSON-serializable payload object attached to a runtime event."""

SCHEMA_VERSION = 1
"""Current runtime event schema version."""


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """A client-neutral event emitted by the shared runtime.

    Attributes:
        type: Stable event type identifier, such as `run.started`.
        payload: Event-specific payload.
        run_id: Optional run identifier.
        thread_id: Optional thread identifier.
        event_id: Unique event identifier.
        timestamp: UTC timestamp when the event was created.
        schema_version: Version of the event envelope schema.
    """

    type: str
    payload: EventPayload = field(default_factory=dict)
    run_id: str | None = None
    thread_id: str | None = None
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex}")
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event to a JSON-friendly dict.

        Returns:
            JSON-serializable mapping for this event.
        """
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "timestamp": self.timestamp.isoformat(),
            "type": self.type,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        """Serialize the event to a compact JSON string.

        Returns:
            Compact JSON string representation of the event.
        """
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


def create_runtime_event(
    event_type: str,
    *,
    payload: EventPayload | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    event_id: str | None = None,
    timestamp: datetime | None = None,
) -> RuntimeEvent:
    """Create a `RuntimeEvent` with consistent defaults.

    Args:
        event_type: Stable event type identifier.
        payload: Optional event payload.
        run_id: Optional run identifier.
        thread_id: Optional thread identifier.
        event_id: Optional explicit event identifier.
        timestamp: Optional explicit UTC timestamp.

    Returns:
        A populated `RuntimeEvent` instance.
    """
    kwargs: dict[str, Any] = {
        "type": event_type,
        "payload": payload or {},
        "run_id": run_id,
        "thread_id": thread_id,
    }
    if event_id is not None:
        kwargs["event_id"] = event_id
    if timestamp is not None:
        kwargs["timestamp"] = timestamp
    return RuntimeEvent(**kwargs)
