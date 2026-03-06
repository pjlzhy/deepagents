"""HTTP serving utilities for the Deep Agents server package."""

from __future__ import annotations

from typing import TYPE_CHECKING

import uvicorn

from deepagents_server.app import create_app

if TYPE_CHECKING:
    from fastapi import FastAPI

    from deepagents_server.config import ServerConfig


def run_server(config: ServerConfig, *, app: FastAPI | None = None) -> None:
    """Run the Deep Agents HTTP server.

    Args:
        config: Server bind configuration.
        app: Optional pre-built FastAPI application for tests.
    """
    server_app = app or create_app()
    uvicorn.run(
        server_app,
        host=config.host,
        port=config.port,
        access_log=False,
        log_level="warning",
    )
