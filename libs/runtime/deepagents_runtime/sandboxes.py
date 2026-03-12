"""Provider-agnostic sandbox lifecycle helpers.

The Deep Agents CLI supports optional remote sandbox providers (Modal, Daytona,
Runloop, LangSmith). The long-term goal for the web platform is to reuse the same
core lifecycle semantics from a shared runtime layer.

This module intentionally does **not** implement provider SDK integrations.
Instead, callers supply a provider resolver that returns a `SandboxProvider`
implementation for a given provider name.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import string
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from deepagents.backends.protocol import SandboxBackendProtocol

logger = logging.getLogger(__name__)


SandboxProviderResolver: TypeAlias = Callable[[str], "SandboxProvider"]


class SandboxError(Exception):
    """Base error for sandbox provider operations."""

    @property
    def original_exc(self) -> BaseException | None:
        """Return the original exception that caused this error, if any."""
        return self.__cause__


class SandboxNotFoundError(SandboxError):
    """Raised when the requested sandbox cannot be found."""


class SandboxSetupError(RuntimeError):
    """Raised when a sandbox setup script fails to execute successfully."""

    def __init__(
        self,
        *,
        setup_script_path: str,
        exit_code: int,
        output: str,
    ) -> None:
        """Initialize a `SandboxSetupError` with script execution details.

        Args:
            setup_script_path: Local path to the setup script.
            exit_code: Exit code returned by the sandbox command execution.
            output: Combined output from the sandbox execution.
        """
        self.setup_script_path = setup_script_path
        self.exit_code = exit_code
        self.output = output
        super().__init__(
            "Setup failed - aborting. "
            f"Exit code: {exit_code}. Output:\n{output}"
        )


class SandboxProvider(ABC):
    """Interface for creating and deleting sandbox backends."""

    @abstractmethod
    def get_or_create(
        self,
        *,
        sandbox_id: str | None = None,
        **kwargs: object,
    ) -> SandboxBackendProtocol:
        """Get an existing sandbox, or create one if needed."""
        raise NotImplementedError

    @abstractmethod
    def delete(
        self,
        *,
        sandbox_id: str,
        **kwargs: object,
    ) -> None:
        """Delete a sandbox by id."""
        raise NotImplementedError

    async def aget_or_create(
        self,
        *,
        sandbox_id: str | None = None,
        **kwargs: object,
    ) -> SandboxBackendProtocol:
        """Async wrapper around get_or_create.

        Returns:
            The created or existing sandbox backend.
        """
        return await asyncio.to_thread(
            self.get_or_create, sandbox_id=sandbox_id, **kwargs
        )

    async def adelete(
        self,
        *,
        sandbox_id: str,
        **kwargs: object,
    ) -> None:
        """Async wrapper around delete."""
        await asyncio.to_thread(self.delete, sandbox_id=sandbox_id, **kwargs)


_PROVIDER_TO_WORKING_DIR: dict[str, str] = {
    "daytona": "/home/daytona",
    "langsmith": "/tmp",  # noqa: S108  # LangSmith sandbox working directory
    "modal": "/workspace",
    "runloop": "/home/user",
}


def get_default_working_dir(provider: str) -> str:
    """Return the default working directory for a sandbox provider.

    Args:
        provider: Sandbox provider name ("daytona", "langsmith", "modal", "runloop").

    Returns:
        Default working directory path as string.

    Raises:
        ValueError: If provider is unknown.
    """
    if provider in _PROVIDER_TO_WORKING_DIR:
        return _PROVIDER_TO_WORKING_DIR[provider]
    msg = f"Unknown sandbox provider: {provider}"
    raise ValueError(msg)


def _run_sandbox_setup(backend: SandboxBackendProtocol, setup_script_path: str) -> None:
    """Run a setup script in the sandbox, expanding `${VAR}` from local env.

    Args:
        backend: Sandbox backend instance.
        setup_script_path: Local path to a setup script file.

    Raises:
        FileNotFoundError: If the setup script does not exist.
        SandboxSetupError: If the setup script fails to execute.
    """
    script_path = Path(setup_script_path)
    if not script_path.exists():
        msg = f"Setup script not found: {setup_script_path}"
        raise FileNotFoundError(msg)

    script_content = script_path.read_text(encoding="utf-8")

    template = string.Template(script_content)
    expanded_script = template.safe_substitute(os.environ)

    result = backend.execute(f"bash -c {shlex.quote(expanded_script)}", timeout=5 * 60)
    if result.exit_code != 0:
        raise SandboxSetupError(
            setup_script_path=setup_script_path,
            exit_code=result.exit_code,
            output=result.output,
        )


@dataclass(frozen=True, slots=True)
class SandboxLifecycleHooks:
    """Optional callbacks invoked during sandbox lifecycle operations."""

    on_start: Callable[[str, str | None], None] | None = None
    on_ready: Callable[[str, str], None] | None = None
    on_setup_start: Callable[[str, str], None] | None = None
    on_setup_complete: Callable[[str, str], None] | None = None
    on_setup_failed: Callable[[str, str, BaseException], None] | None = None
    on_cleanup_start: Callable[[str, str], None] | None = None
    on_cleanup_complete: Callable[[str, str], None] | None = None
    on_cleanup_failed: Callable[[str, str, BaseException], None] | None = None


def _maybe_call_hook(hook: Callable[..., object] | None, *args: object) -> None:
    if hook is None:
        return
    try:
        hook(*args)
    except Exception:
        logger.debug("Sandbox lifecycle hook failed", exc_info=True)


@contextmanager
def create_sandbox(
    provider: str,
    *,
    provider_resolver: SandboxProviderResolver,
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
    provider_kwargs: dict[str, object] | None = None,
    hooks: SandboxLifecycleHooks | None = None,
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to a sandbox using the provider abstraction.

    Args:
        provider: Sandbox provider identifier.
        provider_resolver: Callable that resolves `provider` to a `SandboxProvider`.
        sandbox_id: Optional existing sandbox ID to reuse.
        setup_script_path: Optional local setup script to run inside the sandbox.
        provider_kwargs: Optional extra kwargs forwarded to the provider.
        hooks: Optional lifecycle hooks invoked during sandbox start/setup/cleanup.

    Yields:
        Sandbox backend implementation.
    """
    provider_obj = provider_resolver(provider)
    kwargs = dict(provider_kwargs or {})

    should_cleanup = sandbox_id is None

    hooks_obj = hooks or SandboxLifecycleHooks()

    _maybe_call_hook(hooks_obj.on_start, provider, sandbox_id)
    backend = provider_obj.get_or_create(sandbox_id=sandbox_id, **kwargs)
    _maybe_call_hook(hooks_obj.on_ready, provider, backend.id)

    try:
        if setup_script_path:
            _maybe_call_hook(
                hooks_obj.on_setup_start,
                provider,
                setup_script_path,
            )
            try:
                _run_sandbox_setup(backend, setup_script_path)
            except Exception as exc:
                _maybe_call_hook(
                    hooks_obj.on_setup_failed,
                    provider,
                    setup_script_path,
                    exc,
                )
                raise
            else:
                _maybe_call_hook(
                    hooks_obj.on_setup_complete,
                    provider,
                    setup_script_path,
                )

        yield backend
    finally:
        if should_cleanup:
            _maybe_call_hook(hooks_obj.on_cleanup_start, provider, backend.id)
            try:
                provider_obj.delete(sandbox_id=backend.id)
            except Exception as exc:  # Cleanup must not mask original errors
                _maybe_call_hook(
                    hooks_obj.on_cleanup_failed,
                    provider,
                    backend.id,
                    exc,
                )
                logger.warning(
                    "Cleanup failed for %s sandbox %s",
                    provider,
                    getattr(backend, "id", "<unknown>"),
                    exc_info=True,
                )
            else:
                _maybe_call_hook(
                    hooks_obj.on_cleanup_complete,
                    provider,
                    backend.id,
                )


__all__ = [
    "SandboxError",
    "SandboxLifecycleHooks",
    "SandboxNotFoundError",
    "SandboxProvider",
    "SandboxProviderResolver",
    "SandboxSetupError",
    "create_sandbox",
    "get_default_working_dir",
]
