"""Agent OS data models.

Leaf module: no imports from deepagents_runtime. All data types used
across the runtime package are defined here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePath
from typing import Any, NotRequired, TypedDict


# ──────────────────────────── Enums ────────────────────────────


class AgentStatus(str, enum.Enum):
    """Lifecycle states for a managed agent.

    Canonical public states:

    - `INSTALLED`: agent spec exists in the data plane but no compiled runtime
      is currently loaded
    - `COMPILED`: agent has runnable runtime resources
    - `RUNNING`: agent currently has one or more active runs

    Compatibility aliases:

    - `DEFINED` -> `INSTALLED`
    - `ASSEMBLED` -> `COMPILED`
    - `STOPPED` -> `INSTALLED`
    """

    INSTALLED = "installed"
    COMPILED = "compiled"
    RUNNING = "running"

    # Compatibility aliases. Keep these for older callers while the codebase
    # converges on install/compile terminology.
    DEFINED = "installed"
    ASSEMBLED = "compiled"
    STOPPED = "installed"


class LaunchMode(str, enum.Enum):
    """How an agent is launched."""

    CHAT = "chat"
    GATEWAY = "gateway"
    CRON = "cron"


class RuntimeEventType(str, enum.Enum):
    """Discriminator for RuntimeEvent."""

    TEXT_DELTA = "text_delta"
    TEXT_DONE = "text_done"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DONE = "tool_call_done"
    TOOL_RESULT = "tool_result"
    HITL_REQUEST = "hitl_request"
    RUN_START = "run_start"
    RUN_END = "run_end"
    RUN_CANCELED = "run_canceled"
    ERROR = "error"


# ──────────────────── Resource Specs (Registry) ────────────────


@dataclass(frozen=True)
class SkillFileSpec:
    """One file inside a skill directory snapshot."""

    path: str
    content: str


@dataclass(frozen=True)
class SkillSpec:
    """A registered skill resource.

    `content` always maps to the root `SKILL.md` file.
    `files` carries additional bundled files such as `scripts/`,
    `references/`, or `assets/`.
    """

    name: str
    content: str
    files: list[SkillFileSpec] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class McpConfig:
    """An MCP server connection configuration."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    description: str = ""


class SandboxSpec(TypedDict, total=False):
    """Declarative sandbox specification from AgentSpec YAML."""

    image: str
    resources: dict[str, Any]
    init: list[str]


class PromptSpec(TypedDict, total=False):
    """Prompt configuration within an AgentSpec."""

    system: str


class ToolsSpec(TypedDict, total=False):
    """Reserved for future tool configuration extensions."""


class SubagentMetadata(TypedDict):
    """Metadata for a custom subagent loaded from filesystem or gRPC."""

    name: str
    """Unique identifier for the subagent, used with the task tool."""

    description: str
    """What this subagent does. Main agent uses this to decide when to delegate."""

    system_prompt: str
    """Instructions for the subagent."""

    model: NotRequired[str | None]
    """Optional model override in 'provider:model-name' format."""


class SkillFileItem(TypedDict):
    """One embedded file within a skill directory."""

    path: str
    """Relative path under the skill directory, e.g. `scripts/example.py`."""

    content: str
    """UTF-8 text content for the file."""


class SkillContentItem(TypedDict):
    """A skill directory snapshot embedded into an agent spec."""

    name: str
    """Skill directory name (e.g., 'web-research')."""

    content: str
    """Full SKILL.md content (YAML frontmatter + markdown body)."""

    files: NotRequired[list[SkillFileItem]]
    """Additional skill files such as `scripts/` or `references/`."""


class ModelConfigSpec(TypedDict, total=False):
    """Extended model configuration (optional, overrides model string)."""

    provider: str
    model: str
    base_url: str
    api_key: str
    api_key_env: str
    extra_params: dict[str, str]


