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


class SandboxBackendKind(str, enum.Enum):
    """Explicit sandbox backend kinds understood by the runtime."""

    LOCAL = "local"
    DOCKER = "docker"
    KUBERNETES = "kubernetes"


class ImagePullPolicy(str, enum.Enum):
    """Image pull policies supported by executable sandbox specs."""

    UNSPECIFIED = "unspecified"
    IF_NOT_PRESENT = "if_not_present"
    ALWAYS = "always"
    NEVER = "never"


@dataclass(frozen=True)
class SandboxExecutionPolicy:
    """Execution limits shared by all sandbox backends."""

    command_timeout_seconds: int = 0
    setup_timeout_seconds: int = 0
    startup_timeout_seconds: int = 0
    max_output_bytes: int = 0


@dataclass(frozen=True)
class SandboxEnvVar:
    """One static environment variable injected into the sandbox."""

    name: str
    value: str


@dataclass(frozen=True)
class ImageReference:
    """One concrete image reference used by a sandbox backend."""

    reference: str
    pull_policy: ImagePullPolicy = ImagePullPolicy.UNSPECIFIED


@dataclass(frozen=True)
class LocalSandboxSpec:
    """Local workspace-backed sandbox configuration."""


@dataclass(frozen=True)
class DockerResourceSpec:
    """Docker runtime resource limits."""

    cpu: str = ""
    memory: str = ""
    shm_size: str = ""
    pids_limit: int = 0


@dataclass(frozen=True)
class DockerSandboxSpec:
    """Docker-backed sandbox configuration."""

    image: ImageReference
    resources: DockerResourceSpec = field(default_factory=DockerResourceSpec)


@dataclass(frozen=True)
class KubernetesResourceRequirements:
    """Kubernetes container resource requirements."""

    requests: dict[str, str] = field(default_factory=dict)
    limits: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KubernetesSandboxSpec:
    """Kubernetes-backed sandbox configuration."""

    image: ImageReference
    resources: KubernetesResourceRequirements = field(
        default_factory=KubernetesResourceRequirements
    )


SandboxBackendConfig = LocalSandboxSpec | DockerSandboxSpec | KubernetesSandboxSpec


@dataclass(frozen=True)
class SandboxSpec:
    """Normalized executable sandbox configuration."""

    execution: SandboxExecutionPolicy = field(default_factory=SandboxExecutionPolicy)
    env: list[SandboxEnvVar] = field(default_factory=list)
    setup_commands: list[str] = field(default_factory=list)
    backend: SandboxBackendConfig | None = None


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

    model_config: NotRequired["ModelConfigSpec | None"]
    """Optional extended model configuration (provider, model, base_url, etc.)."""

    skills: NotRequired[list["SkillContentItem"]]
    """Optional skill content items resolved from skill_refs."""


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
    extra_params: dict[str, Any]


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
    sandbox: SandboxSpec | dict[str, Any] | None = None
    interrupt_on: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize legacy/raw sandbox payloads into the runtime sandbox spec."""
        self.sandbox = parse_sandbox_spec(self.sandbox)

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
            sandbox=spec.get("sandbox"),
            interrupt_on=spec.get("interrupt_on", []),
        )


# ──────────────────── Runtime Constructs ────────────────────

_SUPPORTED_MCP_TRANSPORTS = frozenset({"stdio", "sse", "http", "streamable_http"})
_SUPPORTED_SANDBOX_BACKENDS = frozenset(
    kind.value for kind in SandboxBackendKind
)
_SANDBOX_BACKEND_ALIASES = {
    "filesystem": SandboxBackendKind.LOCAL.value,
    "k8s": SandboxBackendKind.KUBERNETES.value,
    "shell": SandboxBackendKind.LOCAL.value,
}
_DEFAULT_DOCKER_IMAGE = "python:3.12-slim"
_IMAGE_PULL_POLICIES = {
    policy.value: policy for policy in ImagePullPolicy
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


def _normalize_optional_string(value: Any, field_name: str) -> str:
    """Return a trimmed string or `""` when the value is absent."""
    if value is None:
        return ""
    normalized = str(value).strip()
    if not normalized:
        msg = f"{field_name} cannot be empty"
        raise ValueError(msg)
    return normalized


def _normalize_string_map(value: Any, field_name: str) -> dict[str, str]:
    """Validate and normalize a string map payload."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        msg = f"{field_name} must be a mapping"
        raise ValueError(msg)

    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _require_non_empty(str(raw_key), f"{field_name} key")
        normalized[key] = _require_non_empty(
            str(raw_value),
            f"{field_name}[{key}]",
        )
    return normalized


