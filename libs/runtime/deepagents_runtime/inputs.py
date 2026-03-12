"""Client-neutral input envelope types for Deep Agents runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, TypeAlias, TypedDict

InputMode: TypeAlias = Literal["normal", "bash", "command"]
"""Supported input modes shared across Deep Agents clients."""


class FileAttachment(TypedDict):
    """Attachment describing a filesystem reference.

    Attributes:
        kind: Discriminator for attachment parsing.
        path: Virtual filesystem path starting with `/` (forward slashes only).
        inject: When `True`, the client/runtime may inject the file contents into
            the agent message for convenience.
    """

    kind: Literal["file"]
    path: str
    inject: NotRequired[bool]


class ImageAttachment(TypedDict):
    """Attachment describing an uploaded image.

    Attributes:
        kind: Discriminator for attachment parsing.
        name: Optional filename for display.
        data_url: Browser-style data URL (`data:image/png;base64,...`).
    """

    kind: Literal["image"]
    name: NotRequired[str]
    data_url: str


InputAttachment: TypeAlias = FileAttachment | ImageAttachment
"""Union of supported attachment payload shapes."""


@dataclass(frozen=True, slots=True)
class InputEnvelope:
    """Normalized input payload shared across clients.

    This structure is intentionally UI-agnostic: Textual and a future browser
    client can both submit the same envelope to the runtime.

    Attributes:
        thread_id: Conversation thread identifier.
        mode: Input mode (`normal`, `command`, `bash`).
        text: Raw user input text (message, slash command, or bash command).
        attachments: Optional structured attachment list.
    """

    thread_id: str
    mode: InputMode
    text: str
    attachments: tuple[InputAttachment, ...] = ()


def normalize_input_mode(value: object) -> InputMode | None:
    """Normalize an arbitrary mode value into a supported `InputMode`.

    Args:
        value: Raw mode value (usually a string from JSON).

    Returns:
        Normalized mode string when supported, otherwise `None`.
    """
    if value in {"normal", "bash", "command"}:
        return value
    return None


def coerce_input_envelope(payload: object) -> InputEnvelope | None:
    """Best-effort conversion from a JSON-like dict into `InputEnvelope`.

    Args:
        payload: JSON-like mapping with `thread_id`, `mode`, `text`, and optional
            `attachments`.

    Returns:
        `InputEnvelope` when the payload shape is valid, otherwise `None`.
    """
    if not isinstance(payload, dict):
        return None

    thread_id = payload.get("thread_id")
    mode = normalize_input_mode(payload.get("mode"))
    text = payload.get("text")
    if not isinstance(thread_id, str) or not isinstance(text, str) or mode is None:
        return None

    raw_attachments = payload.get("attachments", [])
    attachments: list[InputAttachment] = []
    if raw_attachments is None:
        raw_attachments = []
    if not isinstance(raw_attachments, list):
        return None

    for attachment in raw_attachments:
        if not isinstance(attachment, dict):
            return None
        kind = attachment.get("kind")
        if kind not in {"file", "image"}:
            return None
        if kind == "file":
            path = attachment.get("path")
            if not isinstance(path, str):
                return None
            raw_inject = attachment.get("inject", False)
            if raw_inject is not False and not isinstance(raw_inject, bool):
                return None
            attachments.append(attachment)
            continue

        data_url = attachment.get("data_url")
        if not isinstance(data_url, str):
            return None
        name = attachment.get("name")
        if name is not None and not isinstance(name, str):
            return None
        attachments.append(attachment)

    return InputEnvelope(
        thread_id=thread_id,
        mode=mode,
        text=text,
        attachments=tuple(attachments),
    )


__all__ = [
    "FileAttachment",
    "ImageAttachment",
    "InputAttachment",
    "InputEnvelope",
    "InputMode",
    "coerce_input_envelope",
    "normalize_input_mode",
]
