"""Minimal application factory for the Deep Agents HTTP server."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

HealthHandler = Callable[[], tuple[int, dict[str, str]]]

_HEALTH_PATH: Final[str] = "/healthz"


@dataclass(frozen=True)
class ServerApp:
    """Simple route container for the placeholder server.

    Args:
        health_handler: Handler used to serve the health endpoint.
    """

    health_handler: HealthHandler

    def handle_request(self, method: str, path: str) -> tuple[int, bytes, str]:
        """Handle a single HTTP request.

        Args:
            method: HTTP method from the incoming request.
            path: Request path.

        Returns:
            Tuple of status code, body bytes, and content type.
        """
        if method == "GET" and path == _HEALTH_PATH:
            status_code, payload = self.health_handler()
            return status_code, json.dumps(payload).encode("utf-8"), "application/json"
        return 404, json.dumps({"error": "not_found"}).encode("utf-8"), "application/json"


def create_app() -> ServerApp:
    """Create the placeholder server application.

    Returns:
        Minimal route container with a health route.
    """
    return ServerApp(health_handler=lambda: (200, {"status": "ok"}))
