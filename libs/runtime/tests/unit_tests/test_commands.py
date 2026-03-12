import importlib.metadata
from unittest.mock import patch

from deepagents_runtime.commands import (
    ClearConversationAction,
    ClearDefaultModelAction,
    CompactThreadAction,
    ExitAction,
    OpenUrlAction,
    SetDefaultModelAction,
    SetThreadAction,
    ShowMessageAction,
    ShowModelSelectorAction,
    ShowThreadSelectorAction,
    SubmitUserMessageAction,
    SwitchModelAction,
    build_help_text,
    build_remember_prompt,
    build_token_usage_message,
    execute_parsed_slash_command,
    execute_parsed_slash_command_async,
    parse_slash_command,
    resolve_command_url,
)


class TestParseSlashCommand:
    def test_help_command(self):
        parsed = parse_slash_command("/help")

        assert parsed.kind == "help"
        assert parsed.normalized == "/help"

    def test_open_url_command(self):
        parsed = parse_slash_command("/docs")

        assert parsed.kind == "open_url"
        assert parsed.url_key == "/docs"

    def test_remember_command_preserves_context_casing(self):
        parsed = parse_slash_command("/remember Keep Project-Specific Notes")

        assert parsed.kind == "remember"
        assert parsed.argument == "Keep Project-Specific Notes"

    def test_model_selector_command(self):
        parsed = parse_slash_command("/model")

        assert parsed.kind == "model_selector"

    def test_model_switch_command(self):
        parsed = parse_slash_command("/model claude-sonnet-4-5")

        assert parsed.kind == "model_switch"
        assert parsed.argument == "claude-sonnet-4-5"

    def test_model_set_default_command(self):
        parsed = parse_slash_command("/model --default anthropic:claude-opus-4-1")

        assert parsed.kind == "model_set_default"
        assert parsed.argument == "anthropic:claude-opus-4-1"

    def test_model_clear_default_command(self):
        parsed = parse_slash_command("/model --default --clear")

        assert parsed.kind == "model_clear_default"

    def test_model_default_usage_command(self):
        parsed = parse_slash_command("/model --default")

        assert parsed.kind == "model_default_usage"

    def test_unknown_command(self):
        parsed = parse_slash_command("/wat")

        assert parsed.kind == "unknown"
        assert parsed.normalized == "/wat"


class TestCommandHelpers:
    def test_build_help_text_includes_docs_url(self):
        help_text = build_help_text("https://example.com/docs")

        assert "Commands: /quit" in help_text
        assert "https://example.com/docs" in help_text

    def test_build_token_usage_message_with_usage(self):
        message = build_token_usage_message(
            current_context=12_500,
            model_name="gpt-test",
            context_limit=100_000,
            conversation_line="Conversation only: 4.2K",
        )

        assert "12.5K / 100.0K tokens" in message
        assert "gpt-test" in message
        assert "Conversation only: 4.2K" in message

    def test_build_token_usage_message_without_usage(self):
        message = build_token_usage_message(
            current_context=0,
            model_name="gpt-test",
            context_limit=200_000,
        )

        assert message == "No token usage yet · 200.0K context window · gpt-test"

    def test_build_remember_prompt_without_context(self):
        prompt = build_remember_prompt("base prompt")

        assert prompt == "base prompt"

    def test_build_remember_prompt_with_context(self):
        prompt = build_remember_prompt("base prompt", "Focus on tests")

        assert "base prompt" in prompt
        assert "Focus on tests" in prompt


