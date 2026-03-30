"""Unit tests for runtime-specific skill middleware behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path

from deepagents.backends import FilesystemBackend

from deepagents_runtime.skills import RuntimeSkillsMiddleware


def _make_skill_content(name: str, description: str) -> str:
    return f"""---
name: {name}
description: {description}
---

# {name}
"""


def test_before_agent_reloads_skills_when_checkpoint_metadata_exists(
    tmp_path: Path,
) -> None:
    """Runtime middleware should rescan skills even when a thread has cached metadata."""

    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=False)
    skills_dir = tmp_path / "skills" / "runtime"
    middleware = RuntimeSkillsMiddleware(
        backend=backend,
        sources=[str(skills_dir)],
    )

    backend.upload_files(
        [
            (
                str(skills_dir / "skill-one" / "SKILL.md"),
                _make_skill_content("skill-one", "first skill").encode("utf-8"),
            )
        ]
    )

    first = middleware.before_agent({}, None, {})  # type: ignore[arg-type]

    assert first is not None
    assert [skill["name"] for skill in first["skills_metadata"]] == ["skill-one"]

    backend.upload_files(
        [
            (
                str(skills_dir / "skill-two" / "SKILL.md"),
                _make_skill_content("skill-two", "second skill").encode("utf-8"),
            )
        ]
    )

    second = middleware.before_agent(
        {"skills_metadata": first["skills_metadata"]},
        None,
        {},
    )  # type: ignore[arg-type]

    assert second is not None
    assert {skill["name"] for skill in second["skills_metadata"]} == {
        "skill-one",
        "skill-two",
    }


def test_abefore_agent_reloads_updated_skill_metadata(tmp_path: Path) -> None:
    """Async runtime middleware should refresh changed skill metadata."""

    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=False)
    skills_dir = tmp_path / "skills" / "runtime"
    skill_path = str(skills_dir / "skill-one" / "SKILL.md")
    middleware = RuntimeSkillsMiddleware(
        backend=backend,
        sources=[str(skills_dir)],
    )

    backend.upload_files(
        [
            (
                skill_path,
                _make_skill_content("skill-one", "first description").encode("utf-8"),
            )
        ]
    )

    first = asyncio.run(
        middleware.abefore_agent({}, None, {})  # type: ignore[arg-type]
    )

    assert first is not None
    assert first["skills_metadata"][0]["description"] == "first description"

    backend.upload_files(
        [
            (
                skill_path,
                _make_skill_content("skill-one", "updated description").encode("utf-8"),
            )
        ]
    )

    second = asyncio.run(
        middleware.abefore_agent(
            {"skills_metadata": first["skills_metadata"]},
            None,
            {},
        )  # type: ignore[arg-type]
    )

    assert second is not None
    assert second["skills_metadata"][0]["description"] == "updated description"
