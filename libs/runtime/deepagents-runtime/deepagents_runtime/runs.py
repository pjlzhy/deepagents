"""Run statistics and token tracking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelStats:
    """Token stats for a single model within a session."""

    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class SessionStats:
    """Stats accumulated over an agent run."""

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
        """Accumulate token counts for one completed LLM request."""
        self.request_count += 1
        self.input_tokens += input_toks
        self.output_tokens += output_toks

        if model_name:
            if model_name not in self.per_model:
                self.per_model[model_name] = ModelStats()
            ms = self.per_model[model_name]
            ms.request_count += 1
            ms.input_tokens += input_toks
            ms.output_tokens += output_toks

    def merge(self, other: SessionStats) -> None:
        """Merge another SessionStats into this one."""
        self.request_count += other.request_count
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.wall_time_seconds += other.wall_time_seconds
        for model_name, ms in other.per_model.items():
            if model_name not in self.per_model:
                self.per_model[model_name] = ModelStats()
            mine = self.per_model[model_name]
            mine.request_count += ms.request_count
            mine.input_tokens += ms.input_tokens
            mine.output_tokens += ms.output_tokens
