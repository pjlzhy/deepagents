"""Sandbox pool: acquire/release pattern for sandbox instances.

Amortizes sandbox creation cost by maintaining a pool of warm
sandbox instances, keyed by their specification.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deepagents_runtime.spec import SandboxSpec

logger = logging.getLogger(__name__)


def _spec_key(spec: SandboxSpec | None) -> str:
    """Produce a hashable key from a SandboxSpec for pool matching."""
    if not spec:
        return "_default"
    return f"{spec.get('image', '_default')}:{sorted(spec.get('resources', {}).items())}"


class SandboxPool:
    """Pool of sandbox instances with acquire/release semantics.

    Each sandbox is backed by a ``SandboxBackendProtocol`` instance
    from the SDK.  The pool manages lifecycle (create, reuse, destroy).

    Sandboxes are keyed by a spec fingerprint so that a returned sandbox
    is only reused for requests with the same specification.
    """

    def __init__(
        self,
        backend_factory: Any = None,
        max_size: int = 5,
    ) -> None:
        """Initialize the pool.

        Args:
            backend_factory: Callable that creates sandbox backend instances.
                Signature: ``async def factory(spec) -> backend``.
                If *None*, creates local filesystem backends.
            max_size: Maximum number of warm sandboxes in the pool.
        """
        self._backend_factory = backend_factory
        self._max_size = max_size
        # Per-spec queues of idle sandboxes
        self._available: dict[str, asyncio.Queue[Any]] = {}
        self._all: list[Any] = []
        self._lock = asyncio.Lock()

    async def acquire(self, spec: SandboxSpec | None = None) -> Any:
        """Acquire a sandbox instance from the pool.

        If an idle sandbox matching *spec* is available, returns it.
        Otherwise creates a new one (up to ``max_size`` total).

        Args:
            spec: Optional sandbox specification (image, resources, etc.).

        Returns:
            A sandbox backend instance (``SandboxBackendProtocol``).
        """
        key = _spec_key(spec)

        # Try to get an existing idle sandbox matching the spec
        queue = self._available.get(key)
        if queue is not None:
            try:
                return queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        # Create a new sandbox if under limit
        async with self._lock:
            if len(self._all) < self._max_size:
                sandbox = await self._create_sandbox(spec)
                self._all.append(sandbox)
                # Tag sandbox with its spec key for release routing
                sandbox._pool_spec_key = key  # type: ignore[attr-defined]
                return sandbox

        # Pool is full — wait for any matching sandbox to become available
        if key not in self._available:
            self._available[key] = asyncio.Queue()
        return await self._available[key].get()

    async def release(self, sandbox: Any) -> None:
        """Return a sandbox to the pool for reuse.

        Args:
            sandbox: The sandbox instance to release.
        """
        key = getattr(sandbox, "_pool_spec_key", "_default")
        if key not in self._available:
            self._available[key] = asyncio.Queue()

        queue = self._available[key]
        try:
            queue.put_nowait(sandbox)
        except asyncio.QueueFull:
            # Pool is full, destroy the excess sandbox
            await self._destroy_sandbox(sandbox)

    async def shutdown(self) -> None:
        """Destroy all sandboxes in the pool."""
        for queue in self._available.values():
            while not queue.empty():
                try:
                    sandbox = queue.get_nowait()
                    await self._destroy_sandbox(sandbox)
                except asyncio.QueueEmpty:
                    break
        self._available.clear()
        self._all.clear()

    async def _create_sandbox(self, spec: SandboxSpec | None) -> Any:
        """Create a new sandbox instance.

        Uses the configured backend factory if available, otherwise falls
        back to a local filesystem backend.
        """
        if self._backend_factory is not None:
            return await self._backend_factory(spec)

        # Default: use SDK's local filesystem backend
        from deepagents.backends.filesystem import FileSystemBackend

        return FileSystemBackend()

    async def _destroy_sandbox(self, sandbox: Any) -> None:
        """Destroy a sandbox instance."""
        cleanup = getattr(sandbox, "cleanup", None)
        if cleanup and callable(cleanup):
            try:
                result = cleanup()
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception:
                logger.warning("Error cleaning up sandbox", exc_info=True)
