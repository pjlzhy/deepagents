"""AgentManager: manager-controlled install, compile, and run lifecycle.

Central coordinator for the data plane. Manages:
- Agent specs via Registry (file-system backed)
- Agent compilation into RuntimeAgent-owned runnable graphs
- Agent execution via RuntimeAgent.astream()
- Compiled agent scoped MCP / sandbox runtime resources

The AgentManager does NOT know about the control plane or gRPC.
It is used by the gRPC servicers (entry/server.py) to handle RPCs.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepagents.backends.protocol import FileDownloadResponse, FileInfo, FileUploadResponse
from agents_runtime import events
from agents_runtime.agent import HITLHandler, RuntimeAgent
from agents_runtime.events import RuntimeEvent
from agents_runtime.registry import Registry
from agents_runtime.runtime_backend import (
    normalize_relative_runtime_path,
    normalize_runtime_upload_path,
)
from agents_runtime.sessions import generate_thread_id, get_checkpointer
from agents_runtime.spec import (
    AgentMeta,
    AgentSpec,
    AgentStatus,
    RunConfig,
    validate_agent_spec,
)
from agents_runtime.telemetry import (
    TelemetryEvent,
    finalize_telemetry_event,
    telemetry_from_runtime_event,
)

logger = logging.getLogger(__name__)

_RUN_TIMEOUT_ERROR = "timeout"
_RUNTIME_ERROR = "runtime_error"


class AgentPool:
    """Concurrent-safe runtime agent pool."""

    def __init__(self, agents: dict[str, RuntimeAgent] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._agents: dict[str, RuntimeAgent] = agents or {}

    async def get(self, name: str) -> RuntimeAgent:
        """Get a runtime agent by name."""
        async with self._lock:
            agent = self._agents.get(name)
            if agent is None:
                raise KeyError(f"Agent '{name}' not found in agent pool")
            return agent

    async def get_optional(self, name: str) -> RuntimeAgent | None:
        """Get a runtime agent by name, returning `None` if absent."""
        async with self._lock:
            return self._agents.get(name)

    async def set(self, agent: RuntimeAgent) -> None:
        """Insert or replace a runtime agent."""
        async with self._lock:
            self._agents[agent.spec.name] = agent

    async def pop(self, name: str) -> RuntimeAgent | None:
        """Remove and return a runtime agent."""
        async with self._lock:
            return self._agents.pop(name, None)

    async def values(self) -> list[RuntimeAgent]:
        """Snapshot all runtime agents."""
        async with self._lock:
            return list(self._agents.values())

    async def count(self) -> int:
        """Return the number of pooled agents."""
        async with self._lock:
            return len(self._agents)

    async def status(self, name: str) -> AgentStatus:
        """Return the public status of a pooled agent."""
        agent = await self.get(name)
        return agent.status()


class AgentManager:
    """Manager-owned lifecycle controller for installed and compiled agents."""

    def __init__(
            self,
            registry: Registry | None = None,
    ) -> None:
        self._registry = registry or Registry()
        self.agent_pool: AgentPool | None = None
        self._checkpointer: Any = None
        self._checkpointer_cm: Any = None

    async def setup(self) -> None:
        """Initialise long-lived resources."""
        if self._checkpointer is None:
            self._checkpointer_cm = get_checkpointer()
            self._checkpointer = await self._checkpointer_cm.__aenter__()
            logger.info("Checkpointer initialised")
        if self.agent_pool is None:
            self.agent_pool = AgentPool()

    async def shutdown(self) -> None:
        """Release compiled runtime resources and the shared checkpointer."""
        if self.agent_pool is not None:
            for agent in await self.agent_pool.values():
                if agent.is_running():
                    logger.warning(
                        "Skipping runtime release for running agent '%s' during shutdown",
                        agent.spec.name,
                    )
                    continue
                if agent.has_runtime():
                    try:
                        await agent.release()
                    except Exception:
                        logger.warning(
                            "Failed to release runtime for agent '%s' during shutdown",
                            agent.spec.name,
                            exc_info=True,
                        )

        if self._checkpointer_cm is not None:
            await self._checkpointer_cm.__aexit__(None, None, None)
            self._checkpointer = None
            self._checkpointer_cm = None
            logger.info("Checkpointer closed")

    async def __aenter__(self) -> AgentManager:
        await self.setup()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.shutdown()

    @property
    def registry(self) -> Registry:
        """Access the underlying registry for direct resource operations."""
        return self._registry

    # ── Agent Lifecycle ──

    async def define_agent(self, spec: AgentSpec) -> None:
        """Install or update an agent spec without compiling it."""
        await self.setup()
        assert self.agent_pool is not None
        validate_agent_spec(spec)

        agent = await self.agent_pool.get_optional(spec.name)
        stored_spec = await self._registry.get_agent_spec(spec.name)
        if agent is not None:
            if agent.is_busy():
                msg = f"cannot redefine agent '{spec.name}' while busy"
                raise RuntimeError(msg)

        runtime_matches = agent is not None and agent.spec == spec
        stored_matches = stored_spec == spec

        if runtime_matches and stored_matches:
            logger.info("Agent '%s' install skipped; spec unchanged", spec.name)
            return

        if runtime_matches:
            await self._registry.add_agent_spec(spec)
            logger.info(
                "Agent '%s' install skipped; runtime unchanged and registry refreshed",
                spec.name,
            )
            return

        if agent is None and stored_matches:
            await self.agent_pool.set(RuntimeAgent(spec=stored_spec, reg=self._registry))
            logger.info("Agent '%s' install skipped; loaded unchanged spec from registry", spec.name)
            return

        if agent is not None and agent.has_runtime():
            await agent.release()

        await self._registry.add_agent_spec(spec)

        if agent is None:
            agent = RuntimeAgent(spec=spec, reg=self._registry)
            await self.agent_pool.set(agent)
        else:
            agent.spec = spec

        logger.info("Agent '%s' installed", spec.name)

    async def assemble_agent(self, name: str) -> None:
        """Compile an installed agent into runnable runtime resources."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if agent.is_busy():
            msg = f"cannot assemble agent '{name}' while busy"
            raise RuntimeError(msg)

        latest_spec = await self._registry.get_agent_spec(name)
        if latest_spec is None:
            raise KeyError(f"Agent '{name}' not found")
        validate_agent_spec(latest_spec)

        if agent.has_runtime() and agent.spec == latest_spec:
            logger.info("Agent '%s' compile skipped; runtime already up to date", name)
            return

        if agent.has_runtime():
            await agent.release()

        agent.spec = latest_spec
        agent.registry = self._registry
        await agent.assemble(checkpointer=self._checkpointer)
        logger.info("Agent '%s' compiled", name)

    async def unload_agent(self, name: str) -> None:
        """Release compiled runtime resources while keeping the installed spec."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if agent.is_busy():
            msg = f"cannot unload agent '{name}' while busy"
            raise RuntimeError(msg)

        if agent.has_runtime():
            await agent.release()
            logger.info("Agent '%s' unloaded", name)

    async def remove_agent(self, name: str) -> bool:
        """Uninstall an agent by unloading runtime state and deleting its spec."""
        await self.setup()
        assert self.agent_pool is not None

        agent = await self.agent_pool.get_optional(name)
        if agent is not None:
            if agent.is_busy():
                msg = f"cannot remove agent '{name}' while busy"
                raise RuntimeError(msg)
            if agent.has_runtime():
                await agent.release()
            await self.agent_pool.pop(name)

        deleted = await self._registry.delete_agent_spec(name)
        if deleted or agent is not None:
            logger.info("Agent '%s' uninstalled", name)
            return True
        return False

    async def upload_workspace_files(
            self,
            *,
            name: str,
            thread_id: str,
            files: list[tuple[str, bytes]],
    ) -> tuple[str, list[FileUploadResponse]]:
        """Upload files into one thread workspace."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)

        resolved_thread_id = thread_id.strip() or generate_thread_id()
        self._ensure_thread_workspace_available(
            agent,
            thread_id=resolved_thread_id,
            operation="upload workspace files",
        )
        responses = await agent.upload_workspace_files(
            thread_id=resolved_thread_id,
            files=files,
        )
        return resolved_thread_id, responses

    async def download_workspace_files(
            self,
            *,
            name: str,
            thread_id: str,
            paths: list[str],
    ) -> tuple[str, list[FileDownloadResponse]]:
        """Download files from one thread workspace."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)

        resolved_thread_id = thread_id.strip()
        if not resolved_thread_id:
            raise ValueError("thread_id is required for download")
        self._ensure_thread_workspace_available(
            agent,
            thread_id=resolved_thread_id,
            operation="download workspace files",
        )
        responses = await agent.download_workspace_files(
            thread_id=resolved_thread_id,
            paths=paths,
        )
        return resolved_thread_id, responses

    async def list_workspace_files(
            self,
            *,
            name: str,
            thread_id: str,
            path: str = ".",
    ) -> tuple[str, list[FileInfo]]:
        """List files in one thread workspace directory."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)

        resolved_thread_id = thread_id.strip()
        if not resolved_thread_id:
            raise ValueError("thread_id is required for listing")
        self._ensure_thread_workspace_available(
            agent,
            thread_id=resolved_thread_id,
            operation="list workspace files",
        )
        entries = await agent.list_workspace_files(
            thread_id=resolved_thread_id,
            path=path,
        )
        return resolved_thread_id, entries

    async def prepare_workspace_file_upload(
            self,
            *,
            name: str,
            thread_id: str,
            path: str,
    ) -> tuple[str, str, Path]:
        """Resolve one upload target path on the runtime host filesystem."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)

        resolved_thread_id = thread_id.strip() or generate_thread_id()
        self._ensure_thread_workspace_available(
            agent,
            thread_id=resolved_thread_id,
            operation="upload workspace files",
        )
        root = self._registry.materialize_thread_root(name, resolved_thread_id)
        normalized_path = normalize_runtime_upload_path(path)
        return resolved_thread_id, normalized_path, _resolve_workspace_host_path(root, normalized_path)

    async def prepare_workspace_file_download(
            self,
            *,
            name: str,
            thread_id: str,
            path: str,
    ) -> tuple[str, Path]:
        """Resolve one download source path on the runtime host filesystem."""
        await self.setup()
        agent = await self._get_or_create_agent(name)

        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)

        resolved_thread_id = thread_id.strip()
        if not resolved_thread_id:
            raise ValueError("thread_id is required for download")
        self._ensure_thread_workspace_available(
            agent,
            thread_id=resolved_thread_id,
            operation="download workspace files",
        )
        root = self._registry.thread_root_dir(name, resolved_thread_id)
        normalized_path = normalize_relative_runtime_path(path)
        return normalized_path, _resolve_workspace_host_path(root, normalized_path)

    async def invoke(
            self,
            name: str,
            run_config: RunConfig,
            *,
            hitl_handler: HITLHandler | None = None,
            cancel_event: asyncio.Event | None = None,
            cancel_reason: str = "Run canceled by client",
            cancel_reason_getter: Callable[[], str] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run an already compiled agent and stream events.

        The manager owns the run lifecycle wrapper around `RuntimeAgent.astream()`:
        it resolves identifiers, enforces timeout and cancel semantics, and
        normalizes terminal runtime failures into public `RuntimeEvent`s.
        """
        await self.setup()
        agent = await self._get_or_create_agent(name)
        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)

        run_id = run_config.run_id or uuid.uuid4().hex[:12]
        thread_id = run_config.thread_id or generate_thread_id()
        configurable: dict[str, Any] = {
            "thread_id": thread_id,
            "run_id": run_id,
        }
        config: dict[str, Any] = {
            "configurable": configurable,
            "metadata": {
                "agent_name": name,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }
        timeout_seconds = run_config.timeout_seconds
        if timeout_seconds is not None and timeout_seconds < 0:
            msg = "run timeout_seconds cannot be negative"
            raise ValueError(msg)

        agent.last_invoked = datetime.now(UTC)
        if timeout_seconds == 0:
            yield self._timeout_event(
                agent_name=name,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
            )
            return

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        producer = asyncio.create_task(
            self._produce_run_events(
                agent=agent,
                message=run_config.input,
                config=config,
                hitl_handler=hitl_handler,
                queue=queue,
            )
        )
        deadline = (
            None
            if timeout_seconds is None
            else time.monotonic() + timeout_seconds
        )
        seq = 0

        def _next_seq() -> int:
            nonlocal seq
            seq += 1
            return seq

        try:
            while True:
                source, item = await self._wait_for_run_signal(
                    queue=queue,
                    cancel_event=cancel_event,
                    deadline=deadline,
                )
                if source == "timeout":
                    await self._cancel_run_producer(producer)
                    yield self._timeout_event(
                        agent_name=name,
                        run_id=run_id,
                        timeout_seconds=timeout_seconds,
                    )
                    return
                if source == "cancel":
                    await self._cancel_run_producer(producer)
                    reason = (
                        cancel_reason_getter()
                        if cancel_reason_getter is not None
                        else cancel_reason
                    )
                    yield events.run_canceled(
                        reason,
                        run_id=run_id,
                        agent_name=name,
                    )
                    return

                kind, payload = item
                if kind == "event":
                    yield payload
                    continue
                if kind == "error":
                    yield self._error_event_from_exception(
                        agent_name=name,
                        run_id=run_id,
                        exc=payload,
                    )
                    return
                if kind == "done":
                    return
        finally:
            await self._cancel_run_producer(producer)

    async def invoke_telemetry(
            self,
            name: str,
            run_config: RunConfig,
            *,
            hitl_handler: HITLHandler | None = None,
            cancel_event: asyncio.Event | None = None,
            cancel_reason: str = "Run canceled by client",
            cancel_reason_getter: Callable[[], str] | None = None,
    ) -> AsyncIterator[TelemetryEvent]:
        """Run an already compiled agent and stream telemetry events."""

        await self.setup()
        agent = await self._get_or_create_agent(name)
        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)

        run_id = run_config.run_id or uuid.uuid4().hex[:12]
        thread_id = run_config.thread_id or generate_thread_id()
        configurable: dict[str, Any] = {
            "thread_id": thread_id,
            "run_id": run_id,
        }
        config: dict[str, Any] = {
            "configurable": configurable,
            "metadata": {
                "agent_name": name,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }
        timeout_seconds = run_config.timeout_seconds
        if timeout_seconds is not None and timeout_seconds < 0:
            msg = "run timeout_seconds cannot be negative"
            raise ValueError(msg)

        agent.last_invoked = datetime.now(UTC)
        if timeout_seconds == 0:
            yield finalize_telemetry_event(
                self._telemetry_timeout_event(
                    agent_name=name,
                    run_id=run_id,
                    timeout_seconds=timeout_seconds,
                ),
                attempt=1,
                seq=1,
            )
            return

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        producer = asyncio.create_task(
            self._produce_telemetry_events(
                agent=agent,
                message=run_config.input,
                config=config,
                hitl_handler=hitl_handler,
                queue=queue,
            )
        )
        deadline = (
            None
            if timeout_seconds is None
            else time.monotonic() + timeout_seconds
        )
        attempt = 1
        seq = 0

        def _next_seq() -> int:
            nonlocal seq
            seq += 1
            return seq

        def next_event(event: TelemetryEvent) -> TelemetryEvent:
            return finalize_telemetry_event(
                event,
                attempt=attempt,
                seq=_next_seq(),
            )

        try:
            while True:
                source, item = await self._wait_for_run_signal(
                    queue=queue,
                    cancel_event=cancel_event,
                    deadline=deadline,
                )
                if source == "timeout":
                    await self._cancel_run_producer(producer)
                    yield next_event(self._telemetry_timeout_event(
                        agent_name=name,
                        run_id=run_id,
                        timeout_seconds=timeout_seconds,
                    ))
                    return
                if source == "cancel":
                    await self._cancel_run_producer(producer)
                    reason = (
                        cancel_reason_getter()
                        if cancel_reason_getter is not None
                        else cancel_reason
                    )
                    yield next_event(telemetry_from_runtime_event(
                        events.run_canceled(
                            reason,
                            run_id=run_id,
                            agent_name=name,
                        )
                    ))
                    return

                kind, payload = item
                if kind == "event":
                    yield next_event(payload)
                    continue
                if kind == "error":
                    yield next_event(self._telemetry_error_event_from_exception(
                        agent_name=name,
                        run_id=run_id,
                        exc=payload,
                    ))
                    return
                if kind == "done":
                    return
        finally:
            await self._cancel_run_producer(producer)

    async def _produce_run_events(
            self,
            *,
            agent: RuntimeAgent,
            message: str,
            config: dict[str, Any],
            hitl_handler: HITLHandler | None,
            queue: asyncio.Queue[tuple[str, Any]],
    ) -> None:
        """Drain `RuntimeAgent.astream()` into a queue for lifecycle control."""
        try:
            async for event in agent.astream(
                    context=None,
                    message=message,
                    config=config,
                    hitl_handler=hitl_handler,
            ):
                queue.put_nowait(("event", event))
        except Exception as exc:
            queue.put_nowait(("error", exc))
        finally:
            queue.put_nowait(("done", None))

    async def _produce_telemetry_events(
            self,
            *,
            agent: RuntimeAgent,
            message: str,
            config: dict[str, Any],
            hitl_handler: HITLHandler | None,
            queue: asyncio.Queue[tuple[str, Any]],
    ) -> None:
        """Drain `RuntimeAgent.atelemetry()` into a queue for lifecycle control."""

        try:
            async for event in agent.atelemetry(
                    context=None,
                    message=message,
                    config=config,
                    hitl_handler=hitl_handler,
            ):
                queue.put_nowait(("event", event))
        except Exception as exc:
            queue.put_nowait(("error", exc))
        finally:
            queue.put_nowait(("done", None))

    async def _wait_for_run_signal(
            self,
            *,
            queue: asyncio.Queue[tuple[str, Any]],
            cancel_event: asyncio.Event | None,
            deadline: float | None,
    ) -> tuple[str, Any]:
        """Wait for the next run event, cancel request, or timeout edge."""
        if not queue.empty():
            return "queue", queue.get_nowait()
        if cancel_event is not None and cancel_event.is_set():
            return "cancel", None

        timeout: float | None = None
        if deadline is not None:
            timeout = max(0.0, deadline - time.monotonic())
            if timeout == 0:
                return "timeout", None

        queue_task = asyncio.create_task(queue.get())
        cancel_task: asyncio.Task[bool] | None = None
        waiters: set[asyncio.Task[Any]] = {queue_task}
        if cancel_event is not None:
            cancel_task = asyncio.create_task(cancel_event.wait())
            waiters.add(cancel_task)

        done, pending = await asyncio.wait(
            waiters,
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with suppress(asyncio.CancelledError):
                await task

        if not done:
            return "timeout", None
        if queue_task in done:
            return "queue", queue_task.result()
        return "cancel", None

    async def _cancel_run_producer(self, task: asyncio.Task[None]) -> None:
        """Cancel the producer task and swallow cooperative cancellation noise."""
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    def _ensure_thread_workspace_available(
            self,
            agent: RuntimeAgent,
            *,
            thread_id: str,
            operation: str,
    ) -> None:
        """Reject thread-scoped workspace operations that would race with one active run."""
        if agent.is_transitioning():
            msg = f"cannot {operation} for agent '{agent.spec.name}' while busy"
            raise RuntimeError(msg)
        if agent.is_thread_running(thread_id):
            msg = (
                f"cannot {operation} for agent '{agent.spec.name}' "
                f"while thread '{thread_id}' is running"
            )
            raise RuntimeError(msg)

    def _timeout_event(
            self,
            *,
            agent_name: str,
            run_id: str,
            timeout_seconds: float | None,
    ) -> RuntimeEvent:
        """Create the terminal timeout event for a run."""
        if timeout_seconds is None or timeout_seconds == 0:
            message = "Run timed out before execution started"
        else:
            message = f"Run timed out after {timeout_seconds:.2f}s"
        return events.error_event(
            message,
            run_id=run_id,
            agent_name=agent_name,
            error_type=_RUN_TIMEOUT_ERROR,
        )

    def _error_event_from_exception(
            self,
            *,
            agent_name: str,
            run_id: str,
            exc: Exception,
    ) -> RuntimeEvent:
        """Convert an execution exception into the public error transport."""
        error_type = (
            _RUN_TIMEOUT_ERROR
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError))
            else _RUNTIME_ERROR
        )
        message = str(exc) or exc.__class__.__name__
        return events.error_event(
            message,
            run_id=run_id,
            agent_name=agent_name,
            error_type=error_type,
        )

    def _telemetry_timeout_event(
            self,
            *,
            agent_name: str,
            run_id: str,
            timeout_seconds: float | None,
    ) -> TelemetryEvent:
        """Create the terminal timeout telemetry event for a run."""

        return telemetry_from_runtime_event(
            self._timeout_event(
                agent_name=agent_name,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
            )
        )

    def _telemetry_error_event_from_exception(
            self,
            *,
            agent_name: str,
            run_id: str,
            exc: Exception,
    ) -> TelemetryEvent:
        """Convert an execution exception into the telemetry transport."""

        return telemetry_from_runtime_event(
            self._error_event_from_exception(
                agent_name=agent_name,
                run_id=run_id,
                exc=exc,
            )
        )


    async def list_agents(self) -> list[AgentMeta]:
        """List all installed agents with live runtime status overlays."""
        await self.setup()
        assert self.agent_pool is not None

        installed = await self._registry.list_agent_specs()
        runtime_agents = {
            agent.spec.name: agent
            for agent in await self.agent_pool.values()
        }

        return [
            AgentMeta(
                name=meta.name,
                version=meta.version,
                description=meta.description,
                tags=meta.tags,
                status=(
                    runtime_agents[meta.name].status()
                    if meta.name in runtime_agents
                    else meta.status
                ),
                active_thread_count=(
                    len(runtime_agents[meta.name].active_thread_ids())
                    if meta.name in runtime_agents
                    else 0
                ),
                active_thread_ids=(
                    runtime_agents[meta.name].active_thread_ids()
                    if meta.name in runtime_agents
                    else []
                ),
                last_invoked_at=(
                    runtime_agents[meta.name].last_invoked
                    if meta.name in runtime_agents
                    else None
                ),
            )
            for meta in installed
        ]

    async def get_agent_graph(
            self,
            name: str,
            *,
            xray_depth: int = 0,
    ) -> dict[str, Any]:
        """Return the drawable graph representation for one compiled agent."""

        await self.setup()
        agent = await self._get_or_create_agent(name)
        if not agent.has_runtime():
            msg = f"Agent '{name}' has not been assembled"
            raise RuntimeError(msg)
        return agent.get_graph_json(xray_depth=xray_depth)

    async def get_agent_status(self, name: str) -> AgentStatus:
        """Get current status of an agent."""
        await self.setup()
        assert self.agent_pool is not None

        agent = await self.agent_pool.get_optional(name)
        if agent is not None:
            return agent.status()
        spec = await self._registry.get_agent_spec(name)
        if spec is not None:
            return AgentStatus.INSTALLED
        raise KeyError(f"Agent '{name}' not found")

    # ── Internal ──

    async def _get_or_create_agent(self, name: str) -> RuntimeAgent:
        """Load an installed agent into the runtime pool if needed."""
        assert self.agent_pool is not None

        agent = await self.agent_pool.get_optional(name)
        if agent is not None:
            return agent

        spec = await self._registry.get_agent_spec(name)
        if spec is None:
            raise KeyError(f"Agent '{name}' not found")

        agent = RuntimeAgent(spec=spec, reg=self._registry)
        await self.agent_pool.set(agent)
        return agent


def _resolve_workspace_host_path(root: Path, relative_path: str) -> Path:
    """Resolve one workspace-relative path under one thread root."""
    resolved_root = root.resolve()
    target = (resolved_root / Path(relative_path)).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        msg = f"workspace path escapes thread root: {relative_path}"
        raise ValueError(msg) from exc
    return target
