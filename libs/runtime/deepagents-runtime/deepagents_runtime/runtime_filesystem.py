"""Runtime-specific filesystem middleware with relative-path contract."""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
from pathlib import Path
from typing import Annotated, Literal, cast

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.messages.content import create_image_block
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import Command

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    WriteResult,
)
from deepagents.middleware.filesystem import (
    DEFAULT_READ_LIMIT,
    DEFAULT_READ_OFFSET,
    GLOB_TIMEOUT,
    GLOB_TOOL_DESCRIPTION,
    GREP_TOOL_DESCRIPTION,
    IMAGE_EXTENSIONS,
    IMAGE_MEDIA_TYPES,
    NUM_CHARS_PER_TOKEN,
    READ_FILE_TOOL_DESCRIPTION,
    READ_FILE_TRUNCATION_MSG,
    TOO_LARGE_TOOL_MSG,
    WRITE_FILE_TOOL_DESCRIPTION,
    EDIT_FILE_TOOL_DESCRIPTION,
    LIST_FILES_TOOL_DESCRIPTION,
    FilesystemMiddleware,
    _build_evicted_content,
    _create_content_preview,
    _extract_text_from_message,
)
from deepagents.backends.utils import (
    format_grep_matches,
    sanitize_tool_call_id,
    truncate_if_too_long,
)
from deepagents_runtime.runtime_backend import normalize_relative_runtime_path

_RUNTIME_HIDDEN_DIR = ".runtime"

RUNTIME_FILESYSTEM_SYSTEM_PROMPT = """## Following Conventions

- Filesystem tools operate relative to your current thread workspace
- Use relative paths such as `A.txt`, `src/app.py`, or `.runtime/memory/AGENTS.md`
- Do not use absolute paths with filesystem tools
- Uploaded files and generated work products live directly in the current workspace
- Runtime-managed files live under `.runtime/`
- Agent memory lives at `.runtime/memory/AGENTS.md`
- Skills live under `.runtime/skills/`
- Summarization history lives under `.runtime/conversation_history/`

## File Reading Best Practices

- Use `ls` before reading or editing when exploring unfamiliar directories
- Use pagination with `read_file(path, offset=..., limit=...)` for large files
- Always read a file before editing it
"""

RUNTIME_EXECUTION_SYSTEM_PROMPT = """## Execute Tool `execute`

- Shell commands start in the current thread workspace
- Prefer relative shell paths such as `ls`, `cat A.txt`, or `python script.py`
- `.runtime/` is available for memory, skills, and conversation history when needed
"""


def _is_hidden_runtime_path(path: str) -> bool:
    normalized = normalize_relative_runtime_path(path)
    return normalized == _RUNTIME_HIDDEN_DIR or normalized.startswith(f"{_RUNTIME_HIDDEN_DIR}/")


def _filter_hidden_runtime_entries(entries: list[str], *, requested_path: str) -> list[str]:
    if _is_hidden_runtime_path(requested_path):
        return entries
    return [
        item
        for item in entries
        if item != f"{_RUNTIME_HIDDEN_DIR}/" and not item.startswith(f"{_RUNTIME_HIDDEN_DIR}/")
    ]


