"""Shared run and streaming helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ModelStats:
    """Token stats for a single model within a session."""

    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class SessionStats:
    """Stats accumulated over a single agent turn or full session."""

    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_time_seconds: float = 0.0
    per_model: dict[str, ModelStats] = field(default_factory=dict)

    def record_request(
        self,
        model_name: str,
        input_toks: int,
        output_toks: int,
    ) -> None:
        """Accumulate token counts for one completed LLM request.

        Args:
            model_name: Model used for the request.
            input_toks: Input tokens consumed.
            output_toks: Output tokens produced.
        """
        self.request_count += 1
        self.input_tokens += input_toks
        self.output_tokens += output_toks
        if model_name:
            entry = self.per_model.setdefault(model_name, ModelStats())
            entry.request_count += 1
            entry.input_tokens += input_toks
            entry.output_tokens += output_toks

    def merge(self, other: SessionStats) -> None:
        """Merge another `SessionStats` into this instance."""
        self.request_count += other.request_count
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.wall_time_seconds += other.wall_time_seconds
        for model, stats in other.per_model.items():
            entry = self.per_model.setdefault(model, ModelStats())
            entry.request_count += stats.request_count
            entry.input_tokens += stats.input_tokens
            entry.output_tokens += stats.output_tokens


def format_token_count(count: int) -> str:
    """Format a token count into a short human-readable string.

    Returns:
        Compact token count string (for example, `12.3K`).
    """
    if count >= 1_000_000:  # noqa: PLR2004
        return f"{count / 1_000_000:.1f}M"
    if count >= 1000:  # noqa: PLR2004
        return f"{count / 1000:.1f}K"
    return str(count)


def build_stream_config(
    thread_id: str,
    assistant_id: str | None,
) -> dict[str, dict[str, str]]:
    """Build a LangGraph stream config dict.

    Args:
        thread_id: Session thread identifier.
        assistant_id: Agent identifier, if any.

    Returns:
        Config dict with `configurable` and `metadata` keys.
    """
    metadata: dict[str, str] = {}
    if assistant_id:
        metadata.update(
            {
                "assistant_id": assistant_id,
                "agent_name": assistant_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
    return {
        "configurable": {"thread_id": thread_id},
        "metadata": metadata,
    }


def is_summarization_chunk(metadata: dict | None) -> bool:
    """Check if stream metadata belongs to summarization middleware.

    Returns:
        `True` if the chunk is produced by summarization middleware, `False`
        otherwise.
    """
    if metadata is None:
        return False
    return metadata.get("lc_source") == "summarization"
