"""Model spec parsing, provider detection, and persistence helpers.

This module is intentionally client-neutral. Both the Textual CLI and a future
web client should be able to share the same semantics for:

- Parsing `provider:model` strings
- Inferring providers from bare model names
- Persisting default/recent model preferences in `~/.deepagents/config.toml`
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


DEFAULT_CONFIG_PATH = Path.home() / ".deepagents" / "config.toml"
"""Default path for Deep Agents config."""


class ModelConfigError(Exception):
    """Raised when model configuration or creation fails."""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A model specification in `provider:model` format."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        """Validate provider/model strings are non-empty.

        Raises:
            ValueError: If provider or model is empty.
        """
        if not self.provider:
            msg = "Provider cannot be empty"
            raise ValueError(msg)
        if not self.model:
            msg = "Model cannot be empty"
            raise ValueError(msg)

    @classmethod
    def parse(cls, spec: str) -> ModelSpec:
        """Parse a model spec in `provider:model` format.

        Args:
            spec: Model specification in `provider:model` format.

        Returns:
            Parsed model spec.

        Raises:
            ValueError: If the spec does not contain both provider and model.
        """
        if ":" not in spec:
            msg = (
                f"Invalid model spec '{spec}': must be in provider:model format "
                "(e.g., 'anthropic:claude-sonnet-4-6')"
            )
            raise ValueError(msg)
        provider, model = spec.split(":", 1)
        return cls(provider=provider, model=model)

    @classmethod
    def try_parse(cls, spec: str) -> ModelSpec | None:
        """Try to parse a `provider:model` spec, returning `None` on failure.

        Returns:
            Parsed model spec, or `None` when parsing fails.
        """
        try:
            return cls.parse(spec)
        except ValueError:
            return None

    def __str__(self) -> str:
        """Render the spec as `provider:model`.

        Returns:
            Model spec string.
        """
        return f"{self.provider}:{self.model}"


def _has_env(name: str) -> bool:
    return bool(os.environ.get(name))


def _has_openai() -> bool:
    return _has_env("OPENAI_API_KEY")


def _has_anthropic() -> bool:
    return _has_env("ANTHROPIC_API_KEY")


def _has_google() -> bool:
    return _has_env("GOOGLE_API_KEY")


def _has_nvidia() -> bool:
    return _has_env("NVIDIA_API_KEY")


def _has_vertex_ai() -> bool:
    google_cloud_project = _has_env("GOOGLE_CLOUD_PROJECT")
    return google_cloud_project and not _has_google()


def detect_provider(model_name: str) -> str | None:
    """Auto-detect provider from model name.

    Args:
        model_name: Model name to detect provider from.

    Returns:
        Provider name (openai, anthropic, google_genai, google_vertexai, nvidia)
            or `None` if the provider cannot be determined from the name alone.
    """
    model_lower = model_name.lower()

    if model_lower.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"

    if model_lower.startswith("claude"):
        if not _has_anthropic() and _has_vertex_ai():
            return "google_vertexai"
        return "anthropic"

    if model_lower.startswith("gemini"):
        if _has_vertex_ai() and not _has_google():
            return "google_vertexai"
        return "google_genai"

    if model_lower.startswith(("nemotron", "nvidia/")):
        return "nvidia"

    return None


def normalize_model_spec(model_spec: str) -> str:
    """Normalize model spec strings into a stable `provider:model` form when possible.

    This helper mirrors the CLI behavior:
    - Accept `provider:model`
    - Accept bare model names (e.g., `gpt-4o`) and prefix when detectable
    - Treat leading-colon specs (e.g., `:claude...`) as bare model names

    Args:
        model_spec: Raw model spec string.

    Returns:
        Normalized model spec string.

        When the provider can be inferred, the result is `provider:model`.
        Otherwise, a bare model name is returned unchanged.

    Raises:
        ModelConfigError: If `model_spec` is empty or malformed (for example
            `openai:` with no model name).
    """
    spec = model_spec.strip()
    if not spec:
        msg = "Model spec cannot be empty"
        raise ModelConfigError(msg)

    spec = spec.removeprefix(":")

    parsed = ModelSpec.try_parse(spec)
    if parsed is not None:
        return str(parsed)

    if ":" in spec:
        _, _, after = spec.partition(":")
        if after:
            # Leading colon case was already handled; this means the provider is empty.
            provider = detect_provider(after) or ""
            if provider:
                return f"{provider}:{after}"
            return after
        msg = (
            f"Invalid model spec '{spec}': model name is required "
            "(e.g., 'anthropic:claude-sonnet-4-6' or 'claude-sonnet-4-6')"
        )
        raise ModelConfigError(msg)

    provider = detect_provider(spec)
    if provider:
        return f"{provider}:{spec}"
    return spec


def _read_config_data(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    return data if isinstance(data, dict) else {}


def _ensure_models_table(data: dict[str, Any]) -> dict[str, Any]:
    models_section = data.get("models")
    if isinstance(models_section, dict):
        return models_section
    models_section = {}
    data["models"] = models_section
    return models_section


_BARE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_escape_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{escaped}"'


def _toml_format_key(key: str) -> str:
    if _BARE_KEY_PATTERN.fullmatch(key):
        return key
    return _toml_escape_string(key)


def _toml_format_scalar(value: object) -> str:
    if isinstance(value, str):
        return _toml_escape_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    msg = f"Unsupported TOML value type: {type(value).__name__}"
    raise TypeError(msg)


def _toml_format_value(value: object) -> str:
    if isinstance(value, dict):
        msg = "Internal error: dict values must be emitted as tables"
        raise TypeError(msg)
    if isinstance(value, (list, tuple)):
        parts = [_toml_format_value(item) for item in value]
        return f"[{', '.join(parts)}]"
    if value is None:
        msg = "TOML does not support null values"
        raise TypeError(msg)
    return _toml_format_scalar(value)


def _iter_table_items(table: Mapping[str, Any]) -> Iterable[tuple[str, Any]]:
    for key in sorted(table):
        yield key, table[key]


def _dump_table(
    lines: list[str],
    table: Mapping[str, Any],
    *,
    prefix: tuple[str, ...],
) -> None:
    scalar_items: list[tuple[str, Any]] = []
    dict_items: list[tuple[str, Mapping[str, Any]]] = []

    for key, value in _iter_table_items(table):
        if isinstance(value, dict):
            dict_items.append((key, value))
        else:
            scalar_items.append((key, value))

    if prefix:
        header = ".".join(_toml_format_key(part) for part in prefix)
        lines.append(f"[{header}]")

    for key, value in scalar_items:
        formatted_key = _toml_format_key(key)
        lines.append(f"{formatted_key} = {_toml_format_value(value)}")

    for key, child in dict_items:
        if lines and lines[-1]:
            lines.append("")
        _dump_table(lines, child, prefix=(*prefix, key))


def _toml_dumps(data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _dump_table(lines, data, prefix=())
    return "\n".join(lines).rstrip() + "\n"


def _write_config_data(config_path: Path, data: Mapping[str, Any]) -> None:
    rendered = _toml_dumps(data)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=config_path.parent, suffix=".tmp")
    tmp_file = Path(tmp_path)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(rendered.encode("utf-8"))
        tmp_file.replace(config_path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp_file.unlink()
        raise


def _save_model_field(field: str, model_spec: str, *, config_path: Path | None) -> bool:
    path = config_path or DEFAULT_CONFIG_PATH
    try:
        data = _read_config_data(path)
        models_section = _ensure_models_table(data)
        models_section[field] = model_spec
        _write_config_data(path, data)
    except (OSError, tomllib.TOMLDecodeError, TypeError):
        return False
    return True


def save_default_model(model_spec: str, *, config_path: Path | None = None) -> bool:
    """Save the default model spec to `config.toml`.

    Args:
        model_spec: Model spec string to store in `[models].default`.
        config_path: Optional path override for testing.

    Returns:
        `True` on success, `False` on I/O or TOML serialization failures.
    """
    return _save_model_field("default", model_spec, config_path=config_path)


def save_recent_model(model_spec: str, *, config_path: Path | None = None) -> bool:
    """Save the recent model spec to `config.toml`.

    Args:
        model_spec: Model spec string to store in `[models].recent`.
        config_path: Optional path override for testing.

    Returns:
        `True` on success, `False` on I/O or TOML serialization failures.
    """
    return _save_model_field("recent", model_spec, config_path=config_path)


def clear_default_model(*, config_path: Path | None = None) -> bool:
    """Remove `[models].default` from the config file.

    Args:
        config_path: Optional path override for testing.

    Returns:
        `True` if cleared (or already absent), `False` on failure.
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return True

    try:
        data = _read_config_data(path)
        models_section = data.get("models")
        if not isinstance(models_section, dict) or "default" not in models_section:
            return True

        del models_section["default"]
        _write_config_data(path, data)
    except (OSError, tomllib.TOMLDecodeError, TypeError):
        return False
    return True


