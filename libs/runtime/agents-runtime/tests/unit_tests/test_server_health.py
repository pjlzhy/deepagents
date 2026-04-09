"""Unit tests for runtime server health reporting."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import time

import pytest

from agents_runtime.entry.server import ResourceSyncServicer
from agents_runtime.generated import runtime_pb2 as pb2
from agents_runtime.spec import AgentMeta, AgentStatus


class _FakeManager:
    """Minimal manager stub for health tests."""

    def __init__(self, *, agents: list[AgentMeta] | None = None, fail: bool = False) -> None:
        self._agents = agents or []
        self._fail = fail

    async def list_agents(self) -> list[AgentMeta]:
        if self._fail:
            raise RuntimeError("boom")
        return self._agents


def test_health_reports_real_uptime_and_compiled_agent_count() -> None:
    """Health should return elapsed uptime and count compiled/running agents."""

    manager = _FakeManager(
        agents=[
            AgentMeta("installed", "1.0.0", "", [], AgentStatus.INSTALLED),
            AgentMeta("compiled", "1.0.0", "", [], AgentStatus.COMPILED),
            AgentMeta(
                "running",
                "1.0.0",
                "",
                [],
                AgentStatus.RUNNING,
                active_thread_count=2,
                active_thread_ids=["thread-1", "thread-2"],
                last_invoked_at=datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC),
            ),
        ]
    )

    servicer = ResourceSyncServicer(manager)
    servicer._started_at = time.monotonic() - 12.5
    response = asyncio.run(servicer.Health(pb2.HealthRequest(), None))

    assert response.status == "ok"
    assert response.ready is True
    assert response.installed_agent_count == 3
    assert response.assembled_agent_count == 2
    assert response.running_agent_count == 1
    assert response.running_thread_count == 2
    assert response.uptime_seconds == pytest.approx(12.5, rel=0.1)
    assert len(response.agents) == 3
    assert response.agents[2].name == "running"
    assert response.agents[2].active_thread_count == 2
    assert list(response.agents[2].active_thread_ids) == ["thread-1", "thread-2"]
    assert response.agents[2].last_invoked_at.seconds == int(
        datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC).timestamp()
    )


def test_health_returns_degraded_when_no_agent_is_compiled() -> None:
    """Health should report degraded readiness when nothing can execute yet."""

    manager = _FakeManager(
        agents=[
            AgentMeta("installed", "1.0.0", "", [], AgentStatus.INSTALLED),
        ]
    )

    response = asyncio.run(ResourceSyncServicer(manager).Health(pb2.HealthRequest(), None))

    assert response.status == "degraded"
    assert response.ready is False
    assert response.installed_agent_count == 1
    assert response.assembled_agent_count == 0
    assert response.running_agent_count == 0
    assert response.running_thread_count == 0
    assert len(response.agents) == 1


def test_health_returns_unhealthy_on_manager_failure() -> None:
    """Health should degrade cleanly when agent status lookup fails."""

    servicer = ResourceSyncServicer(_FakeManager(fail=True))
    response = asyncio.run(servicer.Health(pb2.HealthRequest(), None))

    assert response.status == "unhealthy"
    assert response.ready is False
    assert response.installed_agent_count == 0
    assert response.assembled_agent_count == 0
    assert response.running_agent_count == 0
    assert response.running_thread_count == 0
    assert len(response.agents) == 0
    assert response.uptime_seconds == 0.0
