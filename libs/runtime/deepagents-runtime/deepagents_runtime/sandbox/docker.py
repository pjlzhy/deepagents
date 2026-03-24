"""Docker sandbox backend.

Provides container-isolated execution environments using Docker.
Requires the `docker` extra: `pip install deepagents-runtime[docker]`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.sandbox import BaseSandbox
from deepagents_runtime.spec import SandboxSpec

logger = logging.getLogger(__name__)


class DockerSandboxBackend(BaseSandbox):
    """Docker-based sandbox backend.

    Wraps Docker container lifecycle to provide isolated filesystem
    and shell execution for agent runs.

    Notes:
        - Commands require `/bin/sh` inside the container image.
        - File operations inherited from `BaseSandbox` require `python3`
          inside the container image.
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        *,
        max_output_bytes: int = 100_000,
    ) -> None:
        self._image = image
        self._container: Any = None
        self._client: Any = None
        self._max_output_bytes = max_output_bytes
        self._sandbox_id = f"docker-{uuid.uuid4().hex[:8]}"

    @property
    def id(self) -> str:
        """Unique identifier for this backend instance."""
        return self._sandbox_id

    @classmethod
    async def from_spec(cls, spec: SandboxSpec) -> DockerSandboxBackend:
        """Create a Docker sandbox from a SandboxSpec.

        Args:
            spec: Sandbox specification with image, resources, init commands.

        Returns:
            An initialized (but not yet started) DockerSandboxBackend.
        """
        image = spec.get("image", "python:3.12-slim")
        backend = cls(image=image)
        return backend

    async def start(self) -> None:
        """Create and start the Docker container."""
        if self._container is not None:
            return

        try:
            import docker
        except ImportError as exc:
            raise ImportError(
                "Docker sandbox requires the 'docker' package. "
                "Install with: pip install deepagents-runtime[docker]"
            ) from exc

        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(None, docker.from_env)

        # Keep the container alive so exec calls can reuse the same sandbox.
        self._container = await loop.run_in_executor(
            None,
            lambda: self._client.containers.run(
                self._image,
                command=["sh", "-c", "while true; do sleep 3600; done"],
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

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a command in the container.

        Args:
            command: Shell command to execute.
            timeout: Per-command timeout override.

        Returns:
            Combined stdout/stderr, exit code, and truncation flag.
        """
        if self._container is None:
            raise RuntimeError("Sandbox not started. Call start() first.")

        if timeout is not None:
            msg = "Docker sandbox does not support per-command timeout overrides yet"
            raise ValueError(msg)

        exit_code, output = self._container.exec_run(
            ["sh", "-c", command],
            demux=False,
        )
        decoded = output.decode("utf-8", errors="replace") if output else ""
        encoded = decoded.encode("utf-8")
        truncated = len(encoded) > self._max_output_bytes
        if truncated:
            decoded = encoded[: self._max_output_bytes].decode(
                "utf-8",
                errors="replace",
            )

        return ExecuteResponse(
            output=decoded,
            exit_code=exit_code,
            truncated=truncated,
        )

    async def cleanup(self) -> None:
        """Stop and remove the container."""
        if self._container is not None:
            loop = asyncio.get_running_loop()
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