def _load_preferred_model_specs(
    *, config_path: Path | None
) -> tuple[str | None, str | None]:
    path = config_path or DEFAULT_CONFIG_PATH
    try:
        data = _read_config_data(path)
    except (OSError, tomllib.TOMLDecodeError):
        return None, None

    models_section = data.get("models")
    if not isinstance(models_section, dict):
        return None, None

    default_model = models_section.get("default")
    recent_model = models_section.get("recent")
    return (
        default_model if isinstance(default_model, str) else None,
        recent_model if isinstance(recent_model, str) else None,
    )


def get_default_model_spec(*, config_path: Path | None = None) -> str:
    """Get the preferred model specification based on config + available credentials.

    Resolution order:
    1. `[models].default` in config file (user's intentional preference).
    2. `[models].recent` in config file (last `/model` switch).
    3. Environment-based auto-detection.

    Args:
        config_path: Optional path override for testing.

    Returns:
        Model spec string (typically `provider:model`).

    Raises:
        ModelConfigError: When no model preference is set and no supported
            provider credentials are configured.
    """
    default_model, recent_model = _load_preferred_model_specs(config_path=config_path)
    if default_model:
        return default_model
    if recent_model:
        return recent_model

    if _has_openai():
        return "openai:gpt-5.2"
    if _has_anthropic():
        return "anthropic:claude-sonnet-4-6"
    if _has_google():
        return "google_genai:gemini-3.1-pro-preview"
    if _has_vertex_ai():
        return "google_vertexai:gemini-3.1-pro-preview"
    if _has_nvidia():
        return "nvidia:nvidia/nemotron-3-nano-30b-a3b"

    msg = (
        "No credentials configured. Please set one of: "
        "ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, "
        "GOOGLE_CLOUD_PROJECT, or NVIDIA_API_KEY"
    )
    raise ModelConfigError(msg)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "ModelConfigError",
    "ModelSpec",
    "clear_default_model",
    "detect_provider",
    "get_default_model_spec",
    "normalize_model_spec",
    "save_default_model",
    "save_recent_model",
]
