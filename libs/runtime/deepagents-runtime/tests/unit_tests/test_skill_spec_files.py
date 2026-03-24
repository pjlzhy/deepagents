"""Unit tests for skill directory snapshots in AgentSpec."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

from deepagents_runtime.converters import (
    sync_agent_spec_request_to_agent_spec,
    sync_skill_request_to_skill_spec,
)
from deepagents_runtime.generated import runtime_pb2 as pb2
from deepagents_runtime.registry import Registry
from deepagents_runtime.spec import AgentSpec


def _make_base_dir() -> Path:
    base_dir = Path.cwd() / ".codex_tmp" / "skill-spec" / uuid.uuid4().hex
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _build_agent_spec() -> AgentSpec:
    return AgentSpec(
        name="demo-agent",
        description="demo",
        skills=[
            {
                "name": "web-research",
                "content": "---\nname: web-research\n---\n# Web Research\n",
                "files": [
                    {
                        "path": "scripts/example.py",
                        "content": "print('hello')\n",
                    },
                    {
                        "path": "references/api_reference.md",
                        "content": "# API Reference\n",
                    },
                    {
                        "path": "assets/example.txt",
                        "content": "asset placeholder\n",
                    },
                ],
            }
        ],
    )


def test_sync_requests_parse_skill_files() -> None:
    """Skill protobufs should preserve additional bundled files."""

    sync_skill = pb2.SyncSkillRequest(
        name="web-research",
        content="---\nname: web-research\n---\n# Web Research\n",
        files=[
            pb2.SkillFile(path="scripts/example.py", content="print('hello')\n"),
            pb2.SkillFile(
                path="references/api_reference.md",
                content="# API Reference\n",
            ),
        ],
    )
    parsed_skill = sync_skill_request_to_skill_spec(sync_skill)
    assert [(file.path, file.content) for file in parsed_skill.files] == [
        ("scripts/example.py", "print('hello')\n"),
        ("references/api_reference.md", "# API Reference\n"),
    ]

    sync_agent = pb2.SyncAgentSpecRequest(
        name="demo-agent",
        skills=[
            pb2.SkillContent(
                name="web-research",
                content="---\nname: web-research\n---\n# Web Research\n",
                files=[
                    pb2.SkillFile(
                        path="scripts/example.py",
                        content="print('hello')\n",
                    ),
                    pb2.SkillFile(
                        path="references/api_reference.md",
                        content="# API Reference\n",
                    ),
                ],
            )
        ],
    )
    parsed_agent = sync_agent_spec_request_to_agent_spec(sync_agent)
    assert parsed_agent.skills == [
        {
            "name": "web-research",
            "content": "---\nname: web-research\n---\n# Web Research\n",
            "files": [
                {"path": "scripts/example.py", "content": "print('hello')\n"},
                {
                    "path": "references/api_reference.md",
                    "content": "# API Reference\n",
                },
            ],
        }
    ]


def test_registry_writes_and_roundtrips_skill_directory_snapshot() -> None:
    """Registry should materialize SKILL.md plus bundled skill files."""

    base_dir = _make_base_dir()
    registry = Registry(base_dir=base_dir)
    spec = _build_agent_spec()

    try:
        async def scenario() -> AgentSpec | None:
            await registry.add_agent_spec(spec)
            return await registry.get_agent_spec(spec.name)

        loaded = asyncio.run(scenario())

        skill_dir = registry.skills_dir("demo-agent") / "web-research"
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == (
            "---\nname: web-research\n---\n# Web Research\n"
        )
        assert (skill_dir / "scripts" / "example.py").read_text(
            encoding="utf-8"
        ) == "print('hello')\n"
        assert (skill_dir / "references" / "api_reference.md").read_text(
            encoding="utf-8"
        ) == "# API Reference\n"
        assert (skill_dir / "assets" / "example.txt").read_text(
            encoding="utf-8"
        ) == "asset placeholder\n"

        assert loaded is not None
        assert loaded.skills == spec.skills
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_registry_rejects_skill_file_path_escape() -> None:
    """Registry should reject skill files that escape the skill directory."""

    base_dir = _make_base_dir()
    registry = Registry(base_dir=base_dir)
    spec = AgentSpec(
        name="demo-agent",
        skills=[
            {
                "name": "bad-skill",
                "content": "# Bad Skill\n",
                "files": [
                    {"path": "../escape.py", "content": "print('oops')\n"},
                ],
            }
        ],
    )

    try:
        with pytest.raises(ValueError, match="escapes skill directory"):
            asyncio.run(registry.add_agent_spec(spec))
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_registry_rejects_duplicate_skill_file_path() -> None:
    """Registry should reject duplicate file targets within one skill."""

    base_dir = _make_base_dir()
    registry = Registry(base_dir=base_dir)
    spec = AgentSpec(
        name="demo-agent",
        skills=[
            {
                "name": "dup-skill",
                "content": "# Duplicate Skill\n",
                "files": [
                    {"path": "scripts/example.py", "content": "print('one')\n"},
                    {"path": "scripts/example.py", "content": "print('two')\n"},
                ],
            }
        ],
    )

    try:
        with pytest.raises(ValueError, match="Duplicate skill file path"):
            asyncio.run(registry.add_agent_spec(spec))
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_agent_spec_from_yaml_ignores_removed_phase2_fields() -> None:
    """Legacy YAML fields removed in Phase 2 should be ignored on load."""

    loaded = AgentSpec.from_yaml(
        {
            "metadata": {"name": "demo-agent"},
            "spec": {
                "prompt": {
                    "system": "system prompt",
                    "memory": ["legacy-memory.md"],
                },
                "tools": {
                    "builtins": ["execute"],
                    "mcp": ["github"],
                },
                "subagents": [
                    {
                        "name": "reviewer",
                        "description": "code review",
                        "system_prompt": "review code",
                        "model": "openai:gpt-5.2",
                        "source": "project",
                        "path": "subagents/reviewer.yaml",
                    }
                ],
            },
        }
    )

    assert loaded.prompt == {"system": "system prompt"}
    assert loaded.tools == {}
    assert loaded.subagents == [
        {
            "name": "reviewer",
            "description": "code review",
            "system_prompt": "review code",
            "model": "openai:gpt-5.2",
        }
    ]
