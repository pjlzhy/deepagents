"""File-system-backed resource registry for agent specs.

Stores agent definitions as YAML files under a base directory
(default ``~/.deepagents/agents/{name}/agent.yaml``). The registry keeps
registry metadata, shared runtime snapshots, and per-thread workspaces
separate.

Storage layout::

    base_dir/
    └── agents/
        └── {agent_name}/
            ├── agent.yaml
            └── runtime/
                ├── shared/
                │   ├── memory/
                │   │   └── AGENTS.md
                │   └── skills/
                │       └── {skill}/
                │           └── SKILL.md
                └── threads/
                    └── {thread_id}/
                        ├── uploaded.txt
                        └── .runtime/
                            ├── memory/
                            │   └── AGENTS.md
                            ├── skills/
                            │   └── {skill}/...
                            └── conversation_history/
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import yaml

from deepagents_runtime.spec import (
    AgentMeta,
    AgentSpec,
    sandbox_spec_to_dict,
    validate_agent_spec,
)

logger = logging.getLogger(__name__)


def _default_base_dir() -> Path:
    """Return the default registry base directory."""
    return Path.home() / ".deepagents"


def _agents_dir(base_dir: Path) -> Path:
    return base_dir / "agents"


def _agent_dir(base_dir: Path, name: str) -> Path:
    return _agents_dir(base_dir) / name


def _agent_yaml(base_dir: Path, name: str) -> Path:
    return _agent_dir(base_dir, name) / "agent.yaml"


def _agent_runtime_dir(base_dir: Path, name: str) -> Path:
    return _agent_dir(base_dir, name) / "runtime"


def _agent_shared_dir(base_dir: Path, name: str) -> Path:
    return _agent_runtime_dir(base_dir, name) / "shared"


def _agent_threads_dir(base_dir: Path, name: str) -> Path:
    return _agent_runtime_dir(base_dir, name) / "threads"


def _normalize_thread_id(thread_id: str) -> str:
    normalized = thread_id.strip()
    if not normalized:
        raise ValueError("thread_id must not be empty")
    if "/" in normalized or "\\" in normalized:
        raise ValueError("thread_id must not contain path separators")
    if normalized in {".", ".."}:
        raise ValueError("thread_id must not be a traversal segment")
    return normalized


def _resolve_skill_file_path(skill_dir: Path, relative_path: str) -> Path:
    """Resolve and validate a relative skill file path."""
    if not relative_path.strip():
        raise ValueError("Skill file path cannot be empty")

    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError(f"Skill file path must be relative: {relative_path}")

    full_path = (skill_dir / candidate).resolve()
    root = skill_dir.resolve()
    try:
        full_path.relative_to(root)
    except ValueError as exc:
        msg = f"Skill file path escapes skill directory: {relative_path}"
        raise ValueError(msg) from exc

    if full_path == root:
        raise ValueError(f"Skill file path must point to a file: {relative_path}")

    if full_path.name == "SKILL.md":
        msg = (
            "Skill file path 'SKILL.md' is reserved; "
            "use the skill content field instead"
        )
        raise ValueError(msg)

    return full_path


def _spec_to_yaml_dict(spec: AgentSpec) -> dict[str, Any]:
    """Serialize an ``AgentSpec`` to a YAML-friendly dict.

    Mirrors the structure expected by ``AgentSpec.from_yaml()``.
    """
    # Serialize MCP servers
    mcp_servers = []
    for mcp in spec.mcp_servers:
        mcp_dict: dict[str, Any] = {
            "name": mcp.name,
            "command": mcp.command,
            "args": mcp.args,
            "env": mcp.env,
            "transport": mcp.transport,
            "description": mcp.description,
        }
        mcp_servers.append(mcp_dict)

    # Serialize subagents
    subagents = []
    for sa in spec.subagents:
        sa_dict: dict[str, Any] = {
            "name": sa["name"],
            "description": sa["description"],
            "system_prompt": sa["system_prompt"],
        }
        if sa.get("model"):
            sa_dict["model"] = sa["model"]
        subagents.append(sa_dict)

    # Serialize skills
    skills = []
    for skill in spec.skills:
        skill_dict: dict[str, Any] = {
            "name": skill["name"],
            "content": skill["content"],
        }
        files = [
            {"path": file["path"], "content": file["content"]}
            for file in skill.get("files", [])
        ]
        if files:
            skill_dict["files"] = files
        skills.append(skill_dict)

    spec_dict: dict[str, Any] = {
        "model": spec.model,
        "prompt": (
            {"system": spec.prompt["system"]}
            if spec.prompt.get("system")
            else {}
        ),
        "skills": skills,
        "tools": {},
        "subagents": subagents,
        "mcp_servers": mcp_servers,
        "sandbox": sandbox_spec_to_dict(spec.sandbox),
        "interrupt_on": spec.interrupt_on,
    }
    if spec.model_config:
        spec_dict["model_config"] = dict(spec.model_config)

    return {
        "metadata": {
            "name": spec.name,
            "version": spec.version,
            "description": spec.description,
            "tags": spec.tags,
        },
        "spec": spec_dict,
    }


class Registry:
    """File-system registry for agent specs.

    Manages the runtime-visible directory layout for each agent, including
    shared snapshots and per-thread workspaces under `runtime/`.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or _default_base_dir()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    # ── Path helpers ──

    def agent_dir(self, name: str) -> Path:
        """Return the agent's storage root directory."""
        return _agent_dir(self._base_dir, name)

    def runtime_dir(self, name: str) -> Path:
        """Return the agent's runtime storage root directory."""
        return _agent_runtime_dir(self._base_dir, name)

    def shared_dir(self, name: str) -> Path:
        """Return the shared runtime snapshot root for one agent."""
        return _agent_shared_dir(self._base_dir, name)

    def shared_skills_dir(self, name: str) -> Path:
        """Return the shared skills snapshot directory for one agent."""
        return self.shared_dir(name) / "skills"

    def shared_memory_file(self, name: str) -> Path:
        """Return the shared memory snapshot file for one agent."""
        return self.shared_dir(name) / "memory" / "AGENTS.md"

    def threads_dir(self, name: str) -> Path:
        """Return the per-thread workspace root for one agent."""
        return _agent_threads_dir(self._base_dir, name)

    def thread_root_dir(self, name: str, thread_id: str) -> Path:
        """Return the current thread's workspace root directory."""
        return self.threads_dir(name) / _normalize_thread_id(thread_id)

    def thread_runtime_dir(self, name: str, thread_id: str) -> Path:
        """Return the hidden runtime directory inside one thread root."""
        return self.thread_root_dir(name, thread_id) / ".runtime"

    def thread_memory_file(self, name: str, thread_id: str) -> Path:
        """Return the current thread's memory snapshot file."""
        return self.thread_runtime_dir(name, thread_id) / "memory" / "AGENTS.md"

    def thread_skills_dir(self, name: str, thread_id: str) -> Path:
        """Return the current thread's skills snapshot directory."""
        return self.thread_runtime_dir(name, thread_id) / "skills"

    def thread_history_dir(self, name: str, thread_id: str) -> Path:
        """Return the current thread's conversation-history directory."""
        return self.thread_runtime_dir(name, thread_id) / "conversation_history"

    def delete_thread_dir(self, name: str, thread_id: str) -> None:
        """Delete one thread root directory if it exists."""
        shutil.rmtree(self.thread_root_dir(name, thread_id), ignore_errors=True)

    def materialize_thread_root(self, name: str, thread_id: str) -> Path:
        """Create one thread root and snapshot shared runtime resources into it."""
        root = self.thread_root_dir(name, thread_id)
        runtime_dir = self.thread_runtime_dir(name, thread_id)
        memory_file = self.thread_memory_file(name, thread_id)
        skills_dir = self.thread_skills_dir(name, thread_id)
        history_dir = self.thread_history_dir(name, thread_id)

        root.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)
        history_dir.mkdir(parents=True, exist_ok=True)

        shared_memory = self.shared_memory_file(name)
        if not memory_file.exists():
            if shared_memory.exists():
                memory_file.write_text(
                    shared_memory.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            else:
                memory_file.touch()

        shared_skills = self.shared_skills_dir(name)
        if shared_skills.exists() and not any(skills_dir.iterdir()):
            shutil.copytree(shared_skills, skills_dir, dirs_exist_ok=True)

        return root

    # Backward-compatible helpers used by existing runtime code/tests.
    def skills_dir(self, name: str) -> Path:
        return self.shared_skills_dir(name)

    def memory_dir(self, name: str) -> Path:
        return self.shared_memory_file(name)

    def history_dir(self, name: str) -> Path:
        return self.runtime_dir(name) / "conversation_history"

    def workspace_dir(self, name: str) -> Path:
        return self.runtime_dir(name) / "workspace"

    # ── Agent Specs ──

    async def add_agent_spec(self, spec: AgentSpec) -> None:
        """Write an agent spec to disk and populate resource directories.

        Creates the shared runtime snapshot structure under `runtime/shared`
        and writes each skill directory snapshot under
        ``runtime/shared/skills/{name}/``.
        """
        validate_agent_spec(spec)
        agent_dir = _agent_dir(self._base_dir, spec.name)
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create standard subdirectories
        runtime_dir = self.runtime_dir(spec.name)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        shared_dir = self.shared_dir(spec.name)
        shared_dir.mkdir(parents=True, exist_ok=True)
        skills_base = self.shared_skills_dir(spec.name)
        shutil.rmtree(skills_base, ignore_errors=True)
        skills_base.mkdir(exist_ok=True)
        self.shared_memory_file(spec.name).parent.mkdir(parents=True, exist_ok=True)
        self.threads_dir(spec.name).mkdir(parents=True, exist_ok=True)

        # Write skill directory snapshots
        for skill in spec.skills:
            skill_dir = skills_base / skill["name"]
            skill_dir.mkdir(parents=True, exist_ok=True)
            seen_targets: set[Path] = set()

            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(skill.get("content", ""), encoding="utf-8")
            logger.debug(
                "Wrote skill '%s' root file for agent '%s' to %s",
                skill["name"], spec.name, skill_md,
            )

            for file in skill.get("files", []):
                target = _resolve_skill_file_path(skill_dir, file["path"])
                if target in seen_targets:
                    msg = (
                        f"Duplicate skill file path within skill "
                        f"'{skill['name']}': {file['path']}"
                    )
                    raise ValueError(msg)
                seen_targets.add(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(file["content"], encoding="utf-8")
                logger.debug(
                    "Wrote skill '%s' file for agent '%s' to %s",
                    skill["name"], spec.name, target,
                )

        # 确保AGENTS.md 存在
        agent_md = self.shared_memory_file(spec.name)
        if not agent_md.exists():
            # Create empty file for user customizations
            # Base instructions are loaded fresh from get_system_prompt()
            agent_md.touch()

        # Write agent YAML
        yaml_path = _agent_yaml(self._base_dir, spec.name)
        data = _spec_to_yaml_dict(spec)

        yaml_path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.debug("Wrote agent spec '%s' to %s", spec.name, yaml_path)

    async def get_agent_spec(self, name: str) -> AgentSpec | None:
        """Read an agent spec from disk."""
        yaml_path = _agent_yaml(self._base_dir, name)
        if not yaml_path.exists():
            return None

        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            return AgentSpec.from_yaml(raw)
        except Exception:
            logger.warning(
                "Failed to load agent spec '%s' from %s",
                name, yaml_path, exc_info=True,
            )
            return None

    async def list_agent_specs(self) -> list[AgentMeta]:
        """List metadata for all stored agent specs."""
        agents_dir = _agents_dir(self._base_dir)
        if not agents_dir.exists():
            return []

        results: list[AgentMeta] = []
        for entry in sorted(agents_dir.iterdir()):
            if not entry.is_dir():
                continue
            yaml_path = entry / "agent.yaml"
            if not yaml_path.exists():
                continue
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                metadata = raw.get("metadata", {})
                results.append(
                    AgentMeta(
                        name=metadata.get("name", entry.name),
                        version=metadata.get("version", "1.0.0"),
                        description=metadata.get("description", ""),
                        tags=metadata.get("tags", []),
                    )
                )
            except Exception:
                logger.warning(
                    "Skipping malformed agent spec at %s", yaml_path, exc_info=True,
                )
        return results

    async def delete_agent_spec(self, name: str) -> bool:
        """Delete an agent spec directory.  Returns True if it existed."""
        agent_dir = _agent_dir(self._base_dir, name)
        if not agent_dir.exists():
            return False

        shutil.rmtree(agent_dir)
        logger.debug("Deleted agent spec '%s' at %s", name, agent_dir)
        return True
