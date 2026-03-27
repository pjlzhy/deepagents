"""Data Plane gRPC server.

Implements three gRPC services defined in runtime.proto:
  - AgentExecutor:  bidirectional streaming for agent execution + HITL
  - ResourceSync:   unary RPCs for pushing resources from control plane
  - SessionQuery:   unary RPCs for runtime session inspection

This is the data plane's only external interface. The control plane
connects here to sync resources, assemble agents, invoke runs, and query
runtime sessions.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import grpc
from google.protobuf.json_format import MessageToDict
from google.protobuf import struct_pb2, timestamp_pb2
from grpc import aio as grpc_aio

from deepagents_runtime.converters import (
    runtime_event_to_agent_event,
    sync_agent_spec_request_to_agent_spec,
)
from deepagents_runtime.generated import runtime_pb2 as pb2
from deepagents_runtime.generated import runtime_pb2_grpc
from deepagents_runtime.manager.manager import AgentManager
from deepagents_runtime.sessions import (
    delete_thread,
    generate_thread_id,
    get_latest_session,
    get_session,
    get_session_messages,
    list_sessions,
)
from deepagents_runtime.spec import AgentStatus, RunConfig

logger = logging.getLogger(__name__)

# Default timeout for HITL decisions (seconds).
_HITL_DECISION_TIMEOUT = 300.0
_INVALID_HITL_DECISION_ERROR = "invalid_hitl_decision"


class _InvalidHITLDecisionError(RuntimeError):
    """Raised when the client sends an invalid HITL decision message."""


@dataclass(slots=True)
class _PendingHITLInterrupt:
    """One pending HITL interrupt awaiting a client decision."""

    expected_decision_count: int
    future: asyncio.Future[pb2.HITLDecision]


class _HITLDecisionCoordinator:
    """Run-scoped coordinator for pending HITL interrupts and decisions."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, _PendingHITLInterrupt] = {}
        self._closed: set[str] = set()
        self._transport_error: asyncio.Future[_InvalidHITLDecisionError] = (
            asyncio.get_running_loop().create_future()
        )

    @property
    def transport_error(self) -> asyncio.Future[_InvalidHITLDecisionError]:
        """Return the run-scoped transport error future."""
        return self._transport_error

    async def wait_for_decision(self, request: dict[str, Any]) -> pb2.HITLDecision:
        """Register one interrupt and await its matching HITL decision."""

        interrupt_id = str(request.get("interrupt_id", "")).strip()
        action_requests = request.get("action_requests", [])
        expected_decision_count = (
            len(action_requests) if isinstance(action_requests, list) else 0
        )
        decision_future = await self._register_interrupt(
            interrupt_id=interrupt_id,
            expected_decision_count=expected_decision_count,
        )
        try:
            return await asyncio.wait_for(
                decision_future,
                timeout=_HITL_DECISION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            await self._close_interrupt(interrupt_id)
            msg = f"HITL decision timed out after {_HITL_DECISION_TIMEOUT:.0f}s"
            raise TimeoutError(msg) from None

    async def submit(self, decision: pb2.HITLDecision) -> None:
        """Validate and route one client HITL decision."""

        interrupt_id = decision.interrupt_id.strip()
        if not interrupt_id:
            await self._set_transport_error("interrupt_id must not be empty")
            return

        future: asyncio.Future[pb2.HITLDecision] | None = None
        message = ""
        async with self._lock:
            pending = self._pending.get(interrupt_id)
            if pending is None:
                if interrupt_id in self._closed:
                    message = f"interrupt_id {interrupt_id} is no longer pending"
                else:
                    message = f"unknown interrupt_id: {interrupt_id}"
            elif len(decision.decisions) != pending.expected_decision_count:
                message = (
                    f"decision count mismatch for interrupt {interrupt_id}: "
                    f"expected {pending.expected_decision_count}, "
                    f"got {len(decision.decisions)}"
                )
            else:
                self._pending.pop(interrupt_id)
                self._closed.add(interrupt_id)
                future = pending.future

        if message:
            await self._set_transport_error(message)
            return
        if future is not None and not future.done():
            future.set_result(decision)

    async def _register_interrupt(
        self,
        *,
        interrupt_id: str,
        expected_decision_count: int,
    ) -> asyncio.Future[pb2.HITLDecision]:
        """Register one pending interrupt before waiting for a decision."""

        if not interrupt_id:
            msg = "runtime emitted HITL request with empty interrupt_id"
            raise RuntimeError(msg)

        future: asyncio.Future[pb2.HITLDecision] = (
            asyncio.get_running_loop().create_future()
        )
        async with self._lock:
            if interrupt_id in self._pending or interrupt_id in self._closed:
                msg = f"interrupt_id {interrupt_id} is already registered"
                raise RuntimeError(msg)
            self._pending[interrupt_id] = _PendingHITLInterrupt(
                expected_decision_count=expected_decision_count,
                future=future,
            )
        return future

    async def _close_interrupt(self, interrupt_id: str) -> None:
        """Mark one pending interrupt as closed after timeout/cancellation."""

        async with self._lock:
            pending = self._pending.pop(interrupt_id, None)
            if pending is not None:
                self._closed.add(interrupt_id)
        if pending is not None and not pending.future.done():
            pending.future.cancel()

    async def _set_transport_error(self, message: str) -> None:
        """Store the first transport error seen in the current run."""

        async with self._lock:
            if self._transport_error.done():
                return
            self._transport_error.set_result(_InvalidHITLDecisionError(message))


def _translate_hitl_decisions(decision: pb2.HITLDecision) -> list[dict[str, Any]]:
    """Translate transport HITL decisions into LangChain HITL decision objects."""

    decisions: list[dict[str, Any]] = []
    for item in decision.decisions:
        decision_type = item.type.strip().lower()
        if decision_type == "approve":
            decisions.append({"type": "approve"})
            continue

        if decision_type == "reject":
            reject_decision: dict[str, Any] = {"type": "reject"}
            if item.message:
                reject_decision["message"] = item.message
            decisions.append(reject_decision)
            continue

        if decision_type == "edit":
            if not item.HasField("edited_action"):
                msg = "edit decision must include edited_action"
                raise _InvalidHITLDecisionError(msg)
            edited_name = item.edited_action.name.strip()
            if not edited_name:
                msg = "edited_action.name must not be empty"
                raise _InvalidHITLDecisionError(msg)
            decisions.append({
                "type": "edit",
                "edited_action": {
                    "name": edited_name,
                    "args": (
                        MessageToDict(item.edited_action.args)
                        if item.edited_action.HasField("args")
                        else {}
                    ),
                },
            })
            continue

        msg = f"unsupported decision.type: {item.type!r}"
        raise _InvalidHITLDecisionError(msg)
    return decisions


class AgentExecutorServicer(runtime_pb2_grpc.AgentExecutorServicer):
    """Implements the AgentExecutor gRPC service.

    ``Run()`` is a bidirectional streaming RPC:
      - Client sends: ClientMessage (oneof: RunRequest | HITLDecision | CancelRequest)
      - Server yields: AgentEvent stream with a terminal RunEnded / RunCanceled / ErrorOccurred
    """

    def __init__(self, manager: AgentManager) -> None:
        super().__init__()
        self._manager = manager

    async def Run(
        self,
        request_iterator: grpc_aio.StreamStreamCall,
        context: grpc.aio.ServicerContext,
    ):
        """Handle a bidirectional streaming Run RPC.

        Protocol:
          1. Read first ClientMessage → must contain a RunRequest
          2. Create HITL handler bridging agent loop ↔ client stream
          3. Run the agent loop, yielding AgentEvent protos
          4. On CancelRequest, abort the run
        """
        # ── 1. Read RunRequest ──
        try:
            first_msg: pb2.ClientMessage = await context.read()
        except grpc_aio.AioRpcError:
            yield _error_event("", "", "Empty stream: no RunRequest received")
            return

        if not first_msg or not first_msg.HasField("run_request"):
            yield _error_event("", "", "First message must be a RunRequest")
            return

        run_request = first_msg.run_request
        agent_name = run_request.agent_name
        message = run_request.message
        thread_id = run_request.thread_id or generate_thread_id()
        run_id = uuid.uuid4().hex[:12]
        timeout_seconds = _resolve_run_timeout_seconds(run_request, context)

        logger.info(
            "Run started: agent=%s run=%s thread=%s",
            agent_name, run_id, thread_id,
        )

        # ── 2. Build HITL handler ──
        # The runtime execution path emits HITL_REQUEST events and then calls
        # this handler. The handler simply waits for the client to send a
        # HITLDecision message via the bidirectional stream.
        hitl_coordinator = _HITLDecisionCoordinator()
        cancel_event = asyncio.Event()
        cancel_reason = "Run canceled by client"
        event_queue: asyncio.Queue[pb2.AgentEvent | None] = asyncio.Queue()

        async def hitl_handler(request: dict[str, Any]) -> list[dict[str, Any]]:
            """HITL callback: await client decision (event already emitted)."""
            decision = await hitl_coordinator.wait_for_decision(request)
            return _translate_hitl_decisions(decision)

        # ── 3. Background: read client messages ──
        async def read_client_messages() -> None:
            """Read HITLDecision and CancelRequest from client stream."""
            nonlocal cancel_reason
            try:
                async for msg in request_iterator:
                    msg: pb2.ClientMessage
                    if msg.HasField("hitl_decision"):
                        await hitl_coordinator.submit(msg.hitl_decision)
                        if hitl_coordinator.transport_error.done():
                            return
                    elif msg.HasField("cancel"):
                        cancel_reason = msg.cancel.reason or "Run canceled by client"
                        cancel_event.set()
                        logger.info("Cancel requested for run %s", run_id)
                        break
            except Exception:
                logger.debug("Client stream closed for run %s", run_id)

        async def produce_run_events() -> None:
            """Bridge manager runtime events onto a server-scoped queue."""
            try:
                async for event in self._manager.invoke(
                    name=agent_name,
                    run_config=RunConfig(
                        input=message,
                        thread_id=thread_id,
                        run_id=run_id,
                        timeout_seconds=timeout_seconds,
                    ),
                    hitl_handler=hitl_handler,
                    cancel_event=cancel_event,
                    cancel_reason=cancel_reason,
                    cancel_reason_getter=lambda: cancel_reason,
                ):
                    await event_queue.put(runtime_event_to_agent_event(event))
            except KeyError as e:
                await event_queue.put(_error_event(run_id, agent_name, str(e), "not_found"))
            except _InvalidHITLDecisionError as e:
                await hitl_coordinator._set_transport_error(str(e))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("Error in Run for agent %s", agent_name)
                await event_queue.put(_error_event(run_id, agent_name, str(e)))
            finally:
                await event_queue.put(None)

        reader_task = asyncio.create_task(read_client_messages())
        producer_task = asyncio.create_task(produce_run_events())

        # ── 4. Drain run events and transport errors ──
        try:
            while True:
                source, payload = await _wait_for_run_signal(
                    event_queue=event_queue,
                    transport_error=hitl_coordinator.transport_error,
                )
                if source == "transport_error":
                    await _cancel_background_task(producer_task)
                    yield _error_event(
                        run_id,
                        agent_name,
                        str(payload),
                        _INVALID_HITL_DECISION_ERROR,
                    )
                    return
                if payload is None:
                    return
                yield payload
        finally:
            await _cancel_background_task(reader_task)
            await _cancel_background_task(producer_task)


class ResourceSyncServicer(runtime_pb2_grpc.ResourceSyncServicer):
    """Implements the ResourceSync gRPC service.

    Unary RPCs for pushing resources from control plane to data plane:
      - SyncSkill, SyncMcp, SyncAgentSpec
      - Assemble
      - RemoveResource
      - Health
    """

    def __init__(self, manager: AgentManager) -> None:
        super().__init__()
        self._manager = manager
        self._started_at = time.monotonic()

    async def SyncSkill(
        self,
        request: pb2.SyncSkillRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.SyncResponse:
        """Push a skill to the local registry.

        Note: Skills are now embedded in agent specs and loaded from the
        file system.  This RPC is kept for backward compatibility but is
        effectively a no-op.
        """
        return pb2.SyncResponse(
            ok=True,
            message=(
                f"Skill '{request.name}' acknowledged "
                "(skills are now managed via AgentSpec)"
            ),
        )

    async def SyncMcp(
        self,
        request: pb2.SyncMcpRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.SyncResponse:
        """Push an MCP config to the local registry.

        Note: MCP configs are now embedded in agent specs.  This RPC is
        kept for backward compatibility but is effectively a no-op.
        """
        return pb2.SyncResponse(
            ok=True,
            message=(
                f"MCP '{request.name}' acknowledged "
                "(MCP configs are now managed via AgentSpec)"
            ),
        )

    async def SyncAgentSpec(
        self,
        request: pb2.SyncAgentSpecRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.SyncResponse:
        """Install an agent spec into the local runtime registry."""
        try:
            spec = sync_agent_spec_request_to_agent_spec(request)
            await self._manager.define_agent(spec)
            return pb2.SyncResponse(ok=True, message=f"AgentSpec '{spec.name}' installed")
        except Exception as e:
            logger.exception("SyncAgentSpec failed")
            return pb2.SyncResponse(ok=False, message=str(e))

    async def Assemble(
        self,
        request: pb2.AssembleRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.AssembleResponse:
        """Compile an installed agent into runnable runtime resources."""
        agent_name = request.agent_name
        try:
            await self._manager.assemble_agent(agent_name)
            return pb2.AssembleResponse(
                ok=True,
                message=f"Agent '{agent_name}' compiled",
                status="compiled",
            )
        except KeyError as e:
            return pb2.AssembleResponse(
                ok=False, message=str(e), status="not_found"
            )
        except ValueError as e:
            return pb2.AssembleResponse(
                ok=False, message=str(e), status="error"
            )
        except Exception as e:
            logger.exception("Assemble failed for %s", agent_name)
            return pb2.AssembleResponse(
                ok=False, message=str(e), status="error"
            )

    async def RemoveResource(
        self,
        request: pb2.RemoveResourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.SyncResponse:
        """Uninstall a synced resource from the local runtime registry."""
        resource_type = request.resource_type
        name = request.name

        try:
            if resource_type in {"agent", "agent_spec"}:
                ok = await self._manager.remove_agent(name)
            else:
                return pb2.SyncResponse(
                    ok=False,
                    message=(
                        f"Resource type '{resource_type}' is not supported. "
                        "Only 'agent' and 'agent_spec' are supported."
                    ),
                )
            msg = f"Agent '{name}' uninstalled" if ok else "Not found"
            return pb2.SyncResponse(ok=ok, message=msg)
        except RuntimeError as e:
            return pb2.SyncResponse(ok=False, message=str(e))
        except Exception as e:
            logger.exception("RemoveResource failed")
            return pb2.SyncResponse(ok=False, message=str(e))

    async def Health(
        self,
        request: pb2.HealthRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.HealthResponse:
        """Health check / readiness probe."""
        try:
            agents = await self._manager.list_agents()
            installed_count = len(agents)
            assembled_count = sum(
                1 for a in agents
                if a.status in (AgentStatus.COMPILED, AgentStatus.RUNNING)
            )
            running_count = sum(1 for a in agents if a.status == AgentStatus.RUNNING)
            ready = assembled_count > 0
            return pb2.HealthResponse(
                status="ok" if ready else "degraded",
                assembled_agent_count=assembled_count,
                uptime_seconds=max(0.0, time.monotonic() - self._started_at),
                installed_agent_count=installed_count,
                running_agent_count=running_count,
                ready=ready,
            )
        except Exception:
            return pb2.HealthResponse(
                status="unhealthy",
                assembled_agent_count=0,
                uptime_seconds=0.0,
                installed_agent_count=0,
                running_agent_count=0,
                ready=False,
            )


class SessionQueryServicer(runtime_pb2_grpc.SessionQueryServicer):
    """Implements checkpoint-backed session query RPCs."""

    def __init__(
        self,
        manager: AgentManager | None = None,
        *,
        db_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._manager = manager
        self._db_path = db_path

    async def _agent_status_map(self) -> dict[str, AgentStatus]:
        """Best-effort snapshot of installed agent runtime states."""
        if self._manager is None:
            return {}
        try:
            agents = await self._manager.list_agents()
        except Exception:
            logger.warning("Failed to load agent runtime status overlay", exc_info=True)
            return {}
        return {agent.name: agent.status for agent in agents}

    async def ListSessions(
        self,
        request: pb2.ListSessionsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.ListSessionsResponse:
        """List recent sessions derived from checkpoint storage."""
        try:
            page = await list_sessions(
                agent_name=request.agent_name or None,
                page_size=request.page_size,
                page_token=request.page_token,
                db_path=self._db_path,
            )
        except ValueError as exc:
            await _abort_invalid_argument(context, str(exc))
            return pb2.ListSessionsResponse()

        agent_statuses = await self._agent_status_map()
        return pb2.ListSessionsResponse(
            sessions=[
                _session_summary_to_proto(
                    session,
                    agent_status=_resolve_session_agent_status(
                        session.agent_name,
                        agent_statuses,
                    ),
                )
                for session in page.sessions
            ],
            next_page_token=page.next_page_token,
        )

    async def GetSession(
        self,
        request: pb2.GetSessionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.GetSessionResponse:
        """Return one session summary and checkpoint count."""
        thread_id = request.thread_id.strip()
        if not thread_id:
            await _abort_invalid_argument(context, "thread_id is required")
            return pb2.GetSessionResponse(found=False)

        session = await get_session(thread_id, db_path=self._db_path)
        if session is None:
            return pb2.GetSessionResponse(found=False)

        agent_statuses = await self._agent_status_map()
        return pb2.GetSessionResponse(
            found=True,
            session=pb2.SessionDetail(
                summary=_session_summary_to_proto(
                    session.summary,
                    agent_status=_resolve_session_agent_status(
                        session.summary.agent_name,
                        agent_statuses,
                    ),
                ),
                checkpoint_count=session.checkpoint_count,
            ),
        )

    async def GetSessionMessages(
        self,
        request: pb2.GetSessionMessagesRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.GetSessionMessagesResponse:
        """Return checkpoint-backed message history for one thread."""
        thread_id = request.thread_id.strip()
        if not thread_id:
            await _abort_invalid_argument(context, "thread_id is required")
            return pb2.GetSessionMessagesResponse()

        try:
            page = await get_session_messages(
                thread_id,
                checkpoint_id=request.checkpoint_id or None,
                page_size=request.page_size,
                page_token=request.page_token,
                include_raw=request.include_raw,
                db_path=self._db_path,
            )
        except ValueError as exc:
            await _abort_invalid_argument(context, str(exc))
            return pb2.GetSessionMessagesResponse()
        except RuntimeError as exc:
            await _abort_internal(context, str(exc))
            return pb2.GetSessionMessagesResponse()

        if page is None:
            await _abort_not_found(
                context,
                f"Session '{thread_id}' not found",
            )
            return pb2.GetSessionMessagesResponse()

        return pb2.GetSessionMessagesResponse(
            thread_id=page.thread_id,
            resolved_checkpoint_id=page.resolved_checkpoint_id,
            actual_mode=_session_history_mode_to_proto(page.actual_mode),
            total_message_count=page.total_message_count,
            messages=[
                _session_message_to_proto(message) for message in page.messages
            ],
            next_page_token=page.next_page_token,
        )

    async def GetLatestSession(
        self,
        request: pb2.GetLatestSessionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.GetLatestSessionResponse:
        """Resolve the latest session, optionally filtered by agent."""
        session = await get_latest_session(
            agent_name=request.agent_name or None,
            db_path=self._db_path,
        )
        if session is None:
            return pb2.GetLatestSessionResponse(found=False)

        agent_statuses = await self._agent_status_map()
        return pb2.GetLatestSessionResponse(
            found=True,
            session=_session_summary_to_proto(
                session,
                agent_status=_resolve_session_agent_status(
                    session.agent_name,
                    agent_statuses,
                ),
            ),
        )

    async def DeleteSession(
        self,
        request: pb2.DeleteSessionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.DeleteSessionResponse:
        """Delete one session from local checkpoint storage."""
        thread_id = request.thread_id.strip()
        if not thread_id:
            await _abort_invalid_argument(context, "thread_id is required")
            return pb2.DeleteSessionResponse(deleted=False)

        deleted = await delete_thread(thread_id, db_path=self._db_path)
        return pb2.DeleteSessionResponse(deleted=deleted)


def _resolve_run_timeout_seconds(
    run_request: pb2.RunRequest,
    context: grpc.aio.ServicerContext,
) -> float | None:
    """Resolve the effective run timeout from metadata and gRPC deadline."""
    timeout_seconds: float | None = None

    raw_timeout = run_request.metadata.get("timeout_seconds", "").strip()
    if raw_timeout:
        timeout_seconds = float(raw_timeout)
        if timeout_seconds < 0:
            msg = "RunRequest metadata timeout_seconds cannot be negative"
            raise ValueError(msg)

    remaining = context.time_remaining()
    if remaining is None:
        return timeout_seconds
    remaining = max(0.0, remaining)
    if timeout_seconds is None:
        return remaining
    return min(timeout_seconds, remaining)


async def _wait_for_run_signal(
    *,
    event_queue: asyncio.Queue[pb2.AgentEvent | None],
    transport_error: asyncio.Future[_InvalidHITLDecisionError],
) -> tuple[str, pb2.AgentEvent | _InvalidHITLDecisionError | None]:
    """Wait for the next runtime event or a transport-layer HITL failure."""

    if not event_queue.empty():
        return "event", event_queue.get_nowait()
    if transport_error.done():
        return "transport_error", transport_error.result()

    queue_task = asyncio.create_task(event_queue.get())
    done, pending = await asyncio.wait(
        {queue_task, transport_error},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if queue_task in done:
        for waiter in pending:
            if isinstance(waiter, asyncio.Task):
                waiter.cancel()
        for waiter in pending:
            if isinstance(waiter, asyncio.Task):
                with suppress(asyncio.CancelledError):
                    await waiter
        return "event", queue_task.result()

    queue_task.cancel()
    with suppress(asyncio.CancelledError):
        await queue_task
    return "transport_error", transport_error.result()


async def _cancel_background_task(task: asyncio.Task[Any]) -> None:
    """Cancel one background task and swallow cooperative cancellation noise."""

    if not task.done():
        task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _error_event(
    run_id: str,
    agent_name: str,
    message: str,
    error_type: str = "",
) -> pb2.AgentEvent:
    """Create an error AgentEvent protobuf."""
    from deepagents_runtime import events

    evt = events.error_event(
        message, run_id=run_id, agent_name=agent_name, error_type=error_type
    )
    return runtime_event_to_agent_event(evt)


async def _abort_invalid_argument(
    context: grpc.aio.ServicerContext | None,
    message: str,
) -> None:
    """Abort the current RPC with INVALID_ARGUMENT."""
    if context is None:
        raise ValueError(message)
    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, message)


async def _abort_not_found(
    context: grpc.aio.ServicerContext | None,
    message: str,
) -> None:
    """Abort the current RPC with NOT_FOUND."""
    if context is None:
        raise KeyError(message)
    await context.abort(grpc.StatusCode.NOT_FOUND, message)


async def _abort_internal(
    context: grpc.aio.ServicerContext | None,
    message: str,
) -> None:
    """Abort the current RPC with INTERNAL."""
    if context is None:
        raise RuntimeError(message)
    await context.abort(grpc.StatusCode.INTERNAL, message)


def _session_history_mode_to_proto(mode: str) -> int:
    """Map an internal history mode string to the protobuf enum."""
    if mode == "resume_view":
        return pb2.SESSION_HISTORY_MODE_RESUME_VIEW
    if mode == "full_transcript":
        return pb2.SESSION_HISTORY_MODE_FULL_TRANSCRIPT
    return pb2.SESSION_HISTORY_MODE_UNSPECIFIED


def _session_message_role_to_proto(role: str) -> int:
    """Map an internal session message role to the protobuf enum."""
    if role == "system":
        return pb2.SESSION_MESSAGE_ROLE_SYSTEM
    if role == "human":
        return pb2.SESSION_MESSAGE_ROLE_HUMAN
    if role == "ai":
        return pb2.SESSION_MESSAGE_ROLE_AI
    if role == "tool":
        return pb2.SESSION_MESSAGE_ROLE_TOOL
    return pb2.SESSION_MESSAGE_ROLE_UNSPECIFIED


def _iso_timestamp_to_proto(value: str | None) -> timestamp_pb2.Timestamp:
    """Convert an ISO timestamp string into protobuf Timestamp."""
    timestamp = timestamp_pb2.Timestamp()
    if not value:
        return timestamp

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return timestamp

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    timestamp.FromDatetime(parsed.astimezone(UTC))
    return timestamp


def _struct_from_dict(payload: dict[str, Any] | None) -> struct_pb2.Struct | None:
    """Convert a JSON-like dict into protobuf Struct."""
    if payload is None:
        return None

    struct = struct_pb2.Struct()
    try:
        struct.update(payload)
    except ValueError:
        logger.debug(
            "Failed to convert raw payload into protobuf Struct",
            exc_info=True,
        )
        return None
    return struct


def _runtime_agent_status_to_proto(
    status: AgentStatus | str | None,
) -> pb2.AgentRuntimeStatus:
    """Convert runtime agent lifecycle state into protobuf enum."""
    if status is None:
        return pb2.AGENT_RUNTIME_STATUS_UNSPECIFIED

    normalized = status.value if isinstance(status, AgentStatus) else str(status).strip().lower()
    if normalized == AgentStatus.INSTALLED.value:
        return pb2.AGENT_RUNTIME_STATUS_INSTALLED
    if normalized == AgentStatus.COMPILED.value:
        return pb2.AGENT_RUNTIME_STATUS_COMPILED
    if normalized == AgentStatus.RUNNING.value:
        return pb2.AGENT_RUNTIME_STATUS_RUNNING
    return pb2.AGENT_RUNTIME_STATUS_UNKNOWN


def _resolve_session_agent_status(
    agent_name: str | None,
    statuses: dict[str, AgentStatus],
) -> pb2.AgentRuntimeStatus:
    """Resolve one session's owning agent status from the live manager snapshot."""
    if not agent_name:
        return pb2.AGENT_RUNTIME_STATUS_UNSPECIFIED
    status = statuses.get(agent_name)
    if status is None:
        return pb2.AGENT_RUNTIME_STATUS_UNKNOWN
    return _runtime_agent_status_to_proto(status)


def _session_summary_to_proto(
    session: Any,
    *,
    agent_status: pb2.AgentRuntimeStatus | None = None,
) -> pb2.SessionSummary:
    """Convert an internal session summary record into protobuf."""
    return pb2.SessionSummary(
        thread_id=session.thread_id,
        agent_name=session.agent_name or "",
        updated_at=_iso_timestamp_to_proto(session.updated_at),
        latest_checkpoint_id=session.latest_checkpoint_id or "",
        message_count=session.message_count,
        initial_prompt=session.initial_prompt or "",
        history_mode=_session_history_mode_to_proto(session.history_mode),
        agent_status=(
            agent_status
            if agent_status is not None
            else pb2.AGENT_RUNTIME_STATUS_UNSPECIFIED
        ),
    )


def _session_message_to_proto(message: Any) -> pb2.SessionMessage:
    """Convert an internal session message record into protobuf."""
    proto_message = pb2.SessionMessage(
        index=message.index,
        role=_session_message_role_to_proto(message.role),
        text=message.text,
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        is_error=message.is_error,
    )
    raw = _struct_from_dict(message.raw)
    if raw is not None:
        proto_message.raw.CopyFrom(raw)
    return proto_message


async def serve(port: int = 50051) -> None:
    """Start the data plane gRPC server.

    Creates an AgentManager, registers both servicers, and serves
    on the specified port.

    Args:
        port: gRPC listen port (default: 50051).
    """
    from deepagents_runtime.manager.manager import AgentManager

    manager = AgentManager()
    await manager.setup()

    # Create servicers
    executor_servicer = AgentExecutorServicer(manager)
    resource_servicer = ResourceSyncServicer(manager)
    session_servicer = SessionQueryServicer(manager)

    # Create gRPC server and register servicers
    server = grpc_aio.server()
    runtime_pb2_grpc.add_AgentExecutorServicer_to_server(
        executor_servicer, server
    )
    runtime_pb2_grpc.add_ResourceSyncServicer_to_server(
        resource_servicer, server
    )
    runtime_pb2_grpc.add_SessionQueryServicer_to_server(
        session_servicer, server
    )

    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)

    logger.info("Data plane gRPC server starting on %s", listen_addr)
    await server.start()

    logger.info(
        "Data plane ready: AgentExecutor + ResourceSync + SessionQuery on port %d",
        port,
    )

    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Shutting down gRPC server...")
        await server.stop(grace=5.0)
    finally:
        await manager.shutdown()
