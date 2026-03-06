"""Configuration helpers for the Deep Agents server package."""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration for the placeholder HTTP server.

    Args:
        host: Interface to bind the HTTP server to.
        port: TCP port to listen on.
    """

    host: str = "127.0.0.1"
    port: int = 8080


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the placeholder HTTP server.

    Returns:
        Configured argument parser for `python -m deepagents_server`.
    """
    parser = argparse.ArgumentParser(description="Run the Deep Agents HTTP server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind to.")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on.")
    return parser


def parse_config(argv: list[str] | None = None) -> ServerConfig:
    """Parse command-line arguments into a server config.

    Args:
        argv: Optional explicit argv list for testing.

    Returns:
        Parsed server configuration.
    """
    args = build_argument_parser().parse_args(argv)
    return ServerConfig(host=args.host, port=args.port)
