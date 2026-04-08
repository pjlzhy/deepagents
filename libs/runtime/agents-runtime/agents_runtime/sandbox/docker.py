"""Docker sandbox backend.

Provides container-isolated execution environments using Docker.
Requires the `docker` extra: `pip install agents-runtime[docker]`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import posixpath
import uuid
from typing import Any

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from agents_runtime.spec import (
    DockerSandboxSpec,
    ImagePullPolicy,
    SandboxSpec,
    parse_sandbox_spec,
)

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
        image_pull_policy: ImagePullPolicy = ImagePullPolicy.UNSPECIFIED,
        host_mount_dir: str | None = None,
        container_root: str = "/agent",
        cpu: str = "",
        memory: str = "",
        shm_size: str = "",
        pids_limit: int = 0,
        max_output_bytes: int = 100_000,
    ) -> None:
        self._image = image
        self._image_pull_policy = image_pull_policy
        self._host_mount_dir = host_mount_dir
        self._container_root = container_root
        self._cpu = cpu
        self._memory = memory
        self._shm_size = shm_size
        self._pids_limit = pids_limit
        self._container: Any = None
        self._client: Any = None
        self._max_output_bytes = max_output_bytes
        self._sandbox_id = f"docker-{uuid.uuid4().hex[:8]}"

    @property
    def id(self) -> str:
        """Unique identifier for this backend instance."""
        return self._sandbox_id

    @classmethod
    async def from_spec(
        cls,
        spec: SandboxSpec | dict[str, Any],
        *,
        host_mount_dir: str | None = None,
        container_root: str = "/agent",
    ) -> DockerSandboxBackend:
        """Create a Docker sandbox from a SandboxSpec.

        Args:
            spec: Normalized sandbox specification with a Docker backend.

        Returns:
            An initialized (but not yet started) DockerSandboxBackend.
        """
        normalized_spec = parse_sandbox_spec(spec)
        if normalized_spec is None:
            msg = "docker sandbox backend requires a sandbox spec"
            raise ValueError(msg)

        backend_spec = normalized_spec.backend
        if not isinstance(backend_spec, DockerSandboxSpec):
            msg = "docker sandbox backend requires a DockerSandboxSpec"
            raise ValueError(msg)

        max_output_bytes = normalized_spec.execution.max_output_bytes or 100_000
        return cls(
            image=backend_spec.image.reference,
            image_pull_policy=backend_spec.image.pull_policy,
            host_mount_dir=host_mount_dir,
            container_root=container_root,
            cpu=backend_spec.resources.cpu,
            memory=backend_spec.resources.memory,
            shm_size=backend_spec.resources.shm_size,
            pids_limit=backend_spec.resources.pids_limit,
            max_output_bytes=max_output_bytes,
        )

    async def start(self, *, timeout_seconds: int = 0) -> None:
        """Create and start the Docker container."""
        if self._container is not None:
            return
        if timeout_seconds > 0:
            await asyncio.wait_for(
                self._start_impl(),
                timeout=float(timeout_seconds),
            )
            return
        await self._start_impl()

    async def _start_impl(self) -> None:
        """Create and start the Docker container without timeout wrapping."""
        if self._container is not None:
            return

        try:
            import docker
        except ImportError as exc:
            raise ImportError(
                "Docker sandbox requires the 'docker' package. "
                "Install with: pip install agents-runtime[docker]"
            ) from exc

        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(None, docker.from_env)
        await self._pull_image_if_needed(loop)

        # Keep the container alive so exec calls can reuse the same sandbox.
        run_kwargs: dict[str, Any] = {
            "command": ["sh", "-c", "while true; do sleep 3600; done"],
            "detach": True,
            "stdin_open": True,
            "tty": False,
            "remove": False,
            "working_dir": self._container_root,
        }
        if self._host_mount_dir:
            run_kwargs["volumes"] = {
                self._host_mount_dir: {
                    "bind": self._container_root,
                    "mode": "rw",
                }
            }
        if self._memory:
            run_kwargs["mem_limit"] = self._memory
        if self._shm_size:
            run_kwargs["shm_size"] = self._shm_size
        if self._pids_limit > 0:
            run_kwargs["pids_limit"] = self._pids_limit
        if self._cpu:
            run_kwargs["nano_cpus"] = _docker_nano_cpus(self._cpu)

        self._container = await loop.run_in_executor(
            None,
            lambda: self._client.containers.run(
                self._image,
                **run_kwargs,
            ),
        )
        logger.info(
            "Docker sandbox started: container=%s image=%s",
            self._container.short_id,
            self._image,
        )

    async def _pull_image_if_needed(self, loop: asyncio.AbstractEventLoop) -> None:
        """Apply the configured image pull policy before starting the container."""
        if self._client is None:
            return

        if self._image_pull_policy is ImagePullPolicy.ALWAYS:
            await loop.run_in_executor(
                None,
                lambda: self._client.images.pull(self._image),
            )
            return
        if self._image_pull_policy is ImagePullPolicy.NEVER:
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self._client.images.get(self._image),
                )
            except Exception as exc:
                msg = f"docker image {self._image!r} is not available locally"
                raise RuntimeError(msg) from exc

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

        exec_kwargs: dict[str, Any] = {"demux": False}
        if timeout is not None:
            exec_kwargs["timeout"] = timeout

        exit_code, output = self._container.exec_run(["sh", "-c", command], **exec_kwargs)
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

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload files into the running container.

        Files are written atomically via `python3` in the container. Response order
        matches input order and failures are reported per-file.
        """
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                normalized_path = _normalize_container_path(path)
            except ValueError:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
                continue

            content_b64 = base64.b64encode(content).decode("ascii")
            path_b64 = base64.b64encode(normalized_path.encode("utf-8")).decode("ascii")
            command = _docker_upload_command(path_b64=path_b64, content_b64=content_b64)
            result = self.execute(command)
            if result.exit_code == 0:
                responses.append(FileUploadResponse(path=path, error=None))
            else:
                responses.append(
                    FileUploadResponse(
                        path=path,
                        error=_map_upload_error(result.output),
                    )
                )
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files from the running container."""
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                normalized_path = _normalize_container_path(path)
            except ValueError:
                responses.append(FileDownloadResponse(path=path, content=None, error="invalid_path"))
                continue

            path_b64 = base64.b64encode(normalized_path.encode("utf-8")).decode("ascii")
            command = _docker_download_command(path_b64=path_b64)
            result = self.execute(command)
            if result.exit_code == 0:
                try:
                    content = (
                        base64.b64decode(result.output.encode("ascii"), validate=True)
                        if result.output
                        else b""
                    )
                except (binascii.Error, ValueError):
                    responses.append(FileDownloadResponse(path=path, content=None, error="invalid_path"))
                    continue
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            else:
                responses.append(
                    FileDownloadResponse(
                        path=path,
                        content=None,
                        error=_map_download_error(result.output),
                    )
                )
        return responses

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


def _normalize_container_path(path: str) -> str:
    """Normalize an absolute container path and reject traversal."""
    if not path or not path.startswith("/"):
        raise ValueError(path)
    normalized = posixpath.normpath(path)
    if normalized == "/" or normalized.startswith("/../") or normalized == "/..":
        raise ValueError(path)
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise ValueError(path)
    return normalized


def _docker_nano_cpus(value: str) -> int:
    """Convert a Docker CPU string into `nano_cpus`."""
    try:
        parsed = float(value)
    except ValueError as exc:
        msg = f"docker cpu value must be numeric, got {value!r}"
        raise ValueError(msg) from exc
    if parsed <= 0:
        msg = f"docker cpu value must be positive, got {value!r}"
        raise ValueError(msg)
    return int(parsed * 1_000_000_000)


def _docker_upload_command(*, path_b64: str, content_b64: str) -> str:
    return f"""python3 -c "
