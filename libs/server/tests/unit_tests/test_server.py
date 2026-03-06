from __future__ import annotations

import socket
import time
from contextlib import closing
from threading import Thread
from urllib.request import urlopen

from deepagents_server.app import create_app
from deepagents_server.config import ServerConfig
from deepagents_server.server import run_server


def _get_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def test_http_server_serves_healthz() -> None:
    port = _get_free_port()
    config = ServerConfig(host="127.0.0.1", port=port)
    thread = Thread(target=run_server, kwargs={"config": config, "app": create_app()}, daemon=True)

    thread.start()
    time.sleep(0.1)

    with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
        assert response.status == 200
        assert response.read() == b'{"status": "ok"}'
