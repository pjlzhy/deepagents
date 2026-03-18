"""Docker sandbox backend.

Provides container-isolated execution environments using Docker.
Requires the ``docker`` extra: ``pip install deepagents-runtime[docker]``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deepagents_runtime.spec import SandboxSpec

logger = logging.getLogger(__name__)


class DockerSandboxBackend:
    """Docker-based sandbox backend.

    Wraps Docker container lifecycle to provide isolated filesystem
    and shell execution for agent runs.

    Usage::

        sandbox = await DockerSandboxBackend.from_spec(spec)
        await sandbox.start()
        output = await sandbox.exec("python -c 'print(42)'")
        content = await sandbox.read_file("/tmp/result.txt")
        await sandbox.write_file("/tmp/input.txt", "hello")
        await sandbox.cleanup()
    """

    def __init__(self, image: str = "python:3.12-slim") -> None:
        self._image = image
        self._container: Any = None
        self._client: Any = None

    @classmethod
    async def from_spec(cls, spec: SandboxSpec) -> DockerSandboxBackend:
        """Create a Docker sandbox from a SandboxSpec.

        Args:
            spec: Sandbox specification with image, resources, init commands.

        Returns:
            An initialised (but not yet started) DockerSandboxBackend.
        """
        image = spec.get("image", "python:3.12-slim")
        backend = cls(image=image)
        return backend

    async def start(self) -> None:
        """Create and start the Docker container."""
        try:
            import docker
        except ImportError:
            raise ImportError(
                "Docker sandbox requires the 'docker' package. "
                "Install with: pip install deepagents-runtime[docker]"
            )

        loop = asyncio.get_event_loop()
        self._client = await loop.run_in_executor(None, docker.from_env)

        # Create container with a long-running command to keep it alive
        self._container = await loop.run_in_executor(
            None,
            lambda: self._client.containers.run(
                self._image,
                command="sleep infinity",
                detach=True,
                stdin_open=True,
                tty=False,
                remove=False,
            ),
        )
        logger.info(
            "Docker sandbox started: container=%s image=%s",
            self._container.short_id,
            self._image,
        )

    async def exec(self, command: str, timeout: float = 60.0) -> str:
        """Execute a command in the container.

        Args:
            command: Shell command to execute.
            timeout: Maximum execution time in seconds.

        Returns:
            Combined stdout+stderr output.

        Raises:
            RuntimeError: If container is not started or command fails.
        """
        if self._container is None:
            raise RuntimeError("Sandbox not started. Call start() first.")

        loop = asyncio.get_event_loop()

        def _exec() -> str:
            exit_code, output = self._container.exec_run(
                ["sh", "-c", command],
                demux=False,
            )
            decoded = output.decode("utf-8", errors="replace") if output else ""
            if exit_code != 0:
                raise RuntimeError(
                    f"Command exited with code {exit_code}: {decoded[:500]}"
                )
            return decoded

        return await asyncio.wait_for(
            loop.run_in_executor(None, _exec),
            timeout=timeout,
        )

    async def read_file(self, path: str) -> str:
        """Read a file from the container.

        Args:
            path: Absolute path inside the container.

        Returns:
            File contents as a string.
        """
        return await self.exec(f"cat {path!r}")

    async def write_file(self, path: str, content: str) -> None:
        """Write a file to the container.

        Args:
            path: Absolute path inside the container.
            content: File contents to write.
        """
        # Use heredoc to write arbitrary content
        escaped = content.replace("'", "'\\''")
        await self.exec(f"cat > {path!r} << 'SANDBOX_EOF'\n{escaped}\nSANDBOX_EOF")

    async def cleanup(self) -> None:
        """Stop and remove the container."""
        if self._container is not None:
            loop = asyncio.get_event_loop()
            try:
                container = self._container
                await loop.run_in_executor(
                    None,
                    lambda: container.remove(force=True),
                )
                logger.info(
                    "Docker sandbox cleaned up: container=%s",
                    container.short_id,
                )
            except Exception:
                logger.warning(
                    "Error removing container", exc_info=True
                )
            finally:
                self._container = None

        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
