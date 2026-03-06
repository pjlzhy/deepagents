"""HTTP serving utilities for the Deep Agents server package."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from deepagents_server.app import ServerApp

if TYPE_CHECKING:
    from deepagents_server.config import ServerConfig


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP handler backed by `ServerApp`."""

    app: ServerApp

    def do_GET(self) -> None:  # Required by BaseHTTPRequestHandler.
        """Serve a GET request."""
        self._dispatch_request()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002  # Match stdlib signature.
        """Silence default stdlib request logging for tests and CLI startup."""
        del format, args

    def _dispatch_request(self) -> None:
        """Dispatch the current request to the application."""
        split_result = urlsplit(self.path)
        status_code, body, content_type = self.app.handle_request(
            method=self.command,
            path=split_result.path,
        )
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(config: ServerConfig, *, app: ServerApp | None = None) -> None:
    """Run the placeholder HTTP server.

    Args:
        config: Server bind configuration.
        app: Optional pre-built app for tests.
    """
    server_app = app or ServerApp(health_handler=lambda: (HTTPStatus.OK, {"status": "ok"}))
    RequestHandler.app = server_app
    with ThreadingHTTPServer((config.host, config.port), RequestHandler) as httpd:
        httpd.serve_forever()
