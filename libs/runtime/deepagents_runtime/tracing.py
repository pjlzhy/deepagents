"""Tracing helpers shared across clients.

Currently this focuses on LangSmith trace URL resolution for a thread.

The runtime intentionally treats LangSmith as optional: if the `langsmith`
package is not installed or tracing env vars are not configured, these helpers
return `None` rather than raising.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)


_LANGSMITH_URL_LOOKUP_TIMEOUT_SECONDS = 2.0

_langsmith_url_cache: tuple[str, str] | None = None


def get_langsmith_project_name() -> str | None:
    """Resolve the LangSmith project name if tracing is configured.

    Returns:
        Project name string when LangSmith tracing is active, `None` otherwise.
    """
    langsmith_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get(
        "LANGCHAIN_API_KEY"
    )
    langsmith_tracing = os.environ.get("LANGSMITH_TRACING") or os.environ.get(
        "LANGCHAIN_TRACING_V2"
    )
    if not (langsmith_key and langsmith_tracing):
        return None

    return (
        os.environ.get("DEEPAGENTS_LANGSMITH_PROJECT")
        or os.environ.get("LANGSMITH_PROJECT")
        or "default"
    )


def reset_langsmith_url_cache() -> None:
    """Reset the LangSmith project URL cache (for testing)."""
    global _langsmith_url_cache  # noqa: PLW0603  # Module-level cache requires global statement
    _langsmith_url_cache = None


def fetch_langsmith_project_url(project_name: str) -> str | None:
    """Fetch the LangSmith project URL via the LangSmith client.

    Successful results are cached at module level so repeated calls do not make
    additional network requests.

    The network call runs in a daemon thread with a hard timeout of
    `_LANGSMITH_URL_LOOKUP_TIMEOUT_SECONDS`, so this function blocks the calling
    thread for at most that duration even if LangSmith is unreachable.

    Args:
        project_name: LangSmith project name to look up.

    Returns:
        Project URL string if found, `None` otherwise.
    """
    global _langsmith_url_cache  # noqa: PLW0603  # Module-level cache requires global statement

    if _langsmith_url_cache is not None:
        cached_name, cached_url = _langsmith_url_cache
        if cached_name == project_name:
            return cached_url

    try:
        from langsmith import Client
    except ImportError:
        logger.debug(
            "Could not fetch LangSmith project URL for '%s'",
            project_name,
            exc_info=True,
        )
        return None

    result: str | None = None
    lookup_error: Exception | None = None
    done = threading.Event()

    def _lookup_url() -> None:
        nonlocal result, lookup_error
        try:
            project = Client().read_project(project_name=project_name)
            result = project.url or None
        except Exception as exc:  # noqa: BLE001  # LangSmith SDK error types are not stable
            lookup_error = exc
        finally:
            done.set()

    thread = threading.Thread(target=_lookup_url, daemon=True)
    thread.start()

    if not done.wait(_LANGSMITH_URL_LOOKUP_TIMEOUT_SECONDS):
        logger.debug(
            "Timed out fetching LangSmith project URL for '%s' after %.1fs",
            project_name,
            _LANGSMITH_URL_LOOKUP_TIMEOUT_SECONDS,
        )
        return None

    if lookup_error is not None:
        logger.debug(
            "Could not fetch LangSmith project URL for '%s'",
            project_name,
            exc_info=(type(lookup_error), lookup_error, lookup_error.__traceback__),
        )
        return None

    if result is not None:
        _langsmith_url_cache = (project_name, result)
    return result


def build_langsmith_thread_url(thread_id: str) -> str | None:
    """Build a full LangSmith thread URL if tracing is configured.

    Args:
        thread_id: Thread identifier to build the URL for.

    Returns:
        Full thread URL string, or `None` if unavailable.
    """
    project_name = get_langsmith_project_name()
    if not project_name:
        return None

    project_url = fetch_langsmith_project_url(project_name)
    if not project_url:
        return None

    return f"{project_url.rstrip('/')}/t/{thread_id}?utm_source=deepagents-cli"
