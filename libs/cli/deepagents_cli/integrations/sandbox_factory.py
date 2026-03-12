"""Sandbox lifecycle management with provider abstraction."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from deepagents_runtime.sandboxes import (
    SandboxLifecycleHooks,
    SandboxProvider as RuntimeSandboxProvider,
    SandboxSetupError,
    create_sandbox as create_runtime_sandbox,
    get_default_working_dir,
)

from deepagents_cli.config import console, get_glyphs

if TYPE_CHECKING:
    from collections.abc import Generator

    from deepagents.backends.protocol import SandboxBackendProtocol

    from deepagents_cli.integrations.sandbox_provider import SandboxProvider


_AVAILABLE_SANDBOX_PROVIDERS: tuple[str, ...] = (
    "daytona",
    "langsmith",
    "modal",
    "runloop",
)


@contextmanager
def create_sandbox(
    provider: str,
    *,
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to a sandbox of the specified provider.

    This is the unified interface for sandbox creation using the provider abstraction.

    Args:
        provider: Sandbox provider ("daytona", "langsmith", "modal", "runloop")
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run after sandbox starts

    Yields:
        SandboxBackendProtocol instance

    Raises:
        RuntimeError: If the setup script is missing or fails to execute.
    """
    def on_start(name: str, _existing_id: str | None) -> None:
        console.print(f"[yellow]Starting {name} sandbox...[/yellow]")

    def on_ready(name: str, backend_id: str) -> None:
        glyphs = get_glyphs()
        console.print(
            f"[green]{glyphs.checkmark} {name.capitalize()} sandbox ready: "
            f"{backend_id}[/green]"
        )

    def on_setup_start(_name: str, script_path: str) -> None:
        console.print(f"[dim]Running setup script: {script_path}...[/dim]")

    def on_setup_complete(_name: str, _script_path: str) -> None:
        console.print(f"[green]{get_glyphs().checkmark} Setup complete[/green]")

    def on_setup_failed(_name: str, _script_path: str, exc: BaseException) -> None:
        if isinstance(exc, SandboxSetupError):
            console.print(f"[red]Setup script failed (exit {exc.exit_code}):[/red]")
            if exc.output:
                console.print(f"[dim]{exc.output}[/dim]")
        else:
            console.print(f"[red]Setup script failed: {exc}[/red]")

    def on_cleanup_start(name: str, backend_id: str) -> None:
        console.print(f"[dim]Terminating {name} sandbox {backend_id}...[/dim]")

    def on_cleanup_complete(name: str, backend_id: str) -> None:
        glyphs = get_glyphs()
        console.print(
            f"[dim]{glyphs.checkmark} {name.capitalize()} sandbox "
            f"{backend_id} terminated[/dim]"
        )

    def on_cleanup_failed(name: str, backend_id: str, exc: BaseException) -> None:
        warning = get_glyphs().warning
        console.print(
            f"[yellow]{warning} Cleanup failed for {name} sandbox "
            f"{backend_id}: {exc}[/yellow]"
        )

    hooks = SandboxLifecycleHooks(
        on_start=on_start,
        on_ready=on_ready,
        on_setup_start=on_setup_start,
        on_setup_complete=on_setup_complete,
        on_setup_failed=on_setup_failed,
        on_cleanup_start=on_cleanup_start,
        on_cleanup_complete=on_cleanup_complete,
        on_cleanup_failed=on_cleanup_failed,
    )

    try:
        with create_runtime_sandbox(
            provider,
            provider_resolver=_resolve_provider,
            sandbox_id=sandbox_id,
            setup_script_path=setup_script_path,
            hooks=hooks,
        ) as backend:
            yield backend
    except (FileNotFoundError, SandboxSetupError) as exc:
        msg = str(exc)
        if isinstance(exc, SandboxSetupError):
            msg = "Setup failed - aborting"
        raise RuntimeError(msg) from exc


def _get_available_sandbox_types() -> list[str]:
    """Get list of available sandbox provider types (internal).

    Returns:
        List of available sandbox provider type names
    """
    return sorted(_AVAILABLE_SANDBOX_PROVIDERS)


def _resolve_provider(provider_name: str) -> RuntimeSandboxProvider:
    return cast("RuntimeSandboxProvider", _get_provider(provider_name))


def _get_provider(provider_name: str) -> SandboxProvider:
    """Get a SandboxProvider instance for the specified provider (internal).

    Args:
        provider_name: Name of the provider ("daytona", "langsmith", "modal", "runloop")

    Returns:
        SandboxProvider instance

    Raises:
        ValueError: If provider_name is unknown
    """
    if provider_name == "daytona":
        from deepagents_cli.integrations.daytona import DaytonaProvider

        return DaytonaProvider()
    if provider_name == "langsmith":
        from deepagents_cli.integrations.langsmith import LangSmithProvider

        return LangSmithProvider()
    if provider_name == "modal":
        from deepagents_cli.integrations.modal import ModalProvider

        return ModalProvider()
    if provider_name == "runloop":
        from deepagents_cli.integrations.runloop import RunloopProvider

        return RunloopProvider()
    msg = (
        f"Unknown sandbox provider: {provider_name}. "
        f"Available providers: {', '.join(_get_available_sandbox_types())}"
    )
    raise ValueError(msg)


__all__ = [
    "create_sandbox",
    "get_default_working_dir",
]