class TestCommandService:
    def test_resolve_command_url_returns_docs_url(self):
        assert (
            resolve_command_url("/docs", docs_url="https://example.com/docs")
            == "https://example.com/docs"
        )

    def test_resolve_command_url_returns_static_urls(self):
        assert resolve_command_url("/changelog", docs_url="x") is not None
        assert resolve_command_url("/feedback", docs_url="x") is not None

    def test_execute_quit_returns_exit_action(self):
        parsed = parse_slash_command("/q")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is False
        assert execution.actions == (ExitAction(),)

    def test_execute_help_returns_message_action(self):
        parsed = parse_slash_command("/help")
        execution = execute_parsed_slash_command(
            parsed,
            docs_url="https://example.com/docs",
        )

        assert execution is not None
        assert execution.echo_command is True
        assert len(execution.actions) == 1
        action = execution.actions[0]
        assert isinstance(action, ShowMessageAction)
        assert action.style == "dim italic"
        assert action.link_url == "https://example.com/docs"
        assert "Commands: /quit" in action.message
        assert "https://example.com/docs" in action.message

    def test_execute_docs_returns_open_url_action(self):
        parsed = parse_slash_command("/docs")
        execution = execute_parsed_slash_command(
            parsed,
            docs_url="https://example.com/docs",
        )

        assert execution is not None
        assert execution.echo_command is True
        assert len(execution.actions) == 1
        action = execution.actions[0]
        assert isinstance(action, OpenUrlAction)
        assert action.url == "https://example.com/docs"

    def test_execute_model_default_usage_returns_message(self):
        parsed = parse_slash_command("/model --default")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is True
        assert len(execution.actions) == 1
        action = execution.actions[0]
        assert isinstance(action, ShowMessageAction)
        assert "Usage: /model --default provider:model" in action.message

    def test_execute_unknown_returns_message(self):
        parsed = parse_slash_command("/wat")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is True
        assert len(execution.actions) == 1
        action = execution.actions[0]
        assert isinstance(action, ShowMessageAction)
        assert action.message == "Unknown command: /wat"

    def test_execute_version_returns_message(self) -> None:
        parsed = parse_slash_command("/version")

        with patch("importlib.metadata.version", return_value="1.2.3"):
            execution = execute_parsed_slash_command(
                parsed,
                docs_url="https://example.com",
                client_version="9.9.9",
            )

        assert execution is not None
        assert execution.echo_command is True
        assert len(execution.actions) == 1
        action = execution.actions[0]
        assert isinstance(action, ShowMessageAction)
        assert "deepagents-cli version: 9.9.9" in action.message
        assert "deepagents (SDK) version: 1.2.3" in action.message

    def test_execute_version_shows_unknown_when_sdk_unavailable(self) -> None:
        parsed = parse_slash_command("/version")

        def patched_version(name: str) -> str:
            raise importlib.metadata.PackageNotFoundError(name)

        with patch("importlib.metadata.version", side_effect=patched_version):
            execution = execute_parsed_slash_command(
                parsed,
                docs_url="https://example.com",
                client_version=None,
            )

        assert execution is not None
        assert execution.echo_command is True
        assert len(execution.actions) == 1
        action = execution.actions[0]
        assert isinstance(action, ShowMessageAction)
        assert "deepagents-cli version: unknown" in action.message
        assert "deepagents (SDK) version: unknown" in action.message

    def test_execute_clear_returns_actions(self) -> None:
        parsed = parse_slash_command("/clear")

        with patch(
            "deepagents_runtime.commands._generate_thread_id",
            return_value="deadbeef",
        ):
            execution = execute_parsed_slash_command(
                parsed,
                docs_url="https://example.com",
            )

        assert execution is not None
        assert execution.echo_command is False
        assert execution.actions == (
            ClearConversationAction(),
            SetThreadAction("deadbeef"),
            ShowMessageAction("Started new thread: deadbeef"),
        )

    def test_execute_threads_returns_thread_selector_action(self) -> None:
        parsed = parse_slash_command("/threads")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is False
        assert execution.actions == (ShowThreadSelectorAction(),)

    def test_execute_compact_returns_compact_thread_action(self) -> None:
        parsed = parse_slash_command("/compact")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is True
        assert execution.actions == (CompactThreadAction(),)

    def test_execute_model_selector_returns_model_selector_action(self) -> None:
        parsed = parse_slash_command("/model")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is False
        assert execution.actions == (ShowModelSelectorAction(),)

    def test_execute_model_switch_returns_action(self) -> None:
        parsed = parse_slash_command("/model claude-sonnet-4-5")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is True
        assert execution.actions == (SwitchModelAction("claude-sonnet-4-5"),)

    def test_execute_model_set_default_returns_action(self) -> None:
        parsed = parse_slash_command("/model --default anthropic:claude-opus-4-1")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is True
        assert execution.actions == (
            SetDefaultModelAction("anthropic:claude-opus-4-1"),
        )

    def test_execute_model_clear_default_returns_action(self) -> None:
        parsed = parse_slash_command("/model --default --clear")
        execution = execute_parsed_slash_command(parsed, docs_url="https://example.com")

        assert execution is not None
        assert execution.echo_command is True
        assert execution.actions == (ClearDefaultModelAction(),)

    def test_execute_remember_returns_submit_message_action(self) -> None:
        parsed = parse_slash_command("/remember Focus on tests")

        with patch(
            "deepagents_runtime.commands.REMEMBER_PROMPT",
            "base prompt",
        ):
            execution = execute_parsed_slash_command(
                parsed,
                docs_url="https://example.com",
            )

        assert execution is not None
        assert execution.echo_command is False
        assert len(execution.actions) == 1
        action = execution.actions[0]
        assert isinstance(action, SubmitUserMessageAction)
        assert "base prompt" in action.message
        assert "Additional context from user" in action.message
        assert "Focus on tests" in action.message

    async def test_execute_trace_without_session_returns_message(self) -> None:
        parsed = parse_slash_command("/trace")
        execution = await execute_parsed_slash_command_async(
            parsed,
            docs_url="https://example.com",
            thread_id=None,
        )

        assert execution is not None
        assert execution.echo_command is True
        assert execution.actions == (ShowMessageAction("No active session."),)

    async def test_execute_trace_returns_open_url_action_when_configured(self) -> None:
        parsed = parse_slash_command("/trace")

        with patch(
            "deepagents_runtime.tracing.build_langsmith_thread_url",
            return_value="https://smith.langchain.com/t/test-thread",
        ):
            execution = await execute_parsed_slash_command_async(
                parsed,
                docs_url="https://example.com",
                thread_id="test-thread",
            )

        assert execution is not None
        assert execution.echo_command is True
        assert execution.actions == (
            OpenUrlAction("https://smith.langchain.com/t/test-thread"),
        )

    async def test_execute_trace_shows_hint_when_not_configured(self) -> None:
        parsed = parse_slash_command("/trace")

        with patch(
            "deepagents_runtime.tracing.build_langsmith_thread_url",
            return_value=None,
        ):
            execution = await execute_parsed_slash_command_async(
                parsed,
                docs_url="https://example.com",
                thread_id="test-thread",
            )

        assert execution is not None
        assert execution.echo_command is True
        assert len(execution.actions) == 1
        action = execution.actions[0]
        assert isinstance(action, ShowMessageAction)
        assert "LANGSMITH_API_KEY" in action.message

    async def test_execute_trace_shows_error_when_url_build_raises(self) -> None:
        parsed = parse_slash_command("/trace")

        with patch(
            "deepagents_runtime.tracing.build_langsmith_thread_url",
            side_effect=RuntimeError("boom"),
        ):
            execution = await execute_parsed_slash_command_async(
                parsed,
                docs_url="https://example.com",
                thread_id="test-thread",
            )

        assert execution is not None
        assert execution.echo_command is True
        assert execution.actions == (
            ShowMessageAction("Failed to resolve LangSmith thread URL."),
        )
