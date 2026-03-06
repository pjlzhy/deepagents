"""Module entry point for `python -m deepagents_server`."""

from __future__ import annotations

from deepagents_server.app import create_app
from deepagents_server.config import parse_config
from deepagents_server.server import run_server


def main() -> None:
    """Run the Deep Agents HTTP server."""
    config = parse_config()
    run_server(config, app=create_app())


if __name__ == "__main__":
    main()
