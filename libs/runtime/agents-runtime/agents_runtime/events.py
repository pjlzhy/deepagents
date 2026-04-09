"""RuntimeEvent system.

Every interaction with a running agent produces a stream of RuntimeEvents.
Consumed by CLI (terminal rendering), Gateway (SSE), and tests.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from agents_runtime.spec import RuntimeEventType

_UNSET = object()


@dataclass(frozen=True)
class RuntimeEvent:
    """Immutable event emitted during agent execution."""

    type: RuntimeEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    run_id: str = ""
    agent_name: str = ""

    def to_json(self) -> str:
        """Serialize to JSON string for transport."""
        return json.dumps(asdict(self), default=str)

    def to_sse(self) -> str:
        """Format as a Server-Sent Event line."""
        return f"event: {self.type.value}\ndata: {self.to_json()}\n\n"

    @classmethod
    def from_json(cls, raw: str) -> RuntimeEvent:
        """Deserialize from JSON string."""
        obj = json.loads(raw)
        obj["type"] = RuntimeEventType(obj["type"])
        return cls(**obj)


# ── Convenience Constructors ──


def text_delta(text: str, *, run_id: str = "", agent_name: str = "") -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.TEXT_DELTA,
        data={"text": text},
        run_id=run_id,
        agent_name=agent_name,
    )


def text_done(
    full_text: str, *, run_id: str = "", agent_name: str = ""
) -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.TEXT_DONE,
        data={"text": full_text},
        run_id=run_id,
        agent_name=agent_name,
    )


def tool_call_start(
    tool_name: str,
    tool_call_id: str,
    args: dict[str, Any] | None = None,
    *,
    run_id: str = "",
    agent_name: str = "",
) -> RuntimeEvent:
    data: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
    }
    if args is not None:
        data["args"] = args
    return RuntimeEvent(
        type=RuntimeEventType.TOOL_CALL_START,
        data=data,
        run_id=run_id,
        agent_name=agent_name,
    )


def tool_call_done(
    tool_name: str,
    tool_call_id: str,
    *,
    run_id: str = "",
    agent_name: str = "",
) -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.TOOL_CALL_DONE,
        data={"tool_name": tool_name, "tool_call_id": tool_call_id},
        run_id=run_id,
        agent_name=agent_name,
    )


def tool_result(
    tool_call_id: str,
    content: str,
    *,
    payload: Any = _UNSET,
    is_error: bool = False,
    run_id: str = "",
    agent_name: str = "",
) -> RuntimeEvent:
    data: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "content": content,
        "is_error": is_error,
    }
    if payload is not _UNSET:
        data["payload"] = payload
    return RuntimeEvent(
        type=RuntimeEventType.TOOL_RESULT,
        data=data,
        run_id=run_id,
        agent_name=agent_name,
    )


def hitl_request(
    interrupt_id: str,
    action_requests: list[dict[str, Any]],
    *,
    review_configs: list[dict[str, Any]] | None = None,
    run_id: str = "",
    agent_name: str = "",
) -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.HITL_REQUEST,
        data={
            "interrupt_id": interrupt_id,
            "action_requests": action_requests,
            "review_configs": review_configs or [],
        },
        run_id=run_id,
        agent_name=agent_name,
    )


def run_start(*, run_id: str, agent_name: str, thread_id: str = "") -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.RUN_START,
        data={"thread_id": thread_id},
        run_id=run_id,
        agent_name=agent_name,
    )


def run_end(
    *,
    run_id: str,
    agent_name: str,
    stats: dict[str, Any] | None = None,
    start_checkpoint_id: str = "",
    end_checkpoint_id: str = "",
) -> RuntimeEvent:
    data: dict[str, Any] = {"stats": stats or {}}
    if start_checkpoint_id:
        data["start_checkpoint_id"] = start_checkpoint_id
    if end_checkpoint_id:
        data["end_checkpoint_id"] = end_checkpoint_id
    return RuntimeEvent(
        type=RuntimeEventType.RUN_END,
        data=data,
        run_id=run_id,
        agent_name=agent_name,
    )


def run_canceled(
    reason: str,
    *,
    run_id: str = "",
    agent_name: str = "",
) -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.RUN_CANCELED,
        data={"reason": reason},
        run_id=run_id,
        agent_name=agent_name,
    )


def error_event(
    message: str,
    *,
    run_id: str = "",
    agent_name: str = "",
    error_type: str = "",
) -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.ERROR,
        data={"message": message, "error_type": error_type},
        run_id=run_id,
        agent_name=agent_name,
    )
