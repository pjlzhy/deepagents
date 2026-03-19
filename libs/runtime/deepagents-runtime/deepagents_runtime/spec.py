"""Agent OS data models.

Leaf module: no imports from deepagents_runtime. All data types used
across the runtime package are defined here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
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
    memory: list[str]


class ToolsSpec(TypedDict, total=False):
    """Tools configuration within an AgentSpec."""

    builtins: list[str]
    mcp: list[str]


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

    source: NotRequired[str]
    """Where this subagent was loaded from ('user' or 'project')."""

    path: NotRequired[str]
    """Path to the subagent definition file."""


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
                if sa_raw.get("source"):
                    sa["source"] = sa_raw["source"]
                if sa_raw.get("path"):
                    sa["path"] = sa_raw["path"]
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

        return cls(
            name=metadata.get("name", "unnamed"),
            version=metadata.get("version", "1.0.0"),
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            model=spec.get("model", "anthropic:claude-sonnet-4-6"),
            model_config=model_config,
            prompt=spec.get("prompt", {}),
            skills=skills,
            tools=spec.get("tools", {}),
            subagents=subagents,
            mcp_servers=mcp_servers,
            sandbox=spec.get("sandbox", {}),
            interrupt_on=spec.get("interrupt_on", []),
        )



# ──────────────────── Runtime Constructs ────────────────────


@dataclass
class AgentTemplate:
    """Assembly output: everything needed to run the agent, minus per-run resources.

    The ``graph`` field holds a ``CompiledStateGraph`` from the SDK but is
    typed as ``Any`` here so that spec.py remains a leaf module.
    """

    graph: Any  # CompiledStateGraph
    sandbox_spec: SandboxSpec
    mcp_configs: list[McpConfig]
    resolved_spec: AgentSpec


@dataclass
class MCPRuntime:
    """Assembled agent scoped MCP runtime resources."""

    session_manager: Any
    tools: list[Any] = field(default_factory=list)
    server_infos: list[Any] = field(default_factory=list)


@dataclass
class SandboxRuntime:
    """Agent scoped sandbox runtime that leases backends per run."""

    spec: SandboxSpec
    pool: Any


class AgentRuntimeContext(TypedDict, total=False):
    """Invocation context propagated into the graph runtime."""

    sandbox_backend: Any


@dataclass
class AgentRun:
    """Per-invocation runtime context.

    Lifecycle::

        run = AgentRun(template=template, run_id="abc", thread_id="t1")
        await run.setup(sandbox_pool=pool)    # acquire sandbox lease
        try:
            # ... execute agent loop ...
            pass
        finally:
            await run.teardown(sandbox_pool=pool)  # release sandbox lease
    """

    template: AgentTemplate
    agent_name: str = ""
    run_id: str = ""
    thread_id: str = ""
    sandbox: Any = None  # Sandbox backend lease for this run

    async def setup(self, sandbox_pool: Any = None) -> None:
        """Acquire per-run resources.

        Args:
            sandbox_pool: Optional SandboxPool to acquire a sandbox from.
        """
        if sandbox_pool is not None:
            self.sandbox = await sandbox_pool.acquire(self.template.sandbox_spec)

    def runtime_context(self) -> AgentRuntimeContext:
        """Build the graph runtime context for this run."""
        if self.sandbox is None:
            return {}
        return {"sandbox_backend": self.sandbox}

    async def teardown(self, sandbox_pool: Any = None) -> None:
        """Release per-run resources."""
        if self.sandbox is not None:
            if sandbox_pool is not None:
                await sandbox_pool.release(self.sandbox)
            else:
                cleanup = getattr(self.sandbox, "cleanup", None)
                if cleanup and callable(cleanup):
                    try:
                        await cleanup()
                    except Exception:
                        pass
            self.sandbox = None


@dataclass
class RunConfig:
    """Runtime configuration for launching an agent (not part of AgentSpec)."""

    mode: LaunchMode = LaunchMode.CHAT
    schedule: str = ""
    input: str = ""
    thread_id: str | None = None
    run_id: str | None = None


@dataclass
class ManagedAgent:
    """Manager-owned runtime bookkeeping per agent."""

    name: str
    spec: AgentSpec
    template: AgentTemplate | None = None
    mcp_runtime: MCPRuntime | None = None
    sandbox_runtime: SandboxRuntime | None = None
    status: AgentStatus = AgentStatus.INSTALLED
    run_config: RunConfig | None = None
    active_run_count: int = 0
    last_invoked: datetime | None = None


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