class RuntimeFilesystemMiddleware(FilesystemMiddleware):
    """Filesystem middleware using thread-workspace-relative paths."""

    def __init__(self, **kwargs: object) -> None:
        system_prompt = kwargs.pop("system_prompt", None)
        if system_prompt is None:
            system_prompt = "\n\n".join(
                [RUNTIME_FILESYSTEM_SYSTEM_PROMPT, RUNTIME_EXECUTION_SYSTEM_PROMPT]
            )
        super().__init__(system_prompt=cast(str, system_prompt), **kwargs)

    def _create_ls_tool(self) -> BaseTool:
        tool_description = self._custom_tool_descriptions.get("ls") or LIST_FILES_TOOL_DESCRIPTION

        def sync_ls(
            runtime: ToolRuntime[None, object],
            path: Annotated[str, "Relative directory path to list. Defaults to current directory."] = ".",
        ) -> str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(path)
            except ValueError as e:
                return f"Error: {e}"
            infos = resolved_backend.ls_info(validated_path)
            paths = [fi.get("path", "") for fi in infos]
            result = truncate_if_too_long(
                _filter_hidden_runtime_entries(paths, requested_path=validated_path)
            )
            return str(result)

        async def async_ls(
            runtime: ToolRuntime[None, object],
            path: Annotated[str, "Relative directory path to list. Defaults to current directory."] = ".",
        ) -> str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(path)
            except ValueError as e:
                return f"Error: {e}"
            infos = await resolved_backend.als_info(validated_path)
            paths = [fi.get("path", "") for fi in infos]
            result = truncate_if_too_long(
                _filter_hidden_runtime_entries(paths, requested_path=validated_path)
            )
            return str(result)

        return StructuredTool.from_function(
            name="ls",
            description=tool_description,
            func=sync_ls,
            coroutine=async_ls,
        )

    def _create_read_file_tool(self) -> BaseTool:
        tool_description = self._custom_tool_descriptions.get("read_file") or READ_FILE_TOOL_DESCRIPTION
        token_limit = self._tool_token_limit_before_evict

        def sync_read_file(
            file_path: Annotated[str, "Relative file path to read from the current workspace root."],
            runtime: ToolRuntime[None, object],
            offset: Annotated[int, "Line number to start reading from (0-indexed)."] = DEFAULT_READ_OFFSET,
            limit: Annotated[int, "Maximum number of lines to read."] = DEFAULT_READ_LIMIT,
        ) -> ToolMessage | str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            ext = Path(validated_path).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                responses = resolved_backend.download_files([validated_path])
                if responses and responses[0].content is not None:
                    media_type = IMAGE_MEDIA_TYPES.get(ext, "image/png")
                    image_b64 = base64.standard_b64encode(responses[0].content).decode("utf-8")
                    return ToolMessage(
                        content_blocks=[create_image_block(base64=image_b64, mime_type=media_type)],
                        name="read_file",
                        tool_call_id=runtime.tool_call_id,
                        additional_kwargs={
                            "read_file_path": validated_path,
                            "read_file_media_type": media_type,
                        },
                    )
                if responses and responses[0].error:
                    return f"Error reading image: {responses[0].error}"
                return "Error reading image: unknown error"

            result = resolved_backend.read(validated_path, offset=offset, limit=limit)
            lines = result.splitlines(keepends=True)
            if len(lines) > limit:
                lines = lines[:limit]
                result = "".join(lines)
            if token_limit and len(result) >= NUM_CHARS_PER_TOKEN * token_limit:
                truncation_msg = READ_FILE_TRUNCATION_MSG.format(file_path=validated_path)
                max_content_length = NUM_CHARS_PER_TOKEN * token_limit - len(truncation_msg)
                result = result[:max_content_length]
                result += truncation_msg
            return result

        async def async_read_file(
            file_path: Annotated[str, "Relative file path to read from the current workspace root."],
            runtime: ToolRuntime[None, object],
            offset: Annotated[int, "Line number to start reading from (0-indexed)."] = DEFAULT_READ_OFFSET,
            limit: Annotated[int, "Maximum number of lines to read."] = DEFAULT_READ_LIMIT,
        ) -> ToolMessage | str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            ext = Path(validated_path).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                responses = await resolved_backend.adownload_files([validated_path])
                if responses and responses[0].content is not None:
                    media_type = IMAGE_MEDIA_TYPES.get(ext, "image/png")
                    image_b64 = base64.standard_b64encode(responses[0].content).decode("utf-8")
                    return ToolMessage(
                        content_blocks=[create_image_block(base64=image_b64, mime_type=media_type)],
                        name="read_file",
                        tool_call_id=runtime.tool_call_id,
                        additional_kwargs={
                            "read_file_path": validated_path,
                            "read_file_media_type": media_type,
                        },
                    )
                if responses and responses[0].error:
                    return f"Error reading image: {responses[0].error}"
                return "Error reading image: unknown error"

            result = await resolved_backend.aread(validated_path, offset=offset, limit=limit)
            lines = result.splitlines(keepends=True)
            if len(lines) > limit:
                lines = lines[:limit]
                result = "".join(lines)
            if token_limit and len(result) >= NUM_CHARS_PER_TOKEN * token_limit:
                truncation_msg = READ_FILE_TRUNCATION_MSG.format(file_path=validated_path)
                max_content_length = NUM_CHARS_PER_TOKEN * token_limit - len(truncation_msg)
                result = result[:max_content_length]
                result += truncation_msg
            return result

        return StructuredTool.from_function(
            name="read_file",
            description=tool_description,
            func=sync_read_file,
            coroutine=async_read_file,
        )

    def _create_write_file_tool(self) -> BaseTool:
        tool_description = self._custom_tool_descriptions.get("write_file") or WRITE_FILE_TOOL_DESCRIPTION

        def sync_write_file(
            file_path: Annotated[str, "Relative file path where the file should be created."],
            content: Annotated[str, "The text content to write to the file."],
            runtime: ToolRuntime[None, object],
        ) -> Command | str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(file_path)
            except ValueError as e:
                return f"Error: {e}"
            res: WriteResult = resolved_backend.write(validated_path, content)
            if res.error:
                return res.error
            if res.files_update is not None:
                return Command(
                    update={
                        "files": res.files_update,
                        "messages": [
                            ToolMessage(
                                content=f"Updated file {res.path}",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )
            return f"Updated file {res.path}"

        async def async_write_file(
            file_path: Annotated[str, "Relative file path where the file should be created."],
            content: Annotated[str, "The text content to write to the file."],
            runtime: ToolRuntime[None, object],
        ) -> Command | str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(file_path)
            except ValueError as e:
                return f"Error: {e}"
            res: WriteResult = await resolved_backend.awrite(validated_path, content)
            if res.error:
                return res.error
            if res.files_update is not None:
                return Command(
                    update={
                        "files": res.files_update,
                        "messages": [
                            ToolMessage(
                                content=f"Updated file {res.path}",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )
            return f"Updated file {res.path}"

        return StructuredTool.from_function(
            name="write_file",
            description=tool_description,
            func=sync_write_file,
            coroutine=async_write_file,
        )

    def _create_edit_file_tool(self) -> BaseTool:
        tool_description = self._custom_tool_descriptions.get("edit_file") or EDIT_FILE_TOOL_DESCRIPTION

        def sync_edit_file(
            file_path: Annotated[str, "Relative file path to the file to edit."],
            old_string: Annotated[str, "The exact text to find and replace."],
            new_string: Annotated[str, "The text to replace old_string with."],
            runtime: ToolRuntime[None, object],
            *,
            replace_all: Annotated[bool, "If True, replace all occurrences."] = False,
        ) -> Command | str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(file_path)
            except ValueError as e:
                return f"Error: {e}"
            res: EditResult = resolved_backend.edit(validated_path, old_string, new_string, replace_all=replace_all)
            if res.error:
                return res.error
            if res.files_update is not None:
                return Command(
                    update={
                        "files": res.files_update,
                        "messages": [
                            ToolMessage(
                                content=f"Successfully replaced {res.occurrences} instance(s) of the string in '{res.path}'",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )
            return f"Successfully replaced {res.occurrences} instance(s) of the string in '{res.path}'"

        async def async_edit_file(
            file_path: Annotated[str, "Relative file path to the file to edit."],
            old_string: Annotated[str, "The exact text to find and replace."],
            new_string: Annotated[str, "The text to replace old_string with."],
            runtime: ToolRuntime[None, object],
            *,
            replace_all: Annotated[bool, "If True, replace all occurrences."] = False,
        ) -> Command | str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(file_path)
            except ValueError as e:
                return f"Error: {e}"
            res: EditResult = await resolved_backend.aedit(validated_path, old_string, new_string, replace_all=replace_all)
            if res.error:
                return res.error
            if res.files_update is not None:
                return Command(
                    update={
                        "files": res.files_update,
                        "messages": [
                            ToolMessage(
                                content=f"Successfully replaced {res.occurrences} instance(s) of the string in '{res.path}'",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )
            return f"Successfully replaced {res.occurrences} instance(s) of the string in '{res.path}'"

        return StructuredTool.from_function(
            name="edit_file",
            description=tool_description,
            func=sync_edit_file,
            coroutine=async_edit_file,
        )

    def _create_glob_tool(self) -> BaseTool:
        tool_description = self._custom_tool_descriptions.get("glob") or GLOB_TOOL_DESCRIPTION

        def sync_glob(
            pattern: Annotated[str, "Glob pattern to match files."],
            runtime: ToolRuntime[None, object],
            path: Annotated[str, "Relative base directory to search from. Defaults to current directory."] = ".",
        ) -> str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(path)
            except ValueError as e:
                return f"Error: {e}"
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(resolved_backend.glob_info, pattern, path=validated_path)
                try:
                    infos = future.result(timeout=GLOB_TIMEOUT)
                except concurrent.futures.TimeoutError:
                    return f"Error: glob timed out after {GLOB_TIMEOUT}s. Try a more specific pattern or a narrower path."
            paths = [
                fi.get("path", "")
                for fi in infos
                if _is_hidden_runtime_path(validated_path) or not str(fi.get("path", "")).startswith(f"{_RUNTIME_HIDDEN_DIR}/")
            ]
            result = truncate_if_too_long(paths)
            return str(result)

        async def async_glob(
            pattern: Annotated[str, "Glob pattern to match files."],
            runtime: ToolRuntime[None, object],
            path: Annotated[str, "Relative base directory to search from. Defaults to current directory."] = ".",
        ) -> str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(path)
            except ValueError as e:
                return f"Error: {e}"
            try:
                infos = await asyncio.wait_for(
                    resolved_backend.aglob_info(pattern, path=validated_path),
                    timeout=GLOB_TIMEOUT,
                )
            except TimeoutError:
                return f"Error: glob timed out after {GLOB_TIMEOUT}s. Try a more specific pattern or a narrower path."
            paths = [
                fi.get("path", "")
                for fi in infos
                if _is_hidden_runtime_path(validated_path) or not str(fi.get("path", "")).startswith(f"{_RUNTIME_HIDDEN_DIR}/")
            ]
            result = truncate_if_too_long(paths)
            return str(result)

        return StructuredTool.from_function(
            name="glob",
            description=tool_description,
            func=sync_glob,
            coroutine=async_glob,
        )

    def _create_grep_tool(self) -> BaseTool:
        tool_description = self._custom_tool_descriptions.get("grep") or GREP_TOOL_DESCRIPTION

        def sync_grep(
            pattern: Annotated[str, "Text pattern to search for (literal string, not regex)."],
            runtime: ToolRuntime[None, object],
            path: Annotated[str | None, "Relative directory to search in. Defaults to current directory."] = None,
            glob: Annotated[str | None, "Glob pattern to filter which files to search."] = None,
            output_mode: Annotated[
                Literal["files_with_matches", "content", "count"],
                "Output format.",
            ] = "files_with_matches",
        ) -> str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(path, default=".")
            except ValueError as e:
                return f"Error: {e}"
            raw = resolved_backend.grep_raw(pattern, path=validated_path, glob=glob)
            if isinstance(raw, str):
                return raw
            filtered = (
                raw if _is_hidden_runtime_path(validated_path)
                else [item for item in raw if not item["path"].startswith(f"{_RUNTIME_HIDDEN_DIR}/")]
            )
            formatted = format_grep_matches(filtered, output_mode)
            return truncate_if_too_long(formatted)

        async def async_grep(
            pattern: Annotated[str, "Text pattern to search for (literal string, not regex)."],
            runtime: ToolRuntime[None, object],
            path: Annotated[str | None, "Relative directory to search in. Defaults to current directory."] = None,
            glob: Annotated[str | None, "Glob pattern to filter which files to search."] = None,
            output_mode: Annotated[
                Literal["files_with_matches", "content", "count"],
                "Output format.",
            ] = "files_with_matches",
        ) -> str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = normalize_relative_runtime_path(path, default=".")
            except ValueError as e:
                return f"Error: {e}"
            raw = await resolved_backend.agrep_raw(pattern, path=validated_path, glob=glob)
            if isinstance(raw, str):
                return raw
            filtered = (
                raw if _is_hidden_runtime_path(validated_path)
                else [item for item in raw if not item["path"].startswith(f"{_RUNTIME_HIDDEN_DIR}/")]
            )
            formatted = format_grep_matches(filtered, output_mode)
            return truncate_if_too_long(formatted)

        return StructuredTool.from_function(
            name="grep",
            description=tool_description,
            func=sync_grep,
            coroutine=async_grep,
        )

    def _process_large_message(
        self,
        message: ToolMessage,
        resolved_backend: BackendProtocol,
    ) -> tuple[ToolMessage, dict[str, object] | None]:
        if not self._tool_token_limit_before_evict:
            return message, None

        content_str = _extract_text_from_message(message)
        if len(content_str) <= NUM_CHARS_PER_TOKEN * self._tool_token_limit_before_evict:
            return message, None

        sanitized_id = sanitize_tool_call_id(message.tool_call_id)
        file_path = f".runtime/tool_results/{sanitized_id}"
        result = resolved_backend.write(file_path, content_str)
        if result.error:
            return message, None

        content_sample = _create_content_preview(content_str)
        replacement_text = TOO_LARGE_TOOL_MSG.format(
            tool_call_id=message.tool_call_id,
            file_path=file_path,
            content_sample=content_sample,
        )
        evicted = _build_evicted_content(message, replacement_text)
        processed_message = ToolMessage(
            content=cast("str | list[str | dict]", evicted),
            tool_call_id=message.tool_call_id,
            name=message.name,
            id=message.id,
            artifact=message.artifact,
            status=message.status,
            additional_kwargs=dict(message.additional_kwargs),
            response_metadata=dict(message.response_metadata),
        )
        return processed_message, result.files_update

    async def _aprocess_large_message(
        self,
        message: ToolMessage,
        resolved_backend: BackendProtocol,
    ) -> tuple[ToolMessage, dict[str, object] | None]:
        if not self._tool_token_limit_before_evict:
            return message, None

        content_str = _extract_text_from_message(message)
        if len(content_str) <= NUM_CHARS_PER_TOKEN * self._tool_token_limit_before_evict:
            return message, None

        sanitized_id = sanitize_tool_call_id(message.tool_call_id)
        file_path = f".runtime/tool_results/{sanitized_id}"
        result = await resolved_backend.awrite(file_path, content_str)
        if result.error:
            return message, None

        content_sample = _create_content_preview(content_str)
        replacement_text = TOO_LARGE_TOOL_MSG.format(
            tool_call_id=message.tool_call_id,
            file_path=file_path,
            content_sample=content_sample,
        )
        evicted = _build_evicted_content(message, replacement_text)
        processed_message = ToolMessage(
            content=cast("str | list[str | dict]", evicted),
            tool_call_id=message.tool_call_id,
            name=message.name,
            id=message.id,
            artifact=message.artifact,
            status=message.status,
            additional_kwargs=dict(message.additional_kwargs),
            response_metadata=dict(message.response_metadata),
        )
        return processed_message, result.files_update

    def _create_execute_tool(self) -> BaseTool:
        return super()._create_execute_tool()
