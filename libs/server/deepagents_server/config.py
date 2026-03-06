"""Configuration helpers for the Deep Agents server package."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Literal

_CHECKPOINTER_BACKEND_CHOICES = ("local", "memory")
_SUPPORTED_SANDBOX_TYPES = ("none",)


@dataclass(frozen=True)
class RuntimeDefaults:
    """Default runtime context applied to newly created server threads.

    Args:
        checkpointer_backend: Backend used when no explicit checkpointer is injected.
        sandbox_type: Sandbox provider name for execution requests.
        sandbox_id: Optional existing sandbox identifier to reuse.
        sandbox_setup: Optional setup script path for the sandbox.
        enable_memory: Whether thread metadata should advertise memory support.
        enable_skills: Whether thread metadata should advertise skills support.
        checkpointer: Optional concrete checkpointer injected by the host application.
    """

    checkpointer_backend: Literal["local", "memory"] = "local"
    sandbox_type: str = "none"
    sandbox_id: str | None = None
    sandbox_setup: str | None = None
    enable_memory: bool = False
    enable_skills: bool = False
    checkpointer: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration for the placeholder HTTP server.

    Args:
        host: Interface to bind the HTTP server to.
        port: TCP port to listen on.
        runtime_defaults: Default runtime context applied to new threads.
    """

    host: str = "127.0.0.1"
    port: int = 8080
    runtime_defaults: RuntimeDefaults = field(default_factory=RuntimeDefaults)


def _parse_sandbox_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in _SUPPORTED_SANDBOX_TYPES:
        return normalized
    supported = ", ".join(_SUPPORTED_SANDBOX_TYPES)
    msg = f"Unsupported sandbox type '{value}'. Supported values: {supported}."
    raise argparse.ArgumentTypeError(msg)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the placeholder HTTP server.

    Returns:
        Configured argument parser for `python -m deepagents_server`.
    """
    parser = argparse.ArgumentParser(description="Run the Deep Agents HTTP server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind to.")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on.")
    parser.add_argument(
        "--checkpointer-backend",
        choices=_CHECKPOINTER_BACKEND_CHOICES,
        default="local",
        help=(
            "Thread persistence backend to use (`local` reuses CLI storage, "
            "`memory` stays in-process)."
        ),
    )
    parser.add_argument(
        "--sandbox-type",
        type=_parse_sandbox_type,
        default="none",
        help="Sandbox provider for runs. The MVP server currently supports only `none`.",
    )
    return parser


def parse_config(argv: list[str] | None = None) -> ServerConfig:
    """Parse command-line arguments into a server config.

    Args:
        argv: Optional explicit argv list for testing.

    Returns:
        Parsed server configuration.
    """
    args = build_argument_parser().parse_args(argv)
    return ServerConfig(
        host=args.host,
        port=args.port,
        runtime_defaults=RuntimeDefaults(
            checkpointer_backend=args.checkpointer_backend,
            sandbox_type=args.sandbox_type,
        ),
    )