import base64
import os
import pathlib
import sys

file_path = base64.b64decode('{path_b64}').decode('utf-8')
content = base64.b64decode('{content_b64}')

try:
    pathlib.Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'wb') as handle:
        handle.write(content)
except PermissionError:
    print('permission_denied', file=sys.stderr)
    sys.exit(13)
except OSError:
    print('invalid_path', file=sys.stderr)
    sys.exit(22)
"""


def _docker_download_command(*, path_b64: str) -> str:
    return f"""python3 -c "
import base64
import os
import sys

file_path = base64.b64decode('{path_b64}').decode('utf-8')

if not os.path.exists(file_path):
    print('file_not_found', file=sys.stderr)
    sys.exit(2)
if os.path.isdir(file_path):
    print('is_directory', file=sys.stderr)
    sys.exit(21)

try:
    with open(file_path, 'rb') as handle:
        print(base64.b64encode(handle.read()).decode('ascii'), end='')
except PermissionError:
    print('permission_denied', file=sys.stderr)
    sys.exit(13)
"""


def _map_upload_error(output: str) -> str:
    normalized = output.strip().lower()
    if "permission_denied" in normalized:
        return "permission_denied"
    if "file_not_found" in normalized:
        return "file_not_found"
    return "invalid_path"


def _map_download_error(output: str) -> str:
    normalized = output.strip().lower()
    if "file_not_found" in normalized:
        return "file_not_found"
    if "permission_denied" in normalized:
        return "permission_denied"
    if "is_directory" in normalized:
        return "is_directory"
    return "invalid_path"
