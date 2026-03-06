"""HTTP serving utilities for the Deep Agents server package."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from deepagents_server.app import AppResponse, ServerApp, create_app

if TYPE_CHECKING:
    from deepagents_server.config import ServerConfig


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP handler backed by `ServerApp`."""

    app: ServerApp

    def do_GET(self) -> None:  # Required by BaseHTTPRequestHandler.
        """Serve a GET request."""
        self._dispatch_request()

    def do_POST(self) -> None:  # Required by BaseHTTPRequestHandler.
        """Serve a POST request."""
        self._dispatch_request()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002  # Match stdlib signature.
        """Silence default stdlib request logging for tests and CLI startup."""
        del format, args

    def _dispatch_request(self) -> None:
        """Dispatch the current request to the application."""
        split_result = urlsplit(self.path)
        body_length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(body_length) if body_length > 0 else b""
        response = self.app.handle_request(
            method=self.command,
            path=split_result.path,
            headers=dict(self.headers.items()),
            body=request_body,
        )
        self._write_response(response)

    def _write_response(self, response: AppResponse) -> None:
        self.send_response(response.status_code)
        self.send_header("Content-Type", response.content_type)
        for key, value in response.headers.items():
            self.send_header(key, value)
        if response.stream is None:
            self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if response.stream is None:
            self.wfile.write(response.body)
            return
        for chunk in response.stream:
            self.wfile.write(chunk)
            self.wfile.flush()


def run_server(config: ServerConfig, *, app: ServerApp | None = None) -> None:
    """Run the Deep Agents HTTP server.

    Args:
        config: Server bind configuration.
        app: Optional pre-built app for tests.
    """
    server_app = app or create_app()
    RequestHandler.app = server_app
    with ThreadingHTTPServer((config.host, config.port), RequestHandler) as httpd:
        httpd.serve_forever()
