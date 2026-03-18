"""Agent OS data models.

Leaf module: no imports from deepagents_runtime. All data types used
across the runtime package are defined here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, NotRequired, TypedDict


# ──────────────────────────── Enums ────────────────────────────


class AgentStatus(str, enum.Enum):
    """Lifecycle states for a managed agent."""

    DEFINED = "defined"
    ASSEMBLED = "assembled"
    RUNNING = "running"
    STOPPED = "stopped"


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
    HITL_RESPONSE = "hitl_response"
    RUN_START = "run_start"
    RUN_END = "run_end"
    ERROR = "error"
    STATS = "stats"


# ──────────────────── Resource Specs (Registry) ────────────────


@dataclass(frozen=True)
class SkillSpec:
    """A registered skill resource."""

    name: str
    content: str
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


class SkillContentItem(TypedDict):
    """A skill with embedded content for injection into agent spec."""

    name: str
    """Skill directory name (e.g., 'web-research')."""

    content: str
    """Full SKILL.md content (YAML frontmatter + markdown body)."""


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
                skills.append({
                    "name": s_raw.get("name", ""),
                    "content": s_raw.get("content", ""),
                })
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
class AgentRun:
    """Per-invocation runtime context. Owns its own sandbox and MCP connections.

    Lifecycle::

        run = AgentRun(template=template, run_id="abc", thread_id="t1")
        await run.setup(sandbox_pool=pool)    # acquire sandbox, start MCPs
        try:
            # ... execute agent loop ...
            pass
        finally:
            await run.teardown(sandbox_pool=pool)  # release sandbox, close MCPs
    """

    template: AgentTemplate
    run_id: str = ""
    thread_id: str = ""
    sandbox: Any = None  # SandboxBackendProtocol instance
    mcp_clients: list[Any] = field(default_factory=list)

    async def setup(self, sandbox_pool: Any = None) -> None:
        """Acquire per-run resources (sandbox, MCP clients).

        Args:
            sandbox_pool: Optional SandboxPool to acquire a sandbox from.
        """
        # Acquire sandbox if spec requires one and pool is available
        if sandbox_pool is not None and self.template.sandbox_spec:
            self.sandbox = await sandbox_pool.acquire(self.template.sandbox_spec)

        # Start MCP server processes and create client connections
        for mcp_config in self.template.mcp_configs:
            client = await _start_mcp_client(mcp_config)
            if client is not None:
                self.mcp_clients.append(client)

    async def teardown(self, sandbox_pool: Any = None) -> None:
        """Release per-run resources (sandbox, MCP clients)."""
        # Close MCP clients
        for client in self.mcp_clients:
            try:
                close = getattr(client, "close", None) or getattr(client, "cleanup", None)
                if close and callable(close):
                    await close()
            except Exception:
                pass
        self.mcp_clients.clear()

        # Release sandbox back to pool
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


async def _start_mcp_client(mcp_config: McpConfig) -> Any:
    """Start an MCP server process and return a client connection.

    This is a placeholder that returns *None* until the MCP client
    SDK integration is implemented.
    """
    # TODO: implement MCP client lifecycle
    # 1. Start MCP server subprocess: mcp_config.command + mcp_config.args
    # 2. Connect MCP client via stdio/SSE
    # 3. Return the connected client handle
    return None


@dataclass
class RunConfig:
    """Runtime configuration for launching an agent (not part of AgentSpec)."""

    mode: LaunchMode = LaunchMode.CHAT
    schedule: str = ""
    input: str = ""
    thread_id: str | None = None


@dataclass
class ManagedAgent:
    """Control-plane bookkeeping per agent."""

    name: str
    spec: AgentSpec
    template: AgentTemplate | None = None
    status: AgentStatus = AgentStatus.DEFINED
    run_config: RunConfig | None = None
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
    status: AgentStatus = AgentStatus.DEFINED


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
