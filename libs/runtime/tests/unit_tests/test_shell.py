import signal
from unittest.mock import AsyncMock, patch

from deepagents_runtime.shell import format_shell_output, terminate_shell_process


class TestShellOutputFormatting:
    def test_format_shell_output_combines_stderr(self) -> None:
        output = format_shell_output(
            b"hello stdout\n",
            b"warn stderr\n",
        )

        assert output == "hello stdout\n[stderr]\nwarn stderr"

    def test_format_shell_output_handles_empty_streams(self) -> None:
        assert format_shell_output(None, None) == ""
        assert format_shell_output(b"", b"") == ""


class TestShellTermination:
    async def test_terminate_shell_process_posix_uses_killpg(self) -> None:
        proc = AsyncMock()
        proc.returncode = None
        proc.pid = 42
        proc.wait = AsyncMock()

        with (
            patch("os.killpg", create=True) as mock_killpg,
            patch("os.getpgid", return_value=42, create=True) as mock_getpgid,
        ):
            await terminate_shell_process(proc, platform="linux")

        mock_getpgid.assert_called_once_with(42)
        mock_killpg.assert_called_once_with(42, signal.SIGTERM)