@dataclass
class AgentSpec:
    """Declarative agent definition (corresponds to agent YAML)."""

    # ── metadata ──
    name: str
    version: str = "1.0.0"
    description: str = ""
    tags: list[str] = field(default_factory=list)

    # ── core config ──
    model: str = "anthropic:claude-sonnet-4-6"
    model_config: ModelConfigSpec | None = None
    prompt: PromptSpec = field(default_factory=dict)  # type: ignore[assignment]
    skills: list[SkillContentItem] = field(default_factory=list)
    tools: ToolsSpec = field(default_factory=dict)  # type: ignore[assignment]
    subagents: list[SubagentMetadata] = field(default_factory=list)
    mcp_servers: list[McpConfig] = field(default_factory=list)
    sandbox: SandboxSpec = field(default_factory=dict)  # type: ignore[assignment]
    interrupt_on: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, data: dict[str, Any]) -> AgentSpec:
        """Parse from a YAML-loaded dict."""
        metadata = data.get("metadata", {})
        spec = data.get("spec", {})

        # Parse MCP servers
        mcp_servers: list[McpConfig] = []
        for mcp_raw in spec.get("mcp_servers", []):
            if isinstance(mcp_raw, dict):
                mcp_servers.append(McpConfig(
                    name=mcp_raw.get("name", ""),
                    command=mcp_raw.get("command", ""),
                    args=mcp_raw.get("args", []),
                    env=mcp_raw.get("env", {}),
                    transport=mcp_raw.get("transport", "stdio"),
                    description=mcp_raw.get("description", ""),
                ))

        # Parse subagents
        subagents: list[SubagentMetadata] = []
        for sa_raw in spec.get("subagents", []):
            if isinstance(sa_raw, dict):
                sa: SubagentMetadata = {
                    "name": sa_raw.get("name", ""),
                    "description": sa_raw.get("description", ""),
                    "system_prompt": sa_raw.get("system_prompt", ""),
                }
                if sa_raw.get("model"):
                    sa["model"] = sa_raw["model"]
                subagents.append(sa)

        # Parse skills (support both dict and legacy string format)
        skills: list[SkillContentItem] = []
        for s_raw in spec.get("skills", []):
            if isinstance(s_raw, dict):
                skill_item: SkillContentItem = {
                    "name": s_raw.get("name", ""),
                    "content": s_raw.get("content", ""),
                }
                files: list[SkillFileItem] = []
                for f_raw in s_raw.get("files", []):
                    if isinstance(f_raw, dict):
                        files.append({
                            "path": f_raw.get("path", ""),
                            "content": f_raw.get("content", ""),
                        })
                if files:
                    skill_item["files"] = files
                skills.append(skill_item)
            elif isinstance(s_raw, str):
                skills.append({"name": s_raw, "content": ""})

        # Parse model_config
        model_config: ModelConfigSpec | None = None
        mc_raw = spec.get("model_config")
        if isinstance(mc_raw, dict):
            model_config = {}
            for k in ("provider", "model", "base_url", "api_key", "api_key_env"):
                if mc_raw.get(k):
                    model_config[k] = mc_raw[k]  # type: ignore[literal-required]
            if mc_raw.get("extra_params"):
                model_config["extra_params"] = mc_raw["extra_params"]

        prompt_raw = spec.get("prompt", {})
        prompt: PromptSpec = {}
        if isinstance(prompt_raw, dict) and prompt_raw.get("system"):
            prompt["system"] = prompt_raw["system"]

        return cls(
            name=metadata.get("name", "unnamed"),
            version=metadata.get("version", "1.0.0"),
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            model=spec.get("model", "anthropic:claude-sonnet-4-6"),
            model_config=model_config,
            prompt=prompt,
            skills=skills,
            tools={},
            subagents=subagents,
            mcp_servers=mcp_servers,
            sandbox=spec.get("sandbox", {}),
            interrupt_on=spec.get("interrupt_on", []),
        )


# ──────────────────── Runtime Constructs ────────────────────

_SUPPORTED_MCP_TRANSPORTS = frozenset({"stdio", "sse", "http", "streamable_http"})
_SUPPORTED_SANDBOX_BACKENDS = frozenset({"local", "docker", "k8s"})
_SANDBOX_BACKEND_ALIASES = {
    "filesystem": "local",
    "kubernetes": "k8s",
    "shell": "local",
}


def _require_non_empty(value: str, field_name: str) -> str:
    """Return a trimmed string or raise when it is empty."""
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} cannot be empty"
        raise ValueError(msg)
    return normalized


