"""Shell command helpers shared across clients.

This module intentionally avoids any UI dependencies. It owns the behavior
that should remain consistent across Textual and future browser clients.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress

logger = logging.getLogger(__name__)


def format_shell_output(stdout_bytes: bytes | None, stderr_bytes: bytes | None) -> str:
    """Format subprocess stdout/stderr into a single display string.

    The CLI renders direct `!command` output inside a fenced code block, so this
    helper only concerns itself with decoding and merging stdout/stderr.

    Args:
        stdout_bytes: Raw stdout bytes, if any.
        stderr_bytes: Raw stderr bytes, if any.

    Returns:
        Combined output string suitable for embedding into a message.
    """
    output = (stdout_bytes or b"").decode(errors="replace").strip()
    stderr_text = (stderr_bytes or b"").decode(errors="replace").strip()
    if stderr_text:
        if output:
            output += "\n"
        output += f"[stderr]\n{stderr_text}"
    return output


async def terminate_shell_process(
    proc: asyncio.subprocess.Process,
    *,
    platform: str,
) -> None:
    """Terminate a running shell subprocess, escalating to SIGKILL when needed.

    On POSIX we terminate the entire process group (when `start_new_session=True`)
    to avoid orphaned children. On Windows we can only terminate the root process.

    Args:
        proc: Running subprocess handle.
        platform: `sys.platform`-style identifier (passed in by the client).
    """
    if proc.returncode is not None:
        return

    try:
        if platform != "win32":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        return
    except OSError:
        logger.warning(
            "Failed to terminate shell process (pid=%s)", proc.pid, exc_info=True
        )
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except TimeoutError:
        logger.warning(
            "Shell process (pid=%s) did not exit after SIGTERM; sending SIGKILL",
            proc.pid,
        )
        sigkill = getattr(signal, "SIGKILL", None)
        with suppress(ProcessLookupError, OSError):
            if platform != "win32" and sigkill is not None:
                os.killpg(os.getpgid(proc.pid), sigkill)
            else:
                proc.kill()
        with suppress(ProcessLookupError, OSError):
            await proc.wait()
    except (ProcessLookupError, OSError):
        pass
