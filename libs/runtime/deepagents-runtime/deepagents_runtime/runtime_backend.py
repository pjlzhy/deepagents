"""Thread-scoped runtime backend adapters.

These adapters present one stable virtual filesystem contract to agents:

- `/workspace/...` for per-thread uploaded/generated files
- `/memory/...` for agent memory
- `/skills/...` for synced skills
- `/conversation_history/...` for summarization offloads

Shell execution always starts in the current thread's workspace. This keeps
the file-tool contract explicit while letting shell commands use natural
relative paths.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import posixpath
import shlex
from typing import cast

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.protocol import (
    BackendProtocol,
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


_VISIBLE_WORKSPACE_PREFIX = "/workspace"
_VISIBLE_MEMORY_PREFIX = "/memory"
_VISIBLE_SKILLS_PREFIX = "/skills"
_VISIBLE_HISTORY_PREFIX = "/conversation_history"
_VISIBLE_ROOTS = (
    _VISIBLE_HISTORY_PREFIX,
    _VISIBLE_MEMORY_PREFIX,
    _VISIBLE_SKILLS_PREFIX,
    _VISIBLE_WORKSPACE_PREFIX,
)


def _normalize_thread_id(thread_id: str) -> str:
    normalized = thread_id.strip()
    if not normalized:
        raise ValueError("thread_id must not be empty")
    if "/" in normalized or "\\" in normalized:
        raise ValueError("thread_id must not contain path separators")
    if normalized in {".", ".."}:
        raise ValueError("thread_id must not be a traversal segment")
    return normalized


def _normalize_visible_path(path: str) -> str:
    normalized = path.strip()
    if not normalized.startswith("/"):
        msg = f"path must be absolute, got {path!r}"
        raise ValueError(msg)
    normalized = posixpath.normpath(normalized)
    if normalized == "/..":
        raise ValueError("path traversal is not allowed")
    if normalized.startswith("/../"):
        raise ValueError("path traversal is not allowed")
    return normalized


def _suffix_for_prefix(path: str, prefix: str) -> str | None:
    if path == prefix:
        return "/"
    boundary = prefix + "/"
    if path.startswith(boundary):
        suffix = path[len(prefix):]
        return suffix if suffix.startswith("/") else "/" + suffix
    return None


def _prefix_backend_path(prefix: str, backend_path: str) -> str:
    normalized = backend_path if backend_path.startswith("/") else "/" + backend_path
    if normalized == "/":
        return prefix
    return prefix + normalized


def _strip_actual_root(path: str, actual_root: str) -> str:
    normalized_path = posixpath.normpath(path)
    normalized_root = posixpath.normpath(actual_root)
    if normalized_path == normalized_root:
        return "/"
    root_with_sep = normalized_root.rstrip("/") + "/"
    if normalized_path.startswith(root_with_sep):
        suffix = normalized_path[len(normalized_root):]
        return suffix if suffix.startswith("/") else "/" + suffix
    return normalized_path


@dataclass(frozen=True)
class _VisibleRoute:
    """One routed virtual filesystem subtree."""

    prefix: str
    backend_getter: Callable[[], BackendProtocol]
    to_backend_path: Callable[[str], str]
    from_backend_path: Callable[[str], str]

    def match(self, path: str) -> str | None:
        return _suffix_for_prefix(path, self.prefix)


class ThreadScopedRuntimeBackend(SandboxBackendProtocol):
    """Expose thread-scoped workspace semantics on top of a concrete backend."""

    def __init__(
        self,
        *,
        shell_backend: SandboxBackendProtocol,
        memory_backend: BackendProtocol,
        skills_backend: BackendProtocol,
        history_backend: BackendProtocol | None,
        shell_execute: Callable[[str, int | None], ExecuteResponse],
        bind_thread: Callable[[str], None],
        workspace_route: _VisibleRoute,
        history_route: _VisibleRoute,
        memory_route: _VisibleRoute,
        skills_route: _VisibleRoute,
    ) -> None:
        self._shell_backend = shell_backend
        self._memory_backend = memory_backend
        self._skills_backend = skills_backend
        self._history_backend = history_backend
        self._shell_execute = shell_execute
        self._bind_thread_callback = bind_thread
        self._workspace_route = workspace_route
        self._history_route = history_route
        self._memory_route = memory_route
        self._skills_route = skills_route
        self._routes = (
            self._workspace_route,
            self._memory_route,
            self._skills_route,
            self._history_route,
        )
        self._current_thread_id: str | None = None

    @property
    def id(self) -> str:
        return self._shell_backend.id

    @classmethod
    def for_local(
        cls,
        *,
        workspace_root_dir: Path,
        history_root_dir: Path,
        memory_file: Path,
        skills_root_dir: Path,
        inherit_env: bool = True,
    ) -> ThreadScopedRuntimeBackend:
        shell_backend = LocalShellBackend(
            root_dir=workspace_root_dir,
            inherit_env=inherit_env,
            virtual_mode=True,
        )
        history_backend = FilesystemBackend(
            root_dir=history_root_dir,
            virtual_mode=True,
        )
        memory_backend = FilesystemBackend(
            root_dir=memory_file.parent,
            virtual_mode=True,
        )
        skills_backend = FilesystemBackend(
            root_dir=skills_root_dir,
            virtual_mode=True,
        )

        def bind_thread(thread_id: str) -> None:
            normalized = _normalize_thread_id(thread_id)
            workspace_dir = (workspace_root_dir / normalized).resolve()
            history_dir = (history_root_dir / normalized).resolve()
            workspace_dir.mkdir(parents=True, exist_ok=True)
            history_dir.mkdir(parents=True, exist_ok=True)
            shell_backend.cwd = workspace_dir
            history_backend.cwd = history_dir

        return cls(
            shell_backend=shell_backend,
            memory_backend=memory_backend,
            skills_backend=skills_backend,
            history_backend=history_backend,
            shell_execute=lambda command, timeout: shell_backend.execute(
                command,
                timeout=timeout,
            ) if timeout is not None else shell_backend.execute(command),
            bind_thread=bind_thread,
            workspace_route=_VisibleRoute(
                prefix=_VISIBLE_WORKSPACE_PREFIX,
                backend_getter=lambda: shell_backend,
                to_backend_path=lambda suffix: suffix,
                from_backend_path=lambda backend_path: _prefix_backend_path(
                    _VISIBLE_WORKSPACE_PREFIX,
                    backend_path,
                ),
            ),
            history_route=_VisibleRoute(
                prefix=_VISIBLE_HISTORY_PREFIX,
                backend_getter=lambda: history_backend,
                to_backend_path=lambda suffix: suffix,
                from_backend_path=lambda backend_path: _prefix_backend_path(
                    _VISIBLE_HISTORY_PREFIX,
                    backend_path,
                ),
            ),
            memory_route=_VisibleRoute(
                prefix=_VISIBLE_MEMORY_PREFIX,
                backend_getter=lambda: memory_backend,
                to_backend_path=lambda suffix: suffix,
                from_backend_path=lambda backend_path: _prefix_backend_path(
                    _VISIBLE_MEMORY_PREFIX,
                    backend_path,
                ),
            ),
            skills_route=_VisibleRoute(
                prefix=_VISIBLE_SKILLS_PREFIX,
                backend_getter=lambda: skills_backend,
                to_backend_path=lambda suffix: suffix,
                from_backend_path=lambda backend_path: _prefix_backend_path(
                    _VISIBLE_SKILLS_PREFIX,
                    backend_path,
                ),
            ),
        )

    @classmethod
    def for_container(
        cls,
        *,
        sandbox_backend: SandboxBackendProtocol,
        container_root: str,
    ) -> ThreadScopedRuntimeBackend:
        normalized_root = posixpath.normpath(container_root)
        current_thread: dict[str, str | None] = {"value": None}

        def require_thread() -> str:
            thread_id = current_thread["value"]
            if thread_id is None:
                raise RuntimeError("thread workspace is not bound")
            return thread_id

        def bind_thread(thread_id: str) -> None:
            current_thread["value"] = _normalize_thread_id(thread_id)

        def workspace_root() -> str:
            return posixpath.join(normalized_root, "workspace", require_thread())

        def history_root() -> str:
            return posixpath.join(
                normalized_root,
                "conversation_history",
                require_thread(),
            )

        def to_actual(base: Callable[[], str], suffix: str) -> str:
            root = base()
            if suffix == "/":
                return root
            return posixpath.join(root, suffix.lstrip("/"))

        def from_actual(base: Callable[[], str], prefix: str, backend_path: str) -> str:
            return _prefix_backend_path(
                prefix,
                _strip_actual_root(backend_path, base()),
            )

        def shell_execute(command: str, timeout: int | None) -> ExecuteResponse:
            workspace_dir = workspace_root()
            wrapped = f"cd {shlex.quote(workspace_dir)} && {command}"
            if timeout is not None and execute_accepts_timeout(type(sandbox_backend)):
                return sandbox_backend.execute(wrapped, timeout=timeout)
            return sandbox_backend.execute(wrapped)

        return cls(
            shell_backend=sandbox_backend,
            memory_backend=sandbox_backend,
            skills_backend=sandbox_backend,
            history_backend=sandbox_backend,
            shell_execute=shell_execute,
            bind_thread=bind_thread,
            workspace_route=_VisibleRoute(
                prefix=_VISIBLE_WORKSPACE_PREFIX,
                backend_getter=lambda: sandbox_backend,
                to_backend_path=lambda suffix: to_actual(workspace_root, suffix),
                from_backend_path=lambda backend_path: from_actual(
                    workspace_root,
                    _VISIBLE_WORKSPACE_PREFIX,
                    backend_path,
                ),
            ),
            history_route=_VisibleRoute(
                prefix=_VISIBLE_HISTORY_PREFIX,
                backend_getter=lambda: sandbox_backend,
                to_backend_path=lambda suffix: to_actual(history_root, suffix),
                from_backend_path=lambda backend_path: from_actual(
                    history_root,
                    _VISIBLE_HISTORY_PREFIX,
                    backend_path,
                ),
            ),
            memory_route=_VisibleRoute(
                prefix=_VISIBLE_MEMORY_PREFIX,
                backend_getter=lambda: sandbox_backend,
                to_backend_path=lambda suffix: to_actual(
                    lambda: posixpath.join(normalized_root, "memory"),
                    suffix,
                ),
                from_backend_path=lambda backend_path: from_actual(
                    lambda: posixpath.join(normalized_root, "memory"),
                    _VISIBLE_MEMORY_PREFIX,
                    backend_path,
                ),
            ),
            skills_route=_VisibleRoute(
                prefix=_VISIBLE_SKILLS_PREFIX,
                backend_getter=lambda: sandbox_backend,
                to_backend_path=lambda suffix: to_actual(
                    lambda: posixpath.join(normalized_root, "skills"),
                    suffix,
                ),
                from_backend_path=lambda backend_path: from_actual(
                    lambda: posixpath.join(normalized_root, "skills"),
                    _VISIBLE_SKILLS_PREFIX,
                    backend_path,
                ),
            ),
        )

    def bind_thread(self, thread_id: str) -> None:
        normalized = _normalize_thread_id(thread_id)
        self._bind_thread_callback(normalized)
        self._current_thread_id = normalized

    def _ensure_thread_bound(self) -> None:
        if self._current_thread_id is None:
            raise RuntimeError("thread workspace is not bound")

    def _ensure_route_is_bound(self, route: _VisibleRoute) -> None:
        if route in {self._workspace_route, self._history_route}:
            self._ensure_thread_bound()

    def _route_for_path(self, path: str) -> tuple[_VisibleRoute, str]:
        normalized = _normalize_visible_path(path)
        if normalized == "/":
            msg = "path '/' is a virtual root; use /workspace, /memory, /skills, or /conversation_history"
            raise ValueError(msg)
        for route in self._routes:
            suffix = route.match(normalized)
            if suffix is not None:
                return route, suffix
        msg = (
            "path must start with /workspace, /memory, "
            "/skills, or /conversation_history"
        )
        raise ValueError(msg)

    def _route_for_optional_path(
        self,
        path: str | None,
    ) -> tuple[_VisibleRoute, str] | None:
        if path is None:
            return None
        return self._route_for_path(path)

    def _remap_file_infos(self, route: _VisibleRoute, infos: list[FileInfo]) -> list[FileInfo]:
        mapped: list[FileInfo] = []
        for item in infos:
            backend_path = str(item.get("path", ""))
            mapped.append(
                FileInfo(
                    path=route.from_backend_path(backend_path),
                    is_dir=item.get("is_dir"),
                    size=item.get("size"),
                    modified_at=item.get("modified_at"),
                )
            )
        return mapped

    def _remap_grep_matches(self, route: _VisibleRoute, matches: list[GrepMatch]) -> list[GrepMatch]:
        mapped: list[GrepMatch] = []
        for item in matches:
            mapped.append(
                cast(
                    GrepMatch,
                    {
                        **item,
                        "path": route.from_backend_path(item["path"]),
                    },
                )
            )
        return mapped

    def ls_info(self, path: str) -> list[FileInfo]:
        if _normalize_visible_path(path) == "/":
            return [
                FileInfo(path=f"{prefix}/", is_dir=True, size=0, modified_at="")
                for prefix in sorted(_VISIBLE_ROOTS)
            ]
        route, suffix = self._route_for_path(path)
        self._ensure_route_is_bound(route)
        return self._remap_file_infos(
            route,
            route.backend_getter().ls_info(route.to_backend_path(suffix)),
        )

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        route, suffix = self._route_for_path(file_path)
        self._ensure_route_is_bound(route)
        return route.backend_getter().read(
            route.to_backend_path(suffix),
            offset=offset,
            limit=limit,
        )

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        routed = self._route_for_optional_path(path)
        if routed is not None:
            route, suffix = routed
            self._ensure_route_is_bound(route)
            raw = route.backend_getter().grep_raw(
                pattern,
                route.to_backend_path(suffix),
                glob,
            )
            if isinstance(raw, str):
                return raw
            return self._remap_grep_matches(route, raw)

        matches: list[GrepMatch] = []
        for route in self._routes:
            self._ensure_route_is_bound(route)
            raw = route.backend_getter().grep_raw(
                pattern,
                route.to_backend_path("/"),
                glob,
            )
            if isinstance(raw, str):
                return raw
            matches.extend(self._remap_grep_matches(route, raw))
        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        normalized = _normalize_visible_path(path)
        if normalized != "/":
            route, suffix = self._route_for_path(path)
            self._ensure_route_is_bound(route)
            return self._remap_file_infos(
                route,
                route.backend_getter().glob_info(
                    pattern,
                    route.to_backend_path(suffix),
                ),
            )

        infos: list[FileInfo] = []
        for route in self._routes:
            self._ensure_route_is_bound(route)
            infos.extend(
                self._remap_file_infos(
                    route,
                    route.backend_getter().glob_info(
                        pattern,
                        route.to_backend_path("/"),
                    ),
                )
            )
        infos.sort(key=lambda item: item.get("path", ""))
        return infos

    def write(self, file_path: str, content: str) -> WriteResult:
        route, suffix = self._route_for_path(file_path)
        self._ensure_route_is_bound(route)
        result = route.backend_getter().write(route.to_backend_path(suffix), content)
        if result.path is not None:
            result.path = route.from_backend_path(result.path)
        return result

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        route, suffix = self._route_for_path(file_path)
        self._ensure_route_is_bound(route)
        result = route.backend_getter().edit(
            route.to_backend_path(suffix),
            old_string,
            new_string,
            replace_all=replace_all,
        )
        if result.path is not None:
            result.path = route.from_backend_path(result.path)
        return result

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        grouped: dict[tuple[str, int], tuple[_VisibleRoute, list[tuple[int, str, bytes]]]] = {}
        for index, (path, content) in enumerate(files):
            try:
                route, suffix = self._route_for_path(path)
            except ValueError:
                grouped[(f"error-{index}", index)] = (
                    self._workspace_route,
                    [(index, "", content)],
                )
                continue
            self._ensure_route_is_bound(route)
            backend = route.backend_getter()
            key = (route.prefix, id(backend))
            batch = grouped.get(key)
            if batch is None:
                grouped[key] = (route, [(index, route.to_backend_path(suffix), content)])
            else:
                batch[1].append((index, route.to_backend_path(suffix), content))

        responses: list[FileUploadResponse | None] = [None] * len(files)
        for key, (route, batch) in grouped.items():
            if key[0].startswith("error-"):
                idx = batch[0][0]
                responses[idx] = FileUploadResponse(path=files[idx][0], error="invalid_path")
                continue
            backend = route.backend_getter()
            backend_responses = backend.upload_files(
                [(item[1], item[2]) for item in batch]
            )
            for order, item in enumerate(batch):
                responses[item[0]] = FileUploadResponse(
                    path=files[item[0]][0],
                    error=backend_responses[order].error if order < len(backend_responses) else None,
                )
        return cast(list[FileUploadResponse], responses)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        grouped: dict[tuple[str, int], tuple[_VisibleRoute, list[tuple[int, str]]]] = {}
        responses: list[FileDownloadResponse | None] = [None] * len(paths)
        for index, path in enumerate(paths):
            try:
                route, suffix = self._route_for_path(path)
            except ValueError:
                responses[index] = FileDownloadResponse(path=path, content=None, error="invalid_path")
                continue
            self._ensure_route_is_bound(route)
            backend = route.backend_getter()
            key = (route.prefix, id(backend))
            batch = grouped.get(key)
            backend_path = route.to_backend_path(suffix)
            if batch is None:
                grouped[key] = (route, [(index, backend_path)])
            else:
                batch[1].append((index, backend_path))

        for route, batch in grouped.values():
            backend_responses = route.backend_getter().download_files(
                [item[1] for item in batch]
            )
            for order, item in enumerate(batch):
                response = backend_responses[order]
                responses[item[0]] = FileDownloadResponse(
                    path=paths[item[0]],
                    content=response.content,
                    error=response.error,
                )
        return cast(list[FileDownloadResponse], responses)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        self._ensure_thread_bound()
        return self._shell_execute(command, timeout)