def _parse_non_negative_int(value: Any, field_name: str) -> int:
    """Parse a non-negative integer where `0` means unset/default."""
    if value is None or value == "":
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        msg = f"{field_name} must be an integer"
        raise ValueError(msg) from exc
    if parsed < 0:
        msg = f"{field_name} must be non-negative"
        raise ValueError(msg)
    return parsed


def _parse_setup_commands(value: Any, field_name: str) -> list[str]:
    """Parse and normalize shell command lists."""
    if value is None:
        return []
    if not isinstance(value, list):
        msg = f"{field_name} must be a list"
        raise ValueError(msg)
    commands: list[str] = []
    for index, command in enumerate(value):
        commands.append(_require_non_empty(str(command), f"{field_name}[{index}]"))
    return commands


def _parse_sandbox_execution_policy(value: Any) -> SandboxExecutionPolicy:
    """Parse the shared execution policy payload."""
    if value is None:
        return SandboxExecutionPolicy()
    if not isinstance(value, dict):
        msg = "sandbox execution must be a mapping"
        raise ValueError(msg)
    return SandboxExecutionPolicy(
        command_timeout_seconds=_parse_non_negative_int(
            value.get("command_timeout_seconds"),
            "sandbox execution command_timeout_seconds",
        ),
        setup_timeout_seconds=_parse_non_negative_int(
            value.get("setup_timeout_seconds"),
            "sandbox execution setup_timeout_seconds",
        ),
        startup_timeout_seconds=_parse_non_negative_int(
            value.get("startup_timeout_seconds"),
            "sandbox execution startup_timeout_seconds",
        ),
        max_output_bytes=_parse_non_negative_int(
            value.get("max_output_bytes"),
            "sandbox execution max_output_bytes",
        ),
    )


def _parse_sandbox_env(value: Any) -> list[SandboxEnvVar]:
    """Parse static sandbox environment variables."""
    if value is None:
        return []
    if not isinstance(value, list):
        msg = "sandbox env must be a list"
        raise ValueError(msg)

    env_vars: list[SandboxEnvVar] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            msg = f"sandbox env[{index}] must be a mapping"
            raise ValueError(msg)
        env_vars.append(
            SandboxEnvVar(
                name=_require_non_empty(
                    str(item.get("name", "")),
                    f"sandbox env[{index}] name",
                ),
                value=str(item.get("value", "")),
            )
        )
    return env_vars


def _parse_image_pull_policy(value: Any, field_name: str) -> ImagePullPolicy:
    """Parse an image pull policy string."""
    if value is None or value == "":
        return ImagePullPolicy.UNSPECIFIED
    normalized = _require_non_empty(str(value), field_name).lower()
    policy = _IMAGE_PULL_POLICIES.get(normalized)
    if policy is None:
        allowed = ", ".join(sorted(_IMAGE_PULL_POLICIES))
        msg = f"{field_name} must be one of: {allowed}"
        raise ValueError(msg)
    return policy


def _parse_image_reference(
    value: Any,
    field_name: str,
    *,
    required: bool,
) -> ImageReference:
    """Parse one image reference payload."""
    if value is None:
        if required:
            msg = f"{field_name} must be provided"
            raise ValueError(msg)
        return ImageReference(reference="")
    if isinstance(value, str):
        return ImageReference(reference=_require_non_empty(value, field_name))
    if not isinstance(value, dict):
        msg = f"{field_name} must be a mapping"
        raise ValueError(msg)

    reference = _normalize_optional_string(value.get("reference"), field_name)
    if required and not reference:
        msg = f"{field_name} reference must be provided"
        raise ValueError(msg)
    return ImageReference(
        reference=reference,
        pull_policy=_parse_image_pull_policy(
            value.get("pull_policy"),
            f"{field_name} pull_policy",
        ),
    )


