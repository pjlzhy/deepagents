"""Thread-bound runtime backend adapters.

Expose one thread workspace as the primary working directory for both shell and
file tools, while keeping hidden runtime resources under `.runtime/`.
"""

from __future__ import annotations

import posixpath
import shlex
from pathlib import Path
from typing import cast

from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
    execute_accepts_timeout,
)


def normalize_relative_runtime_path(path: str | None, *, default: str = ".") -> str:
    """Normalize one runtime-relative path and reject traversal."""
    candidate = default if path is None else path.strip()
    if not candidate:
        candidate = default
    candidate = candidate.replace("\\", "/")
    if candidate.startswith("/"):
        raise ValueError("runtime paths must be relative")
    if candidate.startswith("~"):
        raise ValueError("runtime paths must not start with ~")

    normalized = posixpath.normpath(candidate)
    if normalized in {"..", "/.."} or normalized.startswith("../"):
        raise ValueError("runtime paths must not contain traversal")
    return "." if normalized in {"", "."} else normalized


def normalize_runtime_upload_path(path: str) -> str:
    """Normalize one uploaded filename/path inside the thread workspace."""
    normalized = normalize_relative_runtime_path(path)
    if normalized == ".":
        raise ValueError("workspace upload path must not be empty")
    return normalized


def _actual_child_path(root: str, relative_path: str) -> str:
    if relative_path == ".":
        return root
    return posixpath.join(root, relative_path)


def _strip_actual_root(path: str, actual_root: str) -> str:
    normalized_path = posixpath.normpath(path)
    normalized_root = posixpath.normpath(actual_root)
    if normalized_path == normalized_root:
        return "."
    root_with_sep = normalized_root.rstrip("/") + "/"
    if normalized_path.startswith(root_with_sep):
        return normalized_path[len(root_with_sep):]
    return normalized_path


def _remap_file_info(item: FileInfo, actual_root: str) -> FileInfo:
    path = str(item.get("path", ""))
    is_dir = bool(item.get("is_dir"))
    relative = _strip_actual_root(path.rstrip("/"), actual_root)
    if is_dir and relative != ".":
        relative += "/"
    return FileInfo(
        path=relative,
        is_dir=item.get("is_dir"),
        size=item.get("size"),
        modified_at=item.get("modified_at"),
    )


def _remap_grep_match(item: GrepMatch, actual_root: str) -> GrepMatch:
    return cast(
        GrepMatch,
        {
            **item,
            "path": _strip_actual_root(item["path"], actual_root),
        },
    )


class ThreadRuntimeBackend(SandboxBackendProtocol):
    """Backend view rooted at one thread workspace."""

    def __init__(
        self,
        *,
        shell_backend: SandboxBackendProtocol,
        actual_root: str,
        execute_command_prefix: str,
    ) -> None:
        self._shell_backend = shell_backend
        self._actual_root = actual_root
        self._execute_command_prefix = execute_command_prefix

    @property
    def id(self) -> str:
        return self._shell_backend.id

    @classmethod
    def for_local(
        cls,
        *,
        shell_backend: LocalShellBackend,
        thread_root_dir: Path,
    ) -> ThreadRuntimeBackend:
        actual_root = str(thread_root_dir.resolve())
        execute_command_prefix = f"cd {shlex.quote(actual_root)} && "
        return cls(
            shell_backend=shell_backend,
            actual_root=actual_root,
            execute_command_prefix=execute_command_prefix,
        )

    @classmethod
    def for_container(
        cls,
        *,
        sandbox_backend: SandboxBackendProtocol,
        thread_root_path: str,
    ) -> ThreadRuntimeBackend:
        actual_root = posixpath.normpath(thread_root_path)
        execute_command_prefix = f"cd {shlex.quote(actual_root)} && "
        return cls(
            shell_backend=sandbox_backend,
            actual_root=actual_root,
            execute_command_prefix=execute_command_prefix,
        )

    def ls_info(self, path: str) -> list[FileInfo]:
        relative = normalize_relative_runtime_path(path)
        infos = self._shell_backend.ls_info(_actual_child_path(self._actual_root, relative))
        return [_remap_file_info(item, self._actual_root) for item in infos]

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        relative = normalize_relative_runtime_path(file_path)
        return self._shell_backend.read(
            _actual_child_path(self._actual_root, relative),
            offset=offset,
            limit=limit,
        )

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        relative = normalize_relative_runtime_path(path, default=".")
        raw = self._shell_backend.grep_raw(
            pattern,
            path=_actual_child_path(self._actual_root, relative),
            glob=glob,
        )
        if isinstance(raw, str):
            return raw
        return [_remap_grep_match(item, self._actual_root) for item in raw]

    def glob_info(self, pattern: str, path: str = ".") -> list[FileInfo]:
        relative = normalize_relative_runtime_path(path)
        infos = self._shell_backend.glob_info(
            pattern,
            path=_actual_child_path(self._actual_root, relative),
        )
        return [_remap_file_info(item, self._actual_root) for item in infos]

    def write(self, file_path: str, content: str) -> WriteResult:
        relative = normalize_relative_runtime_path(file_path)
        result = self._shell_backend.write(
            _actual_child_path(self._actual_root, relative),
            content,
        )
        if result.path is not None:
            result.path = relative
        return result

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        relative = normalize_relative_runtime_path(file_path)
        result = self._shell_backend.edit(
            _actual_child_path(self._actual_root, relative),
            old_string,
            new_string,
            replace_all=replace_all,
        )
        if result.path is not None:
            result.path = relative
        return result

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        translated: list[tuple[str, bytes]] = []
        indexes: list[int] = []
        for index, (path, content) in enumerate(files):
            try:
                relative = normalize_runtime_upload_path(path)
            except ValueError:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
                continue
            translated.append((_actual_child_path(self._actual_root, relative), content))
            indexes.append(index)
            responses.append(None)  # type: ignore[arg-type]

        backend_responses = self._shell_backend.upload_files(translated)
        for order, backend_response in enumerate(backend_responses):
            original_index = indexes[order]
            original_path = files[original_index][0]
            normalized_path = normalize_runtime_upload_path(original_path)
            responses[original_index] = FileUploadResponse(
                path=normalized_path,
                error=backend_response.error,
            )
        return cast(list[FileUploadResponse], responses)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse | None] = [None] * len(paths)
        translated: list[str] = []
        indexes: list[int] = []
        for index, path in enumerate(paths):
            try:
                relative = normalize_relative_runtime_path(path)
            except ValueError:
                responses[index] = FileDownloadResponse(
                    path=path,
                    content=None,
                    error="invalid_path",
                )
                continue
            translated.append(_actual_child_path(self._actual_root, relative))
            indexes.append(index)

        backend_responses = self._shell_backend.download_files(translated)
        for order, backend_response in enumerate(backend_responses):
            original_index = indexes[order]
            original_path = normalize_relative_runtime_path(paths[original_index])
            responses[original_index] = FileDownloadResponse(
                path=original_path,
                content=backend_response.content,
                error=backend_response.error,
            )
        return cast(list[FileDownloadResponse], responses)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        wrapped = self._execute_command_prefix + command
        if timeout is not None and execute_accepts_timeout(type(self._shell_backend)):
            return self._shell_backend.execute(wrapped, timeout=timeout)
        return self._shell_backend.execute(wrapped)
