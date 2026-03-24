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
from datetime import UTC, datetime
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import grpc
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
        hitl_decision_queue: asyncio.Queue[pb2.HITLDecision] = asyncio.Queue()
        cancel_event = asyncio.Event()
        cancel_reason = "Run canceled by client"

        async def hitl_handler(request: dict[str, Any]) -> list[dict[str, Any]]:
            """HITL callback: await client decision (event already emitted)."""
            try:
                decision: pb2.HITLDecision = await asyncio.wait_for(
                    hitl_decision_queue.get(),
                    timeout=_HITL_DECISION_TIMEOUT,
                )
                return [
                    {
                        "tool_call_id": d.tool_call_id,
                        "approved": d.approved,
                        "reason": d.reason,
                    }
                    for d in decision.decisions
                ]
            except asyncio.TimeoutError:
                logger.warning("HITL decision timeout for run %s", run_id)
                msg = (
                    f"HITL decision timed out after "
                    f"{_HITL_DECISION_TIMEOUT:.0f}s"
                )
                raise TimeoutError(msg) from None

        # ── 3. Background: read client messages ──
        async def read_client_messages() -> None:
            """Read HITLDecision and CancelRequest from client stream."""
            nonlocal cancel_reason
            try:
                async for msg in request_iterator:
                    msg: pb2.ClientMessage
                    if msg.HasField("hitl_decision"):
                        await hitl_decision_queue.put(msg.hitl_decision)
                    elif msg.HasField("cancel"):
                        cancel_reason = msg.cancel.reason or "Run canceled by client"
                        cancel_event.set()
                        logger.info("Cancel requested for run %s", run_id)
                        break
            except Exception:
                logger.debug("Client stream closed for run %s", run_id)

        reader_task = asyncio.create_task(read_client_messages())

        # ── 4. Run agent and stream events ──
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
                yield runtime_event_to_agent_event(event)

        except KeyError as e:
            yield _error_event(run_id, agent_name, str(e), "not_found")
        except Exception as e:
            logger.exception("Error in Run for agent %s", agent_name)
            yield _error_event(run_id, agent_name, str(e))
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass


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