def _require_path_safe_name(value: str, field_name: str) -> str:
    """Validate a filesystem-backed resource name."""
    normalized = _require_non_empty(value, field_name)
    candidate = PurePath(normalized)
    if normalized in {".", ".."} or candidate.name != normalized:
        msg = f"{field_name} must be a simple name without path separators"
        raise ValueError(msg)
    return normalized


def _validate_unique(values: list[str], field_name: str) -> None:
    """Raise when a list contains duplicates."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
            continue
        seen.add(value)

    if duplicates:
        names = ", ".join(sorted(duplicates))
        msg = f"duplicate {field_name}: {names}"
        raise ValueError(msg)


def _validate_model_spec(model: str, field_name: str) -> None:
    """Validate the runtime `provider:model` syntax."""
    normalized = _require_non_empty(model, field_name)
    if ":" not in normalized:
        msg = f"{field_name} must be in provider:model format"
        raise ValueError(msg)
    provider, model_name = normalized.split(":", 1)
    _require_non_empty(provider, f"{field_name} provider")
    _require_non_empty(model_name, f"{field_name} name")


def resolve_sandbox_backend_kind(spec: SandboxSpec) -> str:
    """Resolve the concrete sandbox backend kind for a sandbox spec.

    Resolution order:

    1. `sandbox.resources["backend"]` (also accepts `kind`/`provider`)
    2. `docker` when an image is present
    3. `local` fallback
    """

    resources = spec.get("resources") or {}
    if not isinstance(resources, dict):
        msg = "sandbox resources must be a mapping"
        raise ValueError(msg)

    raw_backend: str | None = None
    for key in ("backend", "kind", "provider"):
        value = resources.get(key)
        if value is not None:
            raw_backend = str(value)
            break

    if raw_backend:
        normalized = _require_non_empty(raw_backend, "sandbox backend").lower()
    elif spec.get("image"):
        normalized = "docker"
    else:
        normalized = "local"

    normalized = _SANDBOX_BACKEND_ALIASES.get(normalized, normalized)
    if normalized not in _SUPPORTED_SANDBOX_BACKENDS:
        allowed = ", ".join(sorted(_SUPPORTED_SANDBOX_BACKENDS))
        msg = f"sandbox backend '{normalized}' must be one of: {allowed}"
        raise ValueError(msg)
    return normalized


def validate_agent_spec(spec: AgentSpec) -> None:
    """Validate an agent spec before it is persisted or assembled."""
    _require_path_safe_name(spec.name, "agent name")
    _validate_model_spec(spec.model, "agent model")

    skill_names: list[str] = []
    for skill in spec.skills:
        skill_name = _require_path_safe_name(skill["name"], "skill name")
        skill_names.append(skill_name)
        for file in skill.get("files", []):
            _require_non_empty(
                file["path"],
                f"skill '{skill_name}' file path",
            )
    _validate_unique(skill_names, "skill names")

    subagent_names: list[str] = []
    for subagent in spec.subagents:
        subagent_name = _require_non_empty(subagent["name"], "subagent name")
        subagent_names.append(subagent_name)
        _require_non_empty(
            subagent["description"],
            f"subagent '{subagent_name}' description",
        )
        _require_non_empty(
            subagent["system_prompt"],
            f"subagent '{subagent_name}' system_prompt",
        )
        model = subagent.get("model")
        if model:
            _validate_model_spec(model, f"subagent '{subagent_name}' model")
    _validate_unique(subagent_names, "subagent names")

    mcp_names: list[str] = []
    for mcp in spec.mcp_servers:
        mcp_name = _require_non_empty(mcp.name, "mcp server name")
        mcp_names.append(mcp_name)
        transport = _require_non_empty(
            mcp.transport,
            f"mcp server '{mcp_name}' transport",
        ).lower()
        if transport not in _SUPPORTED_MCP_TRANSPORTS:
            allowed = ", ".join(sorted(_SUPPORTED_MCP_TRANSPORTS))
            msg = f"mcp server '{mcp_name}' transport must be one of: {allowed}"
            raise ValueError(msg)
        if transport == "stdio":
            _require_non_empty(
                mcp.command,
                f"mcp server '{mcp_name}' command",
            )
        else:
            _require_non_empty(
                mcp.command,
                f"mcp server '{mcp_name}' url",
            )
    _validate_unique(mcp_names, "mcp server names")

    interrupts: list[str] = []
    for interrupt_name in spec.interrupt_on:
        interrupts.append(_require_non_empty(interrupt_name, "interrupt_on entry"))
    _validate_unique(interrupts, "interrupt_on entries")

    sandbox = spec.sandbox or {}
    if sandbox:
        image = sandbox.get("image")
        if image is not None:
            _require_non_empty(str(image), "sandbox image")

        init_commands = sandbox.get("init")
        if init_commands is not None:
            if not isinstance(init_commands, list):
                msg = "sandbox init must be a list"
                raise ValueError(msg)
            for index, command in enumerate(init_commands):
                _require_non_empty(str(command), f"sandbox init[{index}]")

        resolve_sandbox_backend_kind(sandbox)


@dataclass
class MCPRuntime:
    """Assembled agent scoped MCP runtime resources."""

    session_manager: Any
    tools: list[Any] = field(default_factory=list)
    server_infos: list[Any] = field(default_factory=list)


@dataclass
class SandboxRuntime:
    """Agent scoped sandbox runtime resources owned by a compiled agent."""

    spec: SandboxSpec
    backend: Any


class AgentRuntimeContext(TypedDict, total=False):
    """Invocation context propagated into the graph runtime."""

    sandbox_backend: Any


@dataclass
class RunConfig:
    """Runtime configuration for launching an agent (not part of AgentSpec)."""

    mode: LaunchMode = LaunchMode.CHAT
    schedule: str = ""
    input: str = ""
    thread_id: str | None = None
    run_id: str | None = None
    timeout_seconds: float | None = None


# ──────────────────── Metadata Types (Registry) ────────────────


@dataclass(frozen=True)
class SkillMeta:
    """Lightweight skill metadata returned by list operations."""

    name: str
    description: str
    tags: list[str]
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class McpMeta:
    """Lightweight MCP metadata returned by list operations."""

    name: str
    description: str


@dataclass(frozen=True)
class AgentMeta:
    """Lightweight agent metadata returned by list operations."""

    name: str
    version: str
    description: str
    tags: list[str]
    status: AgentStatus = AgentStatus.INSTALLED


# ──────────────────── Session / Thread Types ────────────────


class ThreadInfo(TypedDict):
    """Thread metadata for session listing."""

    thread_id: str
    agent_name: str | None
    updated_at: str | None
    message_count: NotRequired[int]
    latest_checkpoint_id: NotRequired[str | None]


# ──────────────────── Workspace ────────────────────


@dataclass
class WorkspaceAgentEntry:
    """One agent entry in workspace.yaml."""

    spec_path: str
    mode: LaunchMode = LaunchMode.GATEWAY
    schedule: str = ""
    input: str = ""


@dataclass
class WorkspaceConfig:
    """Parsed workspace.yaml."""

    name: str = "default"
    description: str = ""
    shared_skills: str = "./skills/"
    shared_mcps: str = "./mcps/"
    shared_memory: str = "./memory/"
    agents: dict[str, WorkspaceAgentEntry] = field(default_factory=dict)
    grpc_port: int = 50051

    @classmethod
    def from_yaml(cls, data: dict[str, Any]) -> WorkspaceConfig:
        """Parse from a YAML-loaded dict."""
        metadata = data.get("metadata", {})
        shared = data.get("shared", {})
        agents_raw = data.get("agents", {})

        agents: dict[str, WorkspaceAgentEntry] = {}
        for name, entry in agents_raw.items():
            agents[name] = WorkspaceAgentEntry(
                spec_path=entry.get("spec", ""),
                mode=LaunchMode(entry.get("mode", "gateway")),
                schedule=entry.get("schedule", ""),
                input=entry.get("input", ""),
            )

        return cls(
            name=metadata.get("name", "default"),
            description=metadata.get("description", ""),
            shared_skills=shared.get("skills", "./skills/"),
            shared_mcps=shared.get("mcps", "./mcps/"),
            shared_memory=shared.get("memory", "./memory/"),
            agents=agents,
            grpc_port=data.get("grpc", {}).get("port", 50051),
        )
