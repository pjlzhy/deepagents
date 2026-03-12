import pytest

from deepagents_runtime.runs import (
    SessionStats,
    build_stream_config,
    format_token_count,
    is_summarization_chunk,
)


class TestFormatTokenCount:
    def test_formats_plain_count(self):
        assert format_token_count(500) == "500"

    def test_formats_thousands(self):
        assert format_token_count(12_500) == "12.5K"

    def test_formats_millions(self):
        assert format_token_count(1_250_000) == "1.2M"


class TestBuildStreamConfig:
    def test_includes_assistant_metadata(self):
        config = build_stream_config("thread-1", "agent")

        assert config["configurable"] == {"thread_id": "thread-1"}
        assert config["metadata"]["assistant_id"] == "agent"
        assert config["metadata"]["agent_name"] == "agent"
        assert "updated_at" in config["metadata"]

    def test_omits_assistant_metadata_when_missing(self):
        config = build_stream_config("thread-1", None)

        assert config == {
            "configurable": {"thread_id": "thread-1"},
            "metadata": {},
        }


class TestIsSummarizationChunk:
    def test_true_for_summarization_metadata(self):
        assert is_summarization_chunk({"lc_source": "summarization"}) is True

    def test_false_for_non_summarization_metadata(self):
        assert is_summarization_chunk({"lc_source": "tool"}) is False
        assert is_summarization_chunk(None) is False


class TestSessionStats:
    def test_record_request_updates_totals_and_per_model(self):
        stats = SessionStats()

        stats.record_request("gpt-5", 100, 25)

        assert stats.request_count == 1
        assert stats.input_tokens == 100
        assert stats.output_tokens == 25
        assert stats.per_model["gpt-5"].request_count == 1

    def test_merge_combines_models_and_totals(self):
        left = SessionStats()
        left.record_request("gpt-5", 100, 25)
        left.wall_time_seconds = 2.0

        right = SessionStats()
        right.record_request("claude", 50, 10)
        right.wall_time_seconds = 3.0

        left.merge(right)

        assert left.request_count == 2
        assert left.input_tokens == 150
        assert left.output_tokens == 35
        assert left.wall_time_seconds == pytest.approx(5.0)
        assert set(left.per_model) == {"gpt-5", "claude"}
