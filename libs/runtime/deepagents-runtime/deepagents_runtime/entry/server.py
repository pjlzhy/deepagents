"""Data Plane gRPC server.

Implements two gRPC services defined in runtime.proto:
  - AgentExecutor:  bidirectional streaming for agent execution + HITL
  - ResourceSync:   unary RPCs for pushing resources from control plane

This is the data plane's only external interface. The control plane
connects here to sync resources, assemble agents, and invoke runs.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import grpc
from grpc import aio as grpc_aio

from deepagents_runtime.converters import (
    runtime_event_to_agent_event,
    sync_agent_spec_request_to_agent_spec,
)
from deepagents_runtime.generated import runtime_pb2 as pb2
from deepagents_runtime.generated import runtime_pb2_grpc
from deepagents_runtime.manager.manager import AgentManager
from deepagents_runtime.sessions import generate_thread_id
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
                return []

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
                ),
                hitl_handler=hitl_handler,
            ):
                # Check for cancel
                if cancel_event.is_set():
                    from deepagents_runtime import events as _ev

                    yield runtime_event_to_agent_event(
                        _ev.run_canceled(
                            cancel_reason,
                            run_id=run_id,
                            agent_name=agent_name,
                        )
                    )
                    break

                # Forward runtime events, including HITL_REQUEST.
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
        import time

        try:
            agents = await self._manager.list_agents()
            assembled_count = sum(
                1 for a in agents
                if a.status in (AgentStatus.COMPILED, AgentStatus.RUNNING)
            )
            return pb2.HealthResponse(
                status="ok",
                assembled_agent_count=assembled_count,
                uptime_seconds=time.monotonic(),
            )
        except Exception:
            return pb2.HealthResponse(
                status="unhealthy",
                assembled_agent_count=0,
                uptime_seconds=0.0,
            )


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

    # Create gRPC server and register servicers
    server = grpc_aio.server()
    runtime_pb2_grpc.add_AgentExecutorServicer_to_server(
        executor_servicer, server
    )
    runtime_pb2_grpc.add_ResourceSyncServicer_to_server(
        resource_servicer, server
    )

    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)

    logger.info("Data plane gRPC server starting on %s", listen_addr)
    await server.start()

    logger.info(
        "Data plane ready — AgentExecutor + ResourceSync on port %d", port
    )

    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Shutting down gRPC server...")
        await server.stop(grace=5.0)
    finally:
        await manager.shutdown()
