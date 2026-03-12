"""Subagent loader for Deep Agents clients.

Loads custom subagent definitions from the filesystem. Subagents are defined as
markdown files with YAML frontmatter in agent directories.

Directory structure (per source):
    {agents_dir}/{agent_name}/AGENTS.md
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypedDict

import yaml

if TYPE_CHECKING:
    from pathlib import Path


class SubagentMetadata(TypedDict):
    """Metadata for a custom subagent loaded from filesystem."""

    name: str
    """Unique identifier for the subagent, used with the task tool."""

    description: str
    """What this subagent does. Main agent uses this to decide when to delegate."""

    system_prompt: str
    """Instructions for the subagent (body of the markdown file)."""

    model: str | None
    """Optional model override in 'provider:model-name' format."""

    source: str
    """Where this subagent was loaded from ('user' or 'project')."""

    path: str
    """Absolute path to the subagent definition file."""


def _parse_subagent_file(file_path: Path) -> SubagentMetadata | None:
    """Parse a subagent markdown file with YAML frontmatter.

    The file must have YAML frontmatter (delimited by `---`) containing at minimum
    `name` and `description` fields. The body of the file becomes the `system_prompt`.

    Args:
        file_path: Path to the markdown file.

    Returns:
        Parsed subagent metadata, or `None` if the file is invalid.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if not match:
        return None

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None

    if not isinstance(frontmatter, dict):
        return None

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    model = frontmatter.get("model")

    name_valid = isinstance(name, str) and name
    description_valid = isinstance(description, str) and description
    model_valid = model is None or isinstance(model, str)

    if not (name_valid and description_valid and model_valid):
        return None

    return {
        "name": name,
        "description": description,
        "system_prompt": match.group(2).strip(),
        "model": model,
        "source": "",
        "path": str(file_path),
    }


def _load_subagents_from_dir(
    agents_dir: Path,
    source: str,
) -> dict[str, SubagentMetadata]:
    """Load subagents from a directory.

    Expects structure: `agents_dir/{subagent_name}/AGENTS.md`.

    Args:
        agents_dir: Directory containing subagent folders.
        source: Source identifier ("user" or "project").

    Returns:
        Dict mapping subagent name to metadata.
    """
    subagents: dict[str, SubagentMetadata] = {}

    if not agents_dir.exists() or not agents_dir.is_dir():
        return subagents

    for folder in agents_dir.iterdir():
        if not folder.is_dir():
            continue

        subagent_file = folder / "AGENTS.md"
        if not subagent_file.exists():
            continue

        subagent = _parse_subagent_file(subagent_file)
        if subagent:
            subagent["source"] = source
            subagents[subagent["name"]] = subagent

    return subagents


def list_subagents(
    *,
    user_agents_dir: Path | None = None,
    project_agents_dir: Path | None = None,
) -> list[SubagentMetadata]:
    """List subagents from user and/or project directories.

    Scans for subagent definitions in the provided directories.
    Project subagents override user subagents with the same name.

    Args:
        user_agents_dir: Path to user-level agents directory.
        project_agents_dir: Path to project-level agents directory.

    Returns:
        List of subagent metadata, with project subagents taking precedence.
    """
    all_subagents: dict[str, SubagentMetadata] = {}

    if user_agents_dir is not None:
        all_subagents.update(_load_subagents_from_dir(user_agents_dir, "user"))

    if project_agents_dir is not None:
        all_subagents.update(_load_subagents_from_dir(project_agents_dir, "project"))

    return list(all_subagents.values())


__all__ = [
    "SubagentMetadata",
    "_load_subagents_from_dir",
    "_parse_subagent_file",
    "list_subagents",
]