def _parse_docker_resource_spec(value: Any) -> DockerResourceSpec:
    """Parse Docker-specific resource limits."""
    if value is None:
        return DockerResourceSpec()
    if not isinstance(value, dict):
        msg = "sandbox docker resources must be a mapping"
        raise ValueError(msg)
    return DockerResourceSpec(
        cpu=_normalize_optional_string(value.get("cpu"), "sandbox docker resources cpu"),
        memory=_normalize_optional_string(
            value.get("memory"),
            "sandbox docker resources memory",
        ),
        shm_size=_normalize_optional_string(
            value.get("shm_size"),
            "sandbox docker resources shm_size",
        ),
        pids_limit=_parse_non_negative_int(
            value.get("pids_limit"),
            "sandbox docker resources pids_limit",
        ),
    )


def _parse_kubernetes_resource_requirements(
    value: Any,
) -> KubernetesResourceRequirements:
    """Parse Kubernetes resource requests/limits."""
    if value is None:
        return KubernetesResourceRequirements()
    if not isinstance(value, dict):
        msg = "sandbox kubernetes resources must be a mapping"
        raise ValueError(msg)
    return KubernetesResourceRequirements(
        requests=_normalize_string_map(
            value.get("requests"),
            "sandbox kubernetes resources requests",
        ),
        limits=_normalize_string_map(
            value.get("limits"),
            "sandbox kubernetes resources limits",
        ),
    )


def _sandbox_raw_uses_explicit_schema(raw: dict[str, Any]) -> bool:
    """Return whether a raw sandbox mapping uses the new explicit schema."""
    return any(
        key in raw
        for key in ("execution", "env", "setup_commands", "local", "docker", "kubernetes")
    )


def _parse_explicit_sandbox_spec(raw: dict[str, Any]) -> SandboxSpec:
    """Parse the explicit sandbox schema from YAML/proto-converted input."""
    execution = _parse_sandbox_execution_policy(raw.get("execution"))
    env = _parse_sandbox_env(raw.get("env"))
    setup_commands = _parse_setup_commands(
        raw.get("setup_commands"),
        "sandbox setup_commands",
    )

    backend_keys = [
        key for key in ("local", "docker", "kubernetes")
        if key in raw and raw.get(key) is not None
    ]
    if len(backend_keys) != 1:
        msg = "sandbox must define exactly one backend block"
        raise ValueError(msg)

    backend_key = backend_keys[0]
    backend_value = raw.get(backend_key)
    if backend_key == "local":
        if not isinstance(backend_value, dict):
            msg = "sandbox local must be a mapping"
            raise ValueError(msg)
        backend: SandboxBackendConfig = LocalSandboxSpec()
    elif backend_key == "docker":
        if not isinstance(backend_value, dict):
            msg = "sandbox docker must be a mapping"
            raise ValueError(msg)
        backend = DockerSandboxSpec(
            image=_parse_image_reference(
                backend_value.get("image"),
                "sandbox docker image",
                required=True,
            ),
            resources=_parse_docker_resource_spec(backend_value.get("resources")),
        )
    else:
        if not isinstance(backend_value, dict):
            msg = "sandbox kubernetes must be a mapping"
            raise ValueError(msg)
        backend = KubernetesSandboxSpec(
            image=_parse_image_reference(
                backend_value.get("image"),
                "sandbox kubernetes image",
                required=True,
            ),
            resources=_parse_kubernetes_resource_requirements(
                backend_value.get("resources"),
            ),
        )

    return SandboxSpec(
        execution=execution,
        env=env,
        setup_commands=setup_commands,
        backend=backend,
    )


def _legacy_kubernetes_resources(
    resources: dict[str, Any],
) -> KubernetesResourceRequirements:
    """Map legacy flat resource fields into the minimal Kubernetes shape."""
    limits: dict[str, str] = {}
    for key in ("cpu", "memory"):
        value = _normalize_optional_string(resources.get(key), f"sandbox resource {key}")
        if value:
            limits[key] = value
    return KubernetesResourceRequirements(limits=limits)


