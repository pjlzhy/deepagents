import json

from deepagents_server.app import create_app


def test_health_route_returns_ok() -> None:
    app = create_app()

    status_code, body, content_type = app.handle_request("GET", "/healthz")

    assert status_code == 200
    assert content_type == "application/json"
    assert json.loads(body) == {"status": "ok"}


def test_unknown_route_returns_404() -> None:
    app = create_app()

    status_code, body, content_type = app.handle_request("GET", "/missing")

    assert status_code == 404
    assert content_type == "application/json"
    assert json.loads(body) == {"error": "not_found"}
