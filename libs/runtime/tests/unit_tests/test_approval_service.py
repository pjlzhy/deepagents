from __future__ import annotations

import asyncio

from deepagents_runtime.approval_service import ApprovalService
from deepagents_runtime.streams import validate_hitl_request


def _make_hitl_request(*, action_count: int = 1) -> object:
    return validate_hitl_request(
        {
            "action_requests": [
                {
                    "name": "execute",
                    "args": {"command": f"echo {i}"},
                    "description": "Run command",
                }
                for i in range(action_count)
            ],
            "review_configs": [
                {
                    "action_name": "execute",
                    "allowed_decisions": ["approve", "reject"],
                }
            ],
        }
    )


def test_approval_service_resolves_pending_approvals() -> None:
    async def _run() -> None:
        service = ApprovalService()
        resolver = service.create_resolver(
            run_id="run-1",
            thread_id="thread-1",
        )

        async def _await_resolution() -> object:
            return await resolver({"interrupt-1": _make_hitl_request(action_count=2)})

        task = asyncio.create_task(_await_resolution())

        pending = None
        for _ in range(10):
            pending = await service.get_pending("run-1")
            if pending is not None:
                break
            await asyncio.sleep(0)

        assert pending is not None
        assert pending.run_id == "run-1"
        assert pending.thread_id == "thread-1"
        assert pending.interrupt_ids == ("interrupt-1",)
        assert (
            pending.interrupts["interrupt-1"]["action_requests"][0]["name"]
            == "execute"
        )

        resolved = await service.resolve_run("run-1", "approve")
        assert resolved is True

        result = await task
        assert result == {
            "interrupt-1": {"decisions": [{"type": "approve"}, {"type": "approve"}]}
        }
        assert await service.get_pending("run-1") is None

    asyncio.run(_run())


def test_approval_service_reject_cancels_run() -> None:
    async def _run() -> None:
        service = ApprovalService()
        resolver = service.create_resolver(run_id="run-1", thread_id="thread-1")

        async def _await_resolution() -> object:
            return await resolver({"interrupt-1": _make_hitl_request()})

        task = asyncio.create_task(_await_resolution())

        for _ in range(10):
            if await service.get_pending("run-1") is not None:
                break
            await asyncio.sleep(0)

        assert await service.resolve_run("run-1", "reject") is True
        assert await task == {}

    asyncio.run(_run())


def test_approval_service_auto_approve_all_persists_on_thread() -> None:
    async def _run() -> None:
        service = ApprovalService()
        resolver = service.create_resolver(run_id="run-1", thread_id="thread-1")

        async def _await_resolution() -> object:
            return await resolver({"interrupt-1": _make_hitl_request()})

        task = asyncio.create_task(_await_resolution())

        for _ in range(10):
            if await service.get_pending("run-1") is not None:
                break
            await asyncio.sleep(0)

        assert await service.get_thread_auto_approve("thread-1") is False
        assert await service.resolve_run("run-1", "auto_approve_all") is True

        assert await task == {"interrupt-1": {"decisions": [{"type": "approve"}]}}
        assert await service.get_thread_auto_approve("thread-1") is True

        run_2_resolver = service.create_resolver(
            run_id="run-2",
            thread_id="thread-1",
        )
        run_2_result = await run_2_resolver({"interrupt-2": _make_hitl_request()})
        assert run_2_result == {"interrupt-2": {"decisions": [{"type": "approve"}]}}
        assert await service.get_pending("run-2") is None

    asyncio.run(_run())