def _parse_legacy_sandbox_spec(raw: dict[str, Any]) -> SandboxSpec:
    """Parse the deprecated implicit sandbox schema."""
    resources = raw.get("resources") or {}
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
    elif raw.get("image"):
        normalized = SandboxBackendKind.DOCKER.value
    else:
        normalized = SandboxBackendKind.LOCAL.value

    normalized = _SANDBOX_BACKEND_ALIASES.get(normalized, normalized)
    if normalized not in _SUPPORTED_SANDBOX_BACKENDS:
        allowed = ", ".join(sorted(_SUPPORTED_SANDBOX_BACKENDS))
        msg = f"sandbox backend '{normalized}' must be one of: {allowed}"
        raise ValueError(msg)

    execution = SandboxExecutionPolicy(
        max_output_bytes=_parse_non_negative_int(
            resources.get("max_output_bytes"),
            "sandbox resources max_output_bytes",
        )
    )
    setup_commands = _parse_setup_commands(raw.get("init"), "sandbox init")

    if normalized == SandboxBackendKind.LOCAL.value:
        backend: SandboxBackendConfig = LocalSandboxSpec()
    elif normalized == SandboxBackendKind.DOCKER.value:
        image = _normalize_optional_string(raw.get("image"), "sandbox image")
        backend = DockerSandboxSpec(
            image=ImageReference(reference=image or _DEFAULT_DOCKER_IMAGE),
            resources=DockerResourceSpec(
                cpu=_normalize_optional_string(resources.get("cpu"), "sandbox resource cpu"),
                memory=_normalize_optional_string(
                    resources.get("memory"),
                    "sandbox resource memory",
                ),
                shm_size=_normalize_optional_string(
                    resources.get("shm_size"),
                    "sandbox resource shm_size",
                ),
                pids_limit=_parse_non_negative_int(
                    resources.get("pids_limit"),
                    "sandbox resource pids_limit",
                ),
            ),
        )
    else:
        image = _normalize_optional_string(raw.get("image"), "sandbox image")
        backend = KubernetesSandboxSpec(
            image=ImageReference(reference=image or _DEFAULT_DOCKER_IMAGE),
            resources=_legacy_kubernetes_resources(resources),
        )

    return SandboxSpec(
        execution=execution,
        setup_commands=setup_commands,
        backend=backend,
    )


def parse_sandbox_spec(value: Any) -> SandboxSpec | None:
    """Normalize sandbox input from YAML, tests, or proto conversion."""
    if value is None:
        return None
    if isinstance(value, SandboxSpec):
        return value
    if not isinstance(value, dict):
        msg = "sandbox must be a mapping"
        raise ValueError(msg)
    if not value:
        return None
    if _sandbox_raw_uses_explicit_schema(value):
        return _parse_explicit_sandbox_spec(value)
    return _parse_legacy_sandbox_spec(value)


