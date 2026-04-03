"""Middleware for tracking file artifacts produced by agent tool calls."""

from __future__ import annotations

import posixpath
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class ArtifactEntry(TypedDict):
    """Metadata for one artifact produced by an agent."""

    type: str
    """Artifact type, currently always "file"."""

    path: str
    """Workspace-relative path."""

    title: str
    """Display name (typically the filename)."""

    content_type: str
    """MIME-like content type, e.g. "code/python", "text/markdown"."""

    language: str
    """Programming language if applicable, otherwise empty string."""

    created_by_tool: str
    """Name of the tool that produced this artifact."""

    created_at: str
    """ISO 8601 timestamp of first creation."""

    modified_at: str
    """ISO 8601 timestamp of last modification."""

    size: int
    """File size in bytes (0 if unknown)."""


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------

def _artifact_reducer(
    left: dict[str, ArtifactEntry] | None,
    right: dict[str, ArtifactEntry | None],
) -> dict[str, ArtifactEntry]:
    """Merge artifact updates with support for deletions via ``None`` values."""
    if left is None:
        return {k: v for k, v in right.items() if v is not None}

    result = {**left}
    for key, value in right.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ArtifactsState(AgentState):
    """State channel for artifact tracking."""

    artifacts: Annotated[NotRequired[dict[str, ArtifactEntry]], _artifact_reducer]


# ---------------------------------------------------------------------------
# Language / content-type inference
# ---------------------------------------------------------------------------

_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".lua": "lua",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".tex": "latex",
    ".proto": "protobuf",
}


def _infer_language(path: str) -> str:
    """Return a language identifier from the file extension, or ``""``."""
    ext = posixpath.splitext(path)[1].lower()
    return _EXTENSION_LANGUAGE_MAP.get(ext, "")


def _infer_content_type(path: str) -> str:
    """Return a coarse content-type string from the file extension."""
    lang = _infer_language(path)
    if lang in {"markdown", "restructuredtext", "latex"}:
        return f"text/{lang}"
    if lang:
        return f"code/{lang}"
    ext = posixpath.splitext(path)[1].lower()
    if ext in {".txt", ".log", ".csv"}:
        return "text/plain"
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

_TRACKED_TOOLS = frozenset({"write_file", "edit_file"})


class ArtifactsMiddleware(AgentMiddleware[ArtifactsState, Any, Any]):
    """Observes write_file / edit_file results and records artifact metadata.

    This middleware carries no tools of its own.  It sits after
    ``FilesystemMiddleware`` in the middleware stack and uses
    ``wrap_tool_call`` to inspect results.  On success it augments the
    result with an ``artifacts`` state update so that artifact metadata
    is persisted in the checkpoint.

    Artifact dict keys are the workspace-relative **path**, which gives
    natural deduplication when the same file is edited multiple times.
    """

    state_schema = ArtifactsState
    tools: list[Any] = []  # type: ignore[assignment]

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        result = handler(request)

        tool_name: str = request.tool_call.get("name", "")
        if tool_name not in _TRACKED_TOOLS:
            return result

        return self._maybe_track_artifact(tool_name, request, result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)

        tool_name: str = request.tool_call.get("name", "")
        if tool_name not in _TRACKED_TOOLS:
            return result

        return self._maybe_track_artifact(tool_name, request, result)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _maybe_track_artifact(
        tool_name: str,
        request: ToolCallRequest,
        result: ToolMessage | Command,
    ) -> ToolMessage | Command:
        now = datetime.now(UTC).isoformat()

        # --- Case 1: Command with files update (state backend) ----------
        if isinstance(result, Command) and result.update:
            files_update = result.update.get("files")
            if isinstance(files_update, dict) and files_update:
                artifacts: dict[str, ArtifactEntry | None] = {}
                for path, file_data in files_update.items():
                    if file_data is None:
                        continue
                    created_at = (
                        file_data.get("created_at", now)
                        if isinstance(file_data, dict)
                        else now
                    )
                    modified_at = (
                        file_data.get("modified_at", now)
                        if isinstance(file_data, dict)
                        else now
                    )
                    file_content = (
                        file_data.get("content", "")
                        if isinstance(file_data, dict)
                        else ""
                    )
                    file_size = len(file_content.encode("utf-8")) if isinstance(file_content, str) else 0
                    artifacts[path] = ArtifactEntry(
                        type="file",
                        path=path,
                        title=posixpath.basename(path),
                        content_type=_infer_content_type(path),
                        language=_infer_language(path),
                        created_by_tool=tool_name,
                        created_at=created_at,
                        modified_at=modified_at,
                        size=file_size,
                    )
                if artifacts:
                    return Command(update={**result.update, "artifacts": artifacts})
            return result

        # --- Case 2: ToolMessage (sandbox backend, no files_update) -----
        if isinstance(result, ToolMessage):
            content = result.content if isinstance(result.content, str) else ""
            if content.startswith("Error"):
                return result

            file_path: str = request.tool_call.get("args", {}).get("file_path", "")
            if not file_path:
                return result

            file_content: str = request.tool_call.get("args", {}).get("content", "")
            file_size = len(file_content.encode("utf-8")) if file_content else 0

            artifact_entry = ArtifactEntry(
                type="file",
                path=file_path,
                title=posixpath.basename(file_path),
                content_type=_infer_content_type(file_path),
                language=_infer_language(file_path),
                created_by_tool=tool_name,
                created_at=now,
                modified_at=now,
                size=file_size,
            )
            return Command(
                update={
                    "artifacts": {file_path: artifact_entry},
                    "messages": [result],
                },
            )

        return result
