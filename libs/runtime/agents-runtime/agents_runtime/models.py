"""Model resolution.

Wraps the SDK's resolve_model() so runtime code does not need to
import from deepagents.graph directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel


@dataclass(frozen=True)
class ModelSpec:
    """A model specification in `provider:model` format.

    Examples:
        >>> spec = ModelSpec.parse("anthropic:claude-sonnet-4-5")
        >>> spec.provider
        'anthropic'
        >>> spec.model
        'claude-sonnet-4-5'
        >>> str(spec)
        'anthropic:claude-sonnet-4-5'
    """

    provider: str
    """The provider name (e.g., `'anthropic'`, `'openai'`)."""

    model: str
    """The model identifier (e.g., `'claude-sonnet-4-5'`, `'gpt-4o'`)."""

    def __post_init__(self) -> None:
        """Validate the model spec after initialization.

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
        """Parse a model specification string.

        Args:
            spec: Model specification in `'provider:model'` format.

        Returns:
            Parsed ModelSpec instance.

        Raises:
            ValueError: If the spec is not in valid `'provider:model'` format.
        """
        if ":" not in spec:
            msg = (
                f"Invalid model spec '{spec}': must be in provider:model format "
                "(e.g., 'anthropic:claude-sonnet-4-5')"
            )
            raise ValueError(msg)
        provider, model = spec.split(":", 1)
        return cls(provider=provider, model=model)

    @classmethod
    def try_parse(cls, spec: str) -> ModelSpec | None:
        """Try to parse a model specification, returning None on failure.

        Args:
            spec: Model specification to parse.

        Returns:
            Parsed ModelSpec if valid, None otherwise.
        """
        try:
            return cls.parse(spec)
        except ValueError:
            return None

    def __str__(self) -> str:
        """Return the model spec as a string in `provider:model` format."""
        return f"{self.provider}:{self.model}"

class ModelConfigError(Exception):
    """Raised when model configuration or creation fails."""

def _create_model_via_init(
    model_name: str,
    provider: str,
    kwargs: dict[str, Any],
) -> BaseChatModel:
    """Create a model using langchain's `init_chat_model`.

    Args:
        model_name: Model identifier.
        provider: Provider name (may be empty for auto-detection).
        kwargs: Additional keyword arguments.

    Returns:
        Instantiated `BaseChatModel`.

    Raises:
        ModelConfigError: On import, value, or runtime errors.
    """
    from langchain.chat_models import init_chat_model

    try:
        if provider:
            return init_chat_model(model_name, model_provider=provider, **kwargs)
        return init_chat_model(model_name, **kwargs)
    except ImportError as e:
        package_map = {
            "anthropic": "langchain-anthropic",
            "openai": "langchain-openai",
            "google_genai": "langchain-google-genai",
            "google_vertexai": "langchain-google-vertexai",
            "nvidia": "langchain-nvidia-ai-endpoints",
        }
        package = package_map.get(provider, f"langchain-{provider}")
        msg = (
            f"Missing package for provider '{provider}'. Install: pip install {package}"
        )
        raise ModelConfigError(msg) from e
    except (ValueError, TypeError) as e:
        spec = f"{provider}:{model_name}" if provider else model_name
        msg = f"Invalid model configuration for '{spec}': {e}"
        raise ModelConfigError(msg) from e
    except Exception as e:  # provider SDK auth/network errors
        spec = f"{provider}:{model_name}" if provider else model_name
        msg = f"Failed to initialize model '{spec}': {e}"
        raise ModelConfigError(msg) from e

@dataclass(frozen=True)
class ModelResult:
    """Result of creating a chat model, bundling the model with its metadata.

    This separates model creation from settings mutation so callers can decide
    when to commit the metadata to global settings.

    Attributes:
        model: The instantiated chat model.
        model_name: Resolved model name.
        provider: Resolved provider name.
        context_limit: Max input tokens from the model profile, or `None`.
    """

    model: BaseChatModel
    model_name: str
    provider: str
    context_limit: int | None = None

def create_model(
    model_spec: str | None = None,
    *,
    extra_kwargs: dict[str, Any] | None = None,
) -> ModelResult:
    """Create a chat model.

    Uses `init_chat_model` for standard providers, or imports a custom
    `BaseChatModel` subclass when the provider has a `class_path` in config.

    Supports `provider:model` format (e.g., `'anthropic:claude-sonnet-4-5'`)
    for explicit provider selection, or bare model names for auto-detection.

    Args:
        model_spec: Model specification in `provider:model` format (e.g.,
            `'anthropic:claude-sonnet-4-5'`, `'openai:gpt-4o'`).
            Required.
        extra_kwargs: Additional kwargs to pass to the model constructor.

    Returns:
        A `ModelResult` containing the model and its metadata.

    Raises:
        ModelConfigError: If provider cannot be determined from the model name,
            required provider package is not installed, or no credentials are
            configured.

    Examples:
        >>> result = create_model("anthropic:claude-sonnet-4-5")
        >>> result = create_model("openai:gpt-4o")
    """
    if not model_spec:
        raise ModelConfigError("model_spec is required")

    # Parse provider:model syntax
    provider: str
    model_name: str
    parsed = ModelSpec.parse(model_spec)
    provider, model_name = parsed.provider, parsed.model

    kwargs = extra_kwargs or {}

    model = _create_model_via_init(model_name, provider, kwargs)

    resolved_provider = provider or getattr(model, "_model_provider", provider)

    # Extract context limit from model profile (if available)
    context_limit: int | None = None
    profile = getattr(model, "profile", None)
    if isinstance(profile, dict) and isinstance(profile.get("max_input_tokens"), int):
        context_limit = profile["max_input_tokens"]

    return ModelResult(
        model=model,
        model_name=model_name,
        provider=resolved_provider,
        context_limit=context_limit,
    )
