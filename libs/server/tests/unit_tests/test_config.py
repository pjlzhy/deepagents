import pytest

from deepagents_server.config import RuntimeDefaults, ServerConfig, parse_config


def test_parse_config_uses_default_values() -> None:
    config = parse_config([])

    assert config == ServerConfig(
        host="127.0.0.1",
        port=8080,
        runtime_defaults=RuntimeDefaults(
            checkpointer_backend="local",
            sandbox_type="none",
        ),
    )


def test_parse_config_accepts_explicit_host_and_port() -> None:
    config = parse_config(
        [
            "--host",
            "127.0.0.2",
            "--port",
            "9090",
            "--checkpointer-backend",
            "memory",
            "--sandbox-type",
            "none",
        ]
    )

    assert config == ServerConfig(
        host="127.0.0.2",
        port=9090,
        runtime_defaults=RuntimeDefaults(
            checkpointer_backend="memory",
            sandbox_type="none",
        ),
    )


def test_parse_config_rejects_non_integer_ports() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_config(["--port", "not-a-port"])

    assert exc_info.value.code == 2


def test_parse_config_rejects_unsupported_sandbox_type() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_config(["--sandbox-type", "modal"])

    assert exc_info.value.code == 2