def sandbox_spec_to_dict(spec: SandboxSpec | None) -> dict[str, Any]:
    """Serialize one normalized sandbox spec into a YAML-friendly mapping."""
    if spec is None:
        return {}

    data: dict[str, Any] = {}
    if spec.execution != SandboxExecutionPolicy():
        execution: dict[str, Any] = {}
        if spec.execution.command_timeout_seconds > 0:
            execution["command_timeout_seconds"] = spec.execution.command_timeout_seconds
        if spec.execution.setup_timeout_seconds > 0:
            execution["setup_timeout_seconds"] = spec.execution.setup_timeout_seconds
        if spec.execution.startup_timeout_seconds > 0:
            execution["startup_timeout_seconds"] = spec.execution.startup_timeout_seconds
        if spec.execution.max_output_bytes > 0:
            execution["max_output_bytes"] = spec.execution.max_output_bytes
        if execution:
            data["execution"] = execution

    if spec.env:
        data["env"] = [
            {"name": item.name, "value": item.value}
            for item in spec.env
        ]
    if spec.setup_commands:
        data["setup_commands"] = list(spec.setup_commands)

    backend = spec.backend
    if isinstance(backend, LocalSandboxSpec):
        data["local"] = {}
    elif isinstance(backend, DockerSandboxSpec):
        docker: dict[str, Any] = {
            "image": {
                "reference": backend.image.reference,
            }
        }
        if backend.image.pull_policy is not ImagePullPolicy.UNSPECIFIED:
            docker["image"]["pull_policy"] = backend.image.pull_policy.value
        resources: dict[str, Any] = {}
        if backend.resources.cpu:
            resources["cpu"] = backend.resources.cpu
        if backend.resources.memory:
            resources["memory"] = backend.resources.memory
        if backend.resources.shm_size:
            resources["shm_size"] = backend.resources.shm_size
        if backend.resources.pids_limit > 0:
            resources["pids_limit"] = backend.resources.pids_limit
        if resources:
            docker["resources"] = resources
        data["docker"] = docker
    elif isinstance(backend, KubernetesSandboxSpec):
        kubernetes: dict[str, Any] = {
            "image": {
                "reference": backend.image.reference,
            }
        }
        if backend.image.pull_policy is not ImagePullPolicy.UNSPECIFIED:
            kubernetes["image"]["pull_policy"] = backend.image.pull_policy.value
        resources: dict[str, Any] = {}
        if backend.resources.requests:
            resources["requests"] = dict(backend.resources.requests)
        if backend.resources.limits:
            resources["limits"] = dict(backend.resources.limits)
        if resources:
            kubernetes["resources"] = resources
        data["kubernetes"] = kubernetes

    return data


def resolve_sandbox_backend_kind(spec: SandboxSpec | dict[str, Any]) -> str:
    """Return the canonical backend kind for a normalized or legacy sandbox spec."""
    normalized = parse_sandbox_spec(spec)
    if normalized is None or normalized.backend is None:
        msg = "sandbox backend must be set"
        raise ValueError(msg)
    if isinstance(normalized.backend, LocalSandboxSpec):
        return SandboxBackendKind.LOCAL.value
    if isinstance(normalized.backend, DockerSandboxSpec):
        return SandboxBackendKind.DOCKER.value
    return SandboxBackendKind.KUBERNETES.value


def _validate_sandbox_spec(spec: SandboxSpec) -> None:
    """Validate one normalized sandbox spec before persistence or assembly."""
    backend = spec.backend
    if backend is None:
        msg = "sandbox backend must be set"
        raise ValueError(msg)

    if spec.execution.command_timeout_seconds < 0:
        raise ValueError("sandbox execution command_timeout_seconds must be non-negative")
    if spec.execution.setup_timeout_seconds < 0:
        raise ValueError("sandbox execution setup_timeout_seconds must be non-negative")
    if spec.execution.startup_timeout_seconds < 0:
        raise ValueError("sandbox execution startup_timeout_seconds must be non-negative")
    if spec.execution.max_output_bytes < 0:
        raise ValueError("sandbox execution max_output_bytes must be non-negative")

    env_names: list[str] = []
    for env_var in spec.env:
        env_names.append(_require_non_empty(env_var.name, "sandbox env name"))
    _validate_unique(env_names, "sandbox env names")

    for index, command in enumerate(spec.setup_commands):
        _require_non_empty(command, f"sandbox setup_commands[{index}]")

    if isinstance(backend, DockerSandboxSpec):
        _require_non_empty(backend.image.reference, "sandbox docker image")
        if backend.resources.pids_limit < 0:
            raise ValueError("sandbox docker resources pids_limit must be non-negative")
    elif isinstance(backend, KubernetesSandboxSpec):
        _require_non_empty(backend.image.reference, "sandbox kubernetes image")
        _normalize_string_map(
            backend.resources.requests,
            "sandbox kubernetes resources requests",
        )
        _normalize_string_map(
            backend.resources.limits,
            "sandbox kubernetes resources limits",
        )


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

    sandbox = spec.sandbox
    if sandbox is not None:
        _validate_sandbox_spec(sandbox)


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
