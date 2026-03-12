from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest

from deepagents_runtime.models import (
    ModelConfigError,
    ModelSpec,
    clear_default_model,
    detect_provider,
    get_default_model_spec,
    normalize_model_spec,
    save_default_model,
    save_recent_model,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_model_spec_parses_and_round_trips() -> None:
    spec = ModelSpec.parse("openai:gpt-4o")
    assert spec.provider == "openai"
    assert spec.model == "gpt-4o"
    assert str(spec) == "openai:gpt-4o"
    assert ModelSpec.try_parse("openai:gpt-4o") == spec
    assert ModelSpec.try_parse("gpt-4o") is None


def test_detect_provider_uses_prefixes() -> None:
    assert detect_provider("gpt-4o") == "openai"
    assert detect_provider("o4-mini") == "openai"
    assert detect_provider("claude-sonnet-4-6") in {"anthropic", "google_vertexai"}
    assert detect_provider("gemini-3.1-pro") in {"google_genai", "google_vertexai"}
    assert detect_provider("nvidia/nemotron-3-nano-30b-a3b") == "nvidia"
    assert detect_provider("unknown-model") is None


def test_normalize_model_spec_prefers_provider_model_syntax() -> None:
    assert normalize_model_spec("openai:gpt-4o") == "openai:gpt-4o"
    assert normalize_model_spec("gpt-4o") == "openai:gpt-4o"
    assert normalize_model_spec(":gpt-4o") == "openai:gpt-4o"

    with pytest.raises(ModelConfigError):
        _ = normalize_model_spec("openai:")


def test_model_preferences_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[other]\nvalue = "keep"\n', encoding="utf-8")

    assert save_recent_model("openai:gpt-4o", config_path=config_path)
    assert save_default_model("anthropic:claude-sonnet-4-6", config_path=config_path)

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["models"]["recent"] == "openai:gpt-4o"
    assert data["models"]["default"] == "anthropic:claude-sonnet-4-6"
    assert data["other"]["value"] == "keep"

    assert clear_default_model(config_path=config_path)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "default" not in data["models"]
    assert data["models"]["recent"] == "openai:gpt-4o"


def test_get_default_model_spec_prefers_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[models]\ndefault = "openai:gpt-4o"\nrecent = "anthropic:claude-sonnet-4-6"\n',
        encoding="utf-8",
    )

    assert get_default_model_spec(config_path=config_path) == "openai:gpt-4o"

    config_path.write_text(
        '[models]\nrecent = "anthropic:claude-sonnet-4-6"\n', encoding="utf-8"
    )
    assert (
        get_default_model_spec(config_path=config_path)
        == "anthropic:claude-sonnet-4-6"
    )


def test_get_default_model_spec_uses_env_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    assert get_default_model_spec(config_path=config_path).startswith("openai:")
