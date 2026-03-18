"""Kubernetes sandbox backend stub.

Provides pod-based isolated execution environments using K8s.
"""

from __future__ import annotations

from typing import Any

from deepagents_runtime.spec import SandboxSpec


class K8sSandboxBackend:
    """Kubernetes pod-based sandbox backend.

    Creates ephemeral pods for agent sandboxed execution.

    Requires the ``k8s`` extra: ``pip install deepagents-runtime[k8s]``.
    """

    def __init__(
        self,
        namespace: str = "deepagents",
        image: str = "python:3.12-slim",
    ) -> None:
        self._namespace = namespace
        self._image = image
        self._pod_name: str | None = None

    @classmethod
    async def from_spec(
        cls, spec: SandboxSpec, namespace: str = "deepagents"
    ) -> K8sSandboxBackend:
        """Create a K8s sandbox from a SandboxSpec.

        Raises:
            NotImplementedError: K8s sandbox is not yet implemented.
        """
        raise NotImplementedError(
            "K8s sandbox is not yet implemented. "
            "Use the default local filesystem backend."
        )

    async def start(self) -> None:
        """Create and start the pod.

        Raises:
            NotImplementedError: K8s sandbox is not yet implemented.
        """
        raise NotImplementedError("K8s sandbox is not yet implemented.")

    async def exec(self, command: str) -> str:
        """Execute a command in the pod.

        Raises:
            NotImplementedError: K8s sandbox is not yet implemented.
        """
        raise NotImplementedError("K8s sandbox is not yet implemented.")

    async def read_file(self, path: str) -> str:
        """Read a file from the pod.

        Raises:
            NotImplementedError: K8s sandbox is not yet implemented.
        """
        raise NotImplementedError("K8s sandbox is not yet implemented.")

    async def write_file(self, path: str, content: str) -> None:
        """Write a file to the pod.

        Raises:
            NotImplementedError: K8s sandbox is not yet implemented.
        """
        raise NotImplementedError("K8s sandbox is not yet implemented.")

    async def cleanup(self) -> None:
        """Delete the pod.

        Raises:
            NotImplementedError: K8s sandbox is not yet implemented.
        """
        raise NotImplementedError("K8s sandbox is not yet implemented.")
