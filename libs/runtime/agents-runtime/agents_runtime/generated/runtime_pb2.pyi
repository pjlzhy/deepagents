import datetime

from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ImagePullPolicy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    IMAGE_PULL_POLICY_UNSPECIFIED: _ClassVar[ImagePullPolicy]
    IMAGE_PULL_POLICY_IF_NOT_PRESENT: _ClassVar[ImagePullPolicy]
    IMAGE_PULL_POLICY_ALWAYS: _ClassVar[ImagePullPolicy]
    IMAGE_PULL_POLICY_NEVER: _ClassVar[ImagePullPolicy]

class AgentRuntimeStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AGENT_RUNTIME_STATUS_UNSPECIFIED: _ClassVar[AgentRuntimeStatus]
    AGENT_RUNTIME_STATUS_UNKNOWN: _ClassVar[AgentRuntimeStatus]
    AGENT_RUNTIME_STATUS_INSTALLED: _ClassVar[AgentRuntimeStatus]
    AGENT_RUNTIME_STATUS_COMPILED: _ClassVar[AgentRuntimeStatus]
    AGENT_RUNTIME_STATUS_RUNNING: _ClassVar[AgentRuntimeStatus]

class SessionHistoryMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SESSION_HISTORY_MODE_UNSPECIFIED: _ClassVar[SessionHistoryMode]
    SESSION_HISTORY_MODE_RESUME_VIEW: _ClassVar[SessionHistoryMode]
    SESSION_HISTORY_MODE_FULL_TRANSCRIPT: _ClassVar[SessionHistoryMode]

class SessionMessageRole(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SESSION_MESSAGE_ROLE_UNSPECIFIED: _ClassVar[SessionMessageRole]
    SESSION_MESSAGE_ROLE_SYSTEM: _ClassVar[SessionMessageRole]
    SESSION_MESSAGE_ROLE_HUMAN: _ClassVar[SessionMessageRole]
    SESSION_MESSAGE_ROLE_AI: _ClassVar[SessionMessageRole]
    SESSION_MESSAGE_ROLE_TOOL: _ClassVar[SessionMessageRole]
IMAGE_PULL_POLICY_UNSPECIFIED: ImagePullPolicy
IMAGE_PULL_POLICY_IF_NOT_PRESENT: ImagePullPolicy
IMAGE_PULL_POLICY_ALWAYS: ImagePullPolicy
IMAGE_PULL_POLICY_NEVER: ImagePullPolicy
AGENT_RUNTIME_STATUS_UNSPECIFIED: AgentRuntimeStatus
AGENT_RUNTIME_STATUS_UNKNOWN: AgentRuntimeStatus
AGENT_RUNTIME_STATUS_INSTALLED: AgentRuntimeStatus
AGENT_RUNTIME_STATUS_COMPILED: AgentRuntimeStatus
AGENT_RUNTIME_STATUS_RUNNING: AgentRuntimeStatus
SESSION_HISTORY_MODE_UNSPECIFIED: SessionHistoryMode
SESSION_HISTORY_MODE_RESUME_VIEW: SessionHistoryMode
SESSION_HISTORY_MODE_FULL_TRANSCRIPT: SessionHistoryMode
SESSION_MESSAGE_ROLE_UNSPECIFIED: SessionMessageRole
SESSION_MESSAGE_ROLE_SYSTEM: SessionMessageRole
SESSION_MESSAGE_ROLE_HUMAN: SessionMessageRole
SESSION_MESSAGE_ROLE_AI: SessionMessageRole
SESSION_MESSAGE_ROLE_TOOL: SessionMessageRole

class ClientMessage(_message.Message):
    __slots__ = ("run_request", "hitl_decision", "cancel")
    RUN_REQUEST_FIELD_NUMBER: _ClassVar[int]
    HITL_DECISION_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    run_request: RunRequest
    hitl_decision: HITLDecision
    cancel: CancelRequest
    def __init__(self, run_request: _Optional[_Union[RunRequest, _Mapping]] = ..., hitl_decision: _Optional[_Union[HITLDecision, _Mapping]] = ..., cancel: _Optional[_Union[CancelRequest, _Mapping]] = ...) -> None: ...

class RunRequest(_message.Message):
    __slots__ = ("agent_name", "message", "thread_id", "metadata")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    message: str
    thread_id: str
    metadata: _containers.ScalarMap[str, str]
    def __init__(self, agent_name: _Optional[str] = ..., message: _Optional[str] = ..., thread_id: _Optional[str] = ..., metadata: _Optional[_Mapping[str, str]] = ...) -> None: ...

class HITLDecision(_message.Message):
    __slots__ = ("interrupt_id", "decisions")
    INTERRUPT_ID_FIELD_NUMBER: _ClassVar[int]
    DECISIONS_FIELD_NUMBER: _ClassVar[int]
    interrupt_id: str
    decisions: _containers.RepeatedCompositeFieldContainer[Decision]
    def __init__(self, interrupt_id: _Optional[str] = ..., decisions: _Optional[_Iterable[_Union[Decision, _Mapping]]] = ...) -> None: ...

class Action(_message.Message):
    __slots__ = ("name", "args")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    name: str
    args: _struct_pb2.Struct
    def __init__(self, name: _Optional[str] = ..., args: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class Decision(_message.Message):
    __slots__ = ("type", "message", "edited_action")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    EDITED_ACTION_FIELD_NUMBER: _ClassVar[int]
    type: str
    message: str
    edited_action: Action
    def __init__(self, type: _Optional[str] = ..., message: _Optional[str] = ..., edited_action: _Optional[_Union[Action, _Mapping]] = ...) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class AgentEvent(_message.Message):
    __slots__ = ("run_id", "agent_name", "timestamp", "run_started", "text_delta", "text_done", "tool_call_start", "tool_call_done", "tool_result", "hitl_request", "run_ended", "error", "run_canceled")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    RUN_STARTED_FIELD_NUMBER: _ClassVar[int]
    TEXT_DELTA_FIELD_NUMBER: _ClassVar[int]
    TEXT_DONE_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_START_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_DONE_FIELD_NUMBER: _ClassVar[int]
    TOOL_RESULT_FIELD_NUMBER: _ClassVar[int]
    HITL_REQUEST_FIELD_NUMBER: _ClassVar[int]
    RUN_ENDED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    RUN_CANCELED_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    agent_name: str
    timestamp: _timestamp_pb2.Timestamp
    run_started: RunStarted
    text_delta: TextDelta
    text_done: TextDone
    tool_call_start: ToolCallStart
    tool_call_done: ToolCallDone
    tool_result: ToolResult
    hitl_request: HITLRequest
    run_ended: RunEnded
    error: ErrorOccurred
    run_canceled: RunCanceled
    def __init__(self, run_id: _Optional[str] = ..., agent_name: _Optional[str] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., run_started: _Optional[_Union[RunStarted, _Mapping]] = ..., text_delta: _Optional[_Union[TextDelta, _Mapping]] = ..., text_done: _Optional[_Union[TextDone, _Mapping]] = ..., tool_call_start: _Optional[_Union[ToolCallStart, _Mapping]] = ..., tool_call_done: _Optional[_Union[ToolCallDone, _Mapping]] = ..., tool_result: _Optional[_Union[ToolResult, _Mapping]] = ..., hitl_request: _Optional[_Union[HITLRequest, _Mapping]] = ..., run_ended: _Optional[_Union[RunEnded, _Mapping]] = ..., error: _Optional[_Union[ErrorOccurred, _Mapping]] = ..., run_canceled: _Optional[_Union[RunCanceled, _Mapping]] = ...) -> None: ...

class RunStarted(_message.Message):
    __slots__ = ("thread_id",)
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    def __init__(self, thread_id: _Optional[str] = ...) -> None: ...

class TextDelta(_message.Message):
    __slots__ = ("text",)
    TEXT_FIELD_NUMBER: _ClassVar[int]
    text: str
    def __init__(self, text: _Optional[str] = ...) -> None: ...

class TextDone(_message.Message):
    __slots__ = ("text",)
    TEXT_FIELD_NUMBER: _ClassVar[int]
    text: str
    def __init__(self, text: _Optional[str] = ...) -> None: ...

class ToolCallStart(_message.Message):
    __slots__ = ("tool_name", "tool_call_id", "args")
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    tool_name: str
    tool_call_id: str
    args: _struct_pb2.Struct
    def __init__(self, tool_name: _Optional[str] = ..., tool_call_id: _Optional[str] = ..., args: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class ToolCallDone(_message.Message):
    __slots__ = ("tool_name", "tool_call_id")
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    tool_name: str
    tool_call_id: str
    def __init__(self, tool_name: _Optional[str] = ..., tool_call_id: _Optional[str] = ...) -> None: ...

class ToolResult(_message.Message):
    __slots__ = ("tool_call_id", "content", "is_error", "payload")
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IS_ERROR_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    tool_call_id: str
    content: str
    is_error: bool
    payload: _struct_pb2.Value
    def __init__(self, tool_call_id: _Optional[str] = ..., content: _Optional[str] = ..., is_error: bool = ..., payload: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ...) -> None: ...

class HITLRequest(_message.Message):
    __slots__ = ("interrupt_id", "action_requests", "review_configs")
    INTERRUPT_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_REQUESTS_FIELD_NUMBER: _ClassVar[int]
    REVIEW_CONFIGS_FIELD_NUMBER: _ClassVar[int]
    interrupt_id: str
    action_requests: _containers.RepeatedCompositeFieldContainer[ActionRequest]
    review_configs: _containers.RepeatedCompositeFieldContainer[ReviewConfig]
    def __init__(self, interrupt_id: _Optional[str] = ..., action_requests: _Optional[_Iterable[_Union[ActionRequest, _Mapping]]] = ..., review_configs: _Optional[_Iterable[_Union[ReviewConfig, _Mapping]]] = ...) -> None: ...

class ActionRequest(_message.Message):
    __slots__ = ("name", "args", "description")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    name: str
    args: _struct_pb2.Struct
    description: str
    def __init__(self, name: _Optional[str] = ..., args: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., description: _Optional[str] = ...) -> None: ...

class ReviewConfig(_message.Message):
    __slots__ = ("action_name", "allowed_decisions", "args_schema")
    ACTION_NAME_FIELD_NUMBER: _ClassVar[int]
    ALLOWED_DECISIONS_FIELD_NUMBER: _ClassVar[int]
    ARGS_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    action_name: str
    allowed_decisions: _containers.RepeatedScalarFieldContainer[str]
    args_schema: _struct_pb2.Struct
    def __init__(self, action_name: _Optional[str] = ..., allowed_decisions: _Optional[_Iterable[str]] = ..., args_schema: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class RunEnded(_message.Message):
    __slots__ = ("stats",)
    STATS_FIELD_NUMBER: _ClassVar[int]
    stats: UsageStats
    def __init__(self, stats: _Optional[_Union[UsageStats, _Mapping]] = ...) -> None: ...

class RunCanceled(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class UsageStats(_message.Message):
    __slots__ = ("request_count", "input_tokens", "output_tokens", "wall_time_seconds")
    REQUEST_COUNT_FIELD_NUMBER: _ClassVar[int]
    INPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    WALL_TIME_SECONDS_FIELD_NUMBER: _ClassVar[int]
    request_count: int
    input_tokens: int
    output_tokens: int
    wall_time_seconds: float
    def __init__(self, request_count: _Optional[int] = ..., input_tokens: _Optional[int] = ..., output_tokens: _Optional[int] = ..., wall_time_seconds: _Optional[float] = ...) -> None: ...

class ErrorOccurred(_message.Message):
    __slots__ = ("message", "error_type")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_TYPE_FIELD_NUMBER: _ClassVar[int]
    message: str
    error_type: str
    def __init__(self, message: _Optional[str] = ..., error_type: _Optional[str] = ...) -> None: ...

class TelemetryEvent(_message.Message):
    __slots__ = ("run_id", "agent_name", "timestamp", "ns", "stream_mode", "event_type", "metadata", "payload", "public_event", "event_id", "attempt", "seq", "node_name", "task_id", "model_call_id", "tool_call_id", "interrupt_id", "message_id")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    NS_FIELD_NUMBER: _ClassVar[int]
    STREAM_MODE_FIELD_NUMBER: _ClassVar[int]
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    PUBLIC_EVENT_FIELD_NUMBER: _ClassVar[int]
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    NODE_NAME_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    MODEL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    INTERRUPT_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    agent_name: str
    timestamp: _timestamp_pb2.Timestamp
    ns: _containers.RepeatedScalarFieldContainer[str]
    stream_mode: str
    event_type: str
    metadata: _struct_pb2.Struct
    payload: _struct_pb2.Value
    public_event: AgentEvent
    event_id: str
    attempt: int
    seq: int
    node_name: str
    task_id: str
    model_call_id: str
    tool_call_id: str
    interrupt_id: str
    message_id: str
    def __init__(self, run_id: _Optional[str] = ..., agent_name: _Optional[str] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., ns: _Optional[_Iterable[str]] = ..., stream_mode: _Optional[str] = ..., event_type: _Optional[str] = ..., metadata: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., payload: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ..., public_event: _Optional[_Union[AgentEvent, _Mapping]] = ..., event_id: _Optional[str] = ..., attempt: _Optional[int] = ..., seq: _Optional[int] = ..., node_name: _Optional[str] = ..., task_id: _Optional[str] = ..., model_call_id: _Optional[str] = ..., tool_call_id: _Optional[str] = ..., interrupt_id: _Optional[str] = ..., message_id: _Optional[str] = ...) -> None: ...

class SyncSkillRequest(_message.Message):
    __slots__ = ("name", "content", "description", "tags", "files")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    name: str
    content: str
    description: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    files: _containers.RepeatedCompositeFieldContainer[SkillFile]
    def __init__(self, name: _Optional[str] = ..., content: _Optional[str] = ..., description: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., files: _Optional[_Iterable[_Union[SkillFile, _Mapping]]] = ...) -> None: ...

class SyncMcpRequest(_message.Message):
    __slots__ = ("name", "command", "args", "env", "description")
    class EnvEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    name: str
    command: str
    args: _containers.RepeatedScalarFieldContainer[str]
    env: _containers.ScalarMap[str, str]
    description: str
    def __init__(self, name: _Optional[str] = ..., command: _Optional[str] = ..., args: _Optional[_Iterable[str]] = ..., env: _Optional[_Mapping[str, str]] = ..., description: _Optional[str] = ...) -> None: ...

class SyncAgentSpecRequest(_message.Message):
    __slots__ = ("name", "version", "description", "tags", "model", "prompt", "skills", "tools", "subagents", "sandbox", "interrupt_on", "mcp_servers", "model_config")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    SKILLS_FIELD_NUMBER: _ClassVar[int]
    TOOLS_FIELD_NUMBER: _ClassVar[int]
    SUBAGENTS_FIELD_NUMBER: _ClassVar[int]
    SANDBOX_FIELD_NUMBER: _ClassVar[int]
    INTERRUPT_ON_FIELD_NUMBER: _ClassVar[int]
    MCP_SERVERS_FIELD_NUMBER: _ClassVar[int]
    MODEL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    name: str
    version: str
    description: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    model: str
    prompt: PromptSpec
    skills: _containers.RepeatedCompositeFieldContainer[SkillContent]
    tools: ToolsSpec
    subagents: _containers.RepeatedCompositeFieldContainer[SubagentSpec]
    sandbox: SandboxSpec
    interrupt_on: _containers.RepeatedScalarFieldContainer[str]
    mcp_servers: _containers.RepeatedCompositeFieldContainer[McpServerConfig]
    model_config: ModelConfig
    def __init__(self, name: _Optional[str] = ..., version: _Optional[str] = ..., description: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., model: _Optional[str] = ..., prompt: _Optional[_Union[PromptSpec, _Mapping]] = ..., skills: _Optional[_Iterable[_Union[SkillContent, _Mapping]]] = ..., tools: _Optional[_Union[ToolsSpec, _Mapping]] = ..., subagents: _Optional[_Iterable[_Union[SubagentSpec, _Mapping]]] = ..., sandbox: _Optional[_Union[SandboxSpec, _Mapping]] = ..., interrupt_on: _Optional[_Iterable[str]] = ..., mcp_servers: _Optional[_Iterable[_Union[McpServerConfig, _Mapping]]] = ..., model_config: _Optional[_Union[ModelConfig, _Mapping]] = ...) -> None: ...

class SubagentSpec(_message.Message):
    __slots__ = ("name", "description", "system_prompt", "model", "skills", "model_config")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    SKILLS_FIELD_NUMBER: _ClassVar[int]
    MODEL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    system_prompt: str
    model: str
    skills: _containers.RepeatedCompositeFieldContainer[SkillContent]
    model_config: ModelConfig
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., system_prompt: _Optional[str] = ..., model: _Optional[str] = ..., skills: _Optional[_Iterable[_Union[SkillContent, _Mapping]]] = ..., model_config: _Optional[_Union[ModelConfig, _Mapping]] = ...) -> None: ...

class McpServerConfig(_message.Message):
    __slots__ = ("name", "command", "args", "env", "transport", "description")
    class EnvEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    TRANSPORT_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    name: str
    command: str
    args: _containers.RepeatedScalarFieldContainer[str]
    env: _containers.ScalarMap[str, str]
    transport: str
    description: str
    def __init__(self, name: _Optional[str] = ..., command: _Optional[str] = ..., args: _Optional[_Iterable[str]] = ..., env: _Optional[_Mapping[str, str]] = ..., transport: _Optional[str] = ..., description: _Optional[str] = ...) -> None: ...

class PromptSpec(_message.Message):
    __slots__ = ("system",)
    SYSTEM_FIELD_NUMBER: _ClassVar[int]
    system: str
    def __init__(self, system: _Optional[str] = ...) -> None: ...

class ToolsSpec(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SandboxSpec(_message.Message):
    __slots__ = ("image", "resources", "init", "execution", "env", "setup_commands", "local", "docker", "kubernetes")
    class ResourcesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_FIELD_NUMBER: _ClassVar[int]
    INIT_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    SETUP_COMMANDS_FIELD_NUMBER: _ClassVar[int]
    LOCAL_FIELD_NUMBER: _ClassVar[int]
    DOCKER_FIELD_NUMBER: _ClassVar[int]
    KUBERNETES_FIELD_NUMBER: _ClassVar[int]
    image: str
    resources: _containers.ScalarMap[str, str]
    init: _containers.RepeatedScalarFieldContainer[str]
    execution: SandboxExecutionPolicy
    env: _containers.RepeatedCompositeFieldContainer[SandboxEnvVar]
    setup_commands: _containers.RepeatedScalarFieldContainer[str]
    local: LocalSandboxSpec
    docker: DockerSandboxSpec
    kubernetes: KubernetesSandboxSpec
    def __init__(self, image: _Optional[str] = ..., resources: _Optional[_Mapping[str, str]] = ..., init: _Optional[_Iterable[str]] = ..., execution: _Optional[_Union[SandboxExecutionPolicy, _Mapping]] = ..., env: _Optional[_Iterable[_Union[SandboxEnvVar, _Mapping]]] = ..., setup_commands: _Optional[_Iterable[str]] = ..., local: _Optional[_Union[LocalSandboxSpec, _Mapping]] = ..., docker: _Optional[_Union[DockerSandboxSpec, _Mapping]] = ..., kubernetes: _Optional[_Union[KubernetesSandboxSpec, _Mapping]] = ...) -> None: ...

class SandboxExecutionPolicy(_message.Message):
    __slots__ = ("command_timeout_seconds", "setup_timeout_seconds", "startup_timeout_seconds", "max_output_bytes")
    COMMAND_TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    SETUP_TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    STARTUP_TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    MAX_OUTPUT_BYTES_FIELD_NUMBER: _ClassVar[int]
    command_timeout_seconds: int
    setup_timeout_seconds: int
    startup_timeout_seconds: int
    max_output_bytes: int
    def __init__(self, command_timeout_seconds: _Optional[int] = ..., setup_timeout_seconds: _Optional[int] = ..., startup_timeout_seconds: _Optional[int] = ..., max_output_bytes: _Optional[int] = ...) -> None: ...

class SandboxEnvVar(_message.Message):
    __slots__ = ("name", "value")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    name: str
    value: str
    def __init__(self, name: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

class LocalSandboxSpec(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ImageReference(_message.Message):
    __slots__ = ("reference", "pull_policy")
    REFERENCE_FIELD_NUMBER: _ClassVar[int]
    PULL_POLICY_FIELD_NUMBER: _ClassVar[int]
    reference: str
    pull_policy: ImagePullPolicy
    def __init__(self, reference: _Optional[str] = ..., pull_policy: _Optional[_Union[ImagePullPolicy, str]] = ...) -> None: ...

class DockerSandboxSpec(_message.Message):
    __slots__ = ("image", "resources")
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_FIELD_NUMBER: _ClassVar[int]
    image: ImageReference
    resources: DockerResourceSpec
    def __init__(self, image: _Optional[_Union[ImageReference, _Mapping]] = ..., resources: _Optional[_Union[DockerResourceSpec, _Mapping]] = ...) -> None: ...

class DockerResourceSpec(_message.Message):
    __slots__ = ("cpu", "memory", "shm_size", "pids_limit")
    CPU_FIELD_NUMBER: _ClassVar[int]
    MEMORY_FIELD_NUMBER: _ClassVar[int]
    SHM_SIZE_FIELD_NUMBER: _ClassVar[int]
    PIDS_LIMIT_FIELD_NUMBER: _ClassVar[int]
    cpu: str
    memory: str
    shm_size: str
    pids_limit: int
    def __init__(self, cpu: _Optional[str] = ..., memory: _Optional[str] = ..., shm_size: _Optional[str] = ..., pids_limit: _Optional[int] = ...) -> None: ...

class KubernetesSandboxSpec(_message.Message):
    __slots__ = ("image", "resources")
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_FIELD_NUMBER: _ClassVar[int]
    image: ImageReference
    resources: KubernetesResourceRequirements
    def __init__(self, image: _Optional[_Union[ImageReference, _Mapping]] = ..., resources: _Optional[_Union[KubernetesResourceRequirements, _Mapping]] = ...) -> None: ...

class KubernetesResourceRequirements(_message.Message):
    __slots__ = ("requests", "limits")
    class RequestsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class LimitsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    REQUESTS_FIELD_NUMBER: _ClassVar[int]
    LIMITS_FIELD_NUMBER: _ClassVar[int]
    requests: _containers.ScalarMap[str, str]
    limits: _containers.ScalarMap[str, str]
    def __init__(self, requests: _Optional[_Mapping[str, str]] = ..., limits: _Optional[_Mapping[str, str]] = ...) -> None: ...

class SkillFile(_message.Message):
    __slots__ = ("path", "content")
    PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    path: str
    content: str
    def __init__(self, path: _Optional[str] = ..., content: _Optional[str] = ...) -> None: ...

class SkillContent(_message.Message):
    __slots__ = ("name", "content", "files")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    name: str
    content: str
    files: _containers.RepeatedCompositeFieldContainer[SkillFile]
    def __init__(self, name: _Optional[str] = ..., content: _Optional[str] = ..., files: _Optional[_Iterable[_Union[SkillFile, _Mapping]]] = ...) -> None: ...

class ModelConfig(_message.Message):
    __slots__ = ("provider", "model", "base_url", "api_key", "api_key_env", "extra_params")
    class ExtraParamsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    API_KEY_ENV_FIELD_NUMBER: _ClassVar[int]
    EXTRA_PARAMS_FIELD_NUMBER: _ClassVar[int]
    provider: str
    model: str
    base_url: str
    api_key: str
    api_key_env: str
    extra_params: _containers.ScalarMap[str, str]
    def __init__(self, provider: _Optional[str] = ..., model: _Optional[str] = ..., base_url: _Optional[str] = ..., api_key: _Optional[str] = ..., api_key_env: _Optional[str] = ..., extra_params: _Optional[_Mapping[str, str]] = ...) -> None: ...

class AssembleRequest(_message.Message):
    __slots__ = ("agent_name",)
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    def __init__(self, agent_name: _Optional[str] = ...) -> None: ...

class AssembleResponse(_message.Message):
    __slots__ = ("ok", "message", "status")
    OK_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    message: str
    status: str
    def __init__(self, ok: bool = ..., message: _Optional[str] = ..., status: _Optional[str] = ...) -> None: ...

class GetAgentGraphRequest(_message.Message):
    __slots__ = ("agent_name", "xray_depth")
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    XRAY_DEPTH_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    xray_depth: int
    def __init__(self, agent_name: _Optional[str] = ..., xray_depth: _Optional[int] = ...) -> None: ...

class GetAgentGraphResponse(_message.Message):
    __slots__ = ("graph",)
    GRAPH_FIELD_NUMBER: _ClassVar[int]
    graph: _struct_pb2.Value
    def __init__(self, graph: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ...) -> None: ...

class UploadWorkspaceFileMetadata(_message.Message):
    __slots__ = ("agent_name", "thread_id", "path")
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    thread_id: str
    path: str
    def __init__(self, agent_name: _Optional[str] = ..., thread_id: _Optional[str] = ..., path: _Optional[str] = ...) -> None: ...

class UploadWorkspaceFileStreamRequest(_message.Message):
    __slots__ = ("metadata", "chunk")
    METADATA_FIELD_NUMBER: _ClassVar[int]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    metadata: UploadWorkspaceFileMetadata
    chunk: bytes
    def __init__(self, metadata: _Optional[_Union[UploadWorkspaceFileMetadata, _Mapping]] = ..., chunk: _Optional[bytes] = ...) -> None: ...

class UploadWorkspaceFileStreamResponse(_message.Message):
    __slots__ = ("thread_id", "path", "error")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    path: str
    error: str
    def __init__(self, thread_id: _Optional[str] = ..., path: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class DownloadWorkspaceFileStreamRequest(_message.Message):
    __slots__ = ("agent_name", "thread_id", "path")
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    thread_id: str
    path: str
    def __init__(self, agent_name: _Optional[str] = ..., thread_id: _Optional[str] = ..., path: _Optional[str] = ...) -> None: ...

class DownloadWorkspaceFileChunk(_message.Message):
    __slots__ = ("content",)
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    content: bytes
    def __init__(self, content: _Optional[bytes] = ...) -> None: ...

class ListWorkspaceFilesRequest(_message.Message):
    __slots__ = ("agent_name", "thread_id", "path")
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    thread_id: str
    path: str
    def __init__(self, agent_name: _Optional[str] = ..., thread_id: _Optional[str] = ..., path: _Optional[str] = ...) -> None: ...

class WorkspaceFileInfo(_message.Message):
    __slots__ = ("path", "is_dir", "size", "modified_at")
    PATH_FIELD_NUMBER: _ClassVar[int]
    IS_DIR_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    MODIFIED_AT_FIELD_NUMBER: _ClassVar[int]
    path: str
    is_dir: bool
    size: int
    modified_at: str
    def __init__(self, path: _Optional[str] = ..., is_dir: bool = ..., size: _Optional[int] = ..., modified_at: _Optional[str] = ...) -> None: ...

class ListWorkspaceFilesResponse(_message.Message):
    __slots__ = ("thread_id", "files")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    files: _containers.RepeatedCompositeFieldContainer[WorkspaceFileInfo]
    def __init__(self, thread_id: _Optional[str] = ..., files: _Optional[_Iterable[_Union[WorkspaceFileInfo, _Mapping]]] = ...) -> None: ...

class RemoveResourceRequest(_message.Message):
    __slots__ = ("resource_type", "name")
    RESOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    resource_type: str
    name: str
    def __init__(self, resource_type: _Optional[str] = ..., name: _Optional[str] = ...) -> None: ...

class SyncResponse(_message.Message):
    __slots__ = ("ok", "message")
    OK_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    message: str
    def __init__(self, ok: bool = ..., message: _Optional[str] = ...) -> None: ...

class HealthRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AgentHealth(_message.Message):
    __slots__ = ("name", "version", "description", "tags", "status", "active_thread_count", "active_thread_ids", "last_invoked_at")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_THREAD_COUNT_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_THREAD_IDS_FIELD_NUMBER: _ClassVar[int]
    LAST_INVOKED_AT_FIELD_NUMBER: _ClassVar[int]
    name: str
    version: str
    description: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    status: AgentRuntimeStatus
    active_thread_count: int
    active_thread_ids: _containers.RepeatedScalarFieldContainer[str]
    last_invoked_at: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., version: _Optional[str] = ..., description: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., status: _Optional[_Union[AgentRuntimeStatus, str]] = ..., active_thread_count: _Optional[int] = ..., active_thread_ids: _Optional[_Iterable[str]] = ..., last_invoked_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class HealthResponse(_message.Message):
    __slots__ = ("status", "assembled_agent_count", "uptime_seconds", "installed_agent_count", "running_agent_count", "ready", "running_thread_count", "agents")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ASSEMBLED_AGENT_COUNT_FIELD_NUMBER: _ClassVar[int]
    UPTIME_SECONDS_FIELD_NUMBER: _ClassVar[int]
    INSTALLED_AGENT_COUNT_FIELD_NUMBER: _ClassVar[int]
    RUNNING_AGENT_COUNT_FIELD_NUMBER: _ClassVar[int]
    READY_FIELD_NUMBER: _ClassVar[int]
    RUNNING_THREAD_COUNT_FIELD_NUMBER: _ClassVar[int]
    AGENTS_FIELD_NUMBER: _ClassVar[int]
    status: str
    assembled_agent_count: int
    uptime_seconds: float
    installed_agent_count: int
    running_agent_count: int
    ready: bool
    running_thread_count: int
    agents: _containers.RepeatedCompositeFieldContainer[AgentHealth]
    def __init__(self, status: _Optional[str] = ..., assembled_agent_count: _Optional[int] = ..., uptime_seconds: _Optional[float] = ..., installed_agent_count: _Optional[int] = ..., running_agent_count: _Optional[int] = ..., ready: bool = ..., running_thread_count: _Optional[int] = ..., agents: _Optional[_Iterable[_Union[AgentHealth, _Mapping]]] = ...) -> None: ...

class ListSessionsRequest(_message.Message):
    __slots__ = ("agent_name", "page_size", "page_token")
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    page_size: int
    page_token: str
    def __init__(self, agent_name: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListSessionsResponse(_message.Message):
    __slots__ = ("sessions", "next_page_token")
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    sessions: _containers.RepeatedCompositeFieldContainer[SessionSummary]
    next_page_token: str
    def __init__(self, sessions: _Optional[_Iterable[_Union[SessionSummary, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class GetSessionRequest(_message.Message):
    __slots__ = ("thread_id", "agent_name")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    agent_name: str
    def __init__(self, thread_id: _Optional[str] = ..., agent_name: _Optional[str] = ...) -> None: ...

class GetSessionResponse(_message.Message):
    __slots__ = ("found", "session")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    SESSION_FIELD_NUMBER: _ClassVar[int]
    found: bool
    session: SessionDetail
    def __init__(self, found: bool = ..., session: _Optional[_Union[SessionDetail, _Mapping]] = ...) -> None: ...

class GetLatestSessionRequest(_message.Message):
    __slots__ = ("agent_name",)
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    def __init__(self, agent_name: _Optional[str] = ...) -> None: ...

class GetLatestSessionResponse(_message.Message):
    __slots__ = ("found", "session")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    SESSION_FIELD_NUMBER: _ClassVar[int]
    found: bool
    session: SessionSummary
    def __init__(self, found: bool = ..., session: _Optional[_Union[SessionSummary, _Mapping]] = ...) -> None: ...

class DeleteSessionRequest(_message.Message):
    __slots__ = ("thread_id", "agent_name")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    agent_name: str
    def __init__(self, thread_id: _Optional[str] = ..., agent_name: _Optional[str] = ...) -> None: ...

class DeleteSessionResponse(_message.Message):
    __slots__ = ("deleted",)
    DELETED_FIELD_NUMBER: _ClassVar[int]
    deleted: bool
    def __init__(self, deleted: bool = ...) -> None: ...

class GetSessionMessagesRequest(_message.Message):
    __slots__ = ("thread_id", "checkpoint_id", "page_size", "page_token", "requested_mode", "include_raw", "agent_name")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_MODE_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_RAW_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    checkpoint_id: str
    page_size: int
    page_token: str
    requested_mode: SessionHistoryMode
    include_raw: bool
    agent_name: str
    def __init__(self, thread_id: _Optional[str] = ..., checkpoint_id: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., requested_mode: _Optional[_Union[SessionHistoryMode, str]] = ..., include_raw: bool = ..., agent_name: _Optional[str] = ...) -> None: ...

class GetSessionMessagesResponse(_message.Message):
    __slots__ = ("thread_id", "resolved_checkpoint_id", "actual_mode", "total_message_count", "messages", "next_page_token")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    RESOLVED_CHECKPOINT_ID_FIELD_NUMBER: _ClassVar[int]
    ACTUAL_MODE_FIELD_NUMBER: _ClassVar[int]
    TOTAL_MESSAGE_COUNT_FIELD_NUMBER: _ClassVar[int]
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    resolved_checkpoint_id: str
    actual_mode: SessionHistoryMode
    total_message_count: int
    messages: _containers.RepeatedCompositeFieldContainer[SessionMessage]
    next_page_token: str
    def __init__(self, thread_id: _Optional[str] = ..., resolved_checkpoint_id: _Optional[str] = ..., actual_mode: _Optional[_Union[SessionHistoryMode, str]] = ..., total_message_count: _Optional[int] = ..., messages: _Optional[_Iterable[_Union[SessionMessage, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class SessionSummary(_message.Message):
    __slots__ = ("thread_id", "agent_name", "updated_at", "latest_checkpoint_id", "message_count", "initial_prompt", "history_mode", "agent_status")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    LATEST_CHECKPOINT_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_COUNT_FIELD_NUMBER: _ClassVar[int]
    INITIAL_PROMPT_FIELD_NUMBER: _ClassVar[int]
    HISTORY_MODE_FIELD_NUMBER: _ClassVar[int]
    AGENT_STATUS_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    agent_name: str
    updated_at: _timestamp_pb2.Timestamp
    latest_checkpoint_id: str
    message_count: int
    initial_prompt: str
    history_mode: SessionHistoryMode
    agent_status: AgentRuntimeStatus
    def __init__(self, thread_id: _Optional[str] = ..., agent_name: _Optional[str] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., latest_checkpoint_id: _Optional[str] = ..., message_count: _Optional[int] = ..., initial_prompt: _Optional[str] = ..., history_mode: _Optional[_Union[SessionHistoryMode, str]] = ..., agent_status: _Optional[_Union[AgentRuntimeStatus, str]] = ...) -> None: ...

class SessionDetail(_message.Message):
    __slots__ = ("summary", "checkpoint_count")
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_COUNT_FIELD_NUMBER: _ClassVar[int]
    summary: SessionSummary
    checkpoint_count: int
    def __init__(self, summary: _Optional[_Union[SessionSummary, _Mapping]] = ..., checkpoint_count: _Optional[int] = ...) -> None: ...

class SessionMessage(_message.Message):
    __slots__ = ("index", "role", "text", "tool_call_id", "tool_name", "is_error", "raw")
    INDEX_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    IS_ERROR_FIELD_NUMBER: _ClassVar[int]
    RAW_FIELD_NUMBER: _ClassVar[int]
    index: int
    role: SessionMessageRole
    text: str
    tool_call_id: str
    tool_name: str
    is_error: bool
    raw: _struct_pb2.Struct
    def __init__(self, index: _Optional[int] = ..., role: _Optional[_Union[SessionMessageRole, str]] = ..., text: _Optional[str] = ..., tool_call_id: _Optional[str] = ..., tool_name: _Optional[str] = ..., is_error: bool = ..., raw: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class ListThreadArtifactsRequest(_message.Message):
    __slots__ = ("thread_id", "agent_name")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    agent_name: str
    def __init__(self, thread_id: _Optional[str] = ..., agent_name: _Optional[str] = ...) -> None: ...

class ThreadArtifact(_message.Message):
    __slots__ = ("id", "type", "path", "title", "content_type", "language", "created_by_tool", "created_at", "modified_at", "size")
    ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_TOOL_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    MODIFIED_AT_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    id: str
    type: str
    path: str
    title: str
    content_type: str
    language: str
    created_by_tool: str
    created_at: str
    modified_at: str
    size: int
    def __init__(self, id: _Optional[str] = ..., type: _Optional[str] = ..., path: _Optional[str] = ..., title: _Optional[str] = ..., content_type: _Optional[str] = ..., language: _Optional[str] = ..., created_by_tool: _Optional[str] = ..., created_at: _Optional[str] = ..., modified_at: _Optional[str] = ..., size: _Optional[int] = ...) -> None: ...

class ListThreadArtifactsResponse(_message.Message):
    __slots__ = ("thread_id", "artifacts")
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    thread_id: str
    artifacts: _containers.RepeatedCompositeFieldContainer[ThreadArtifact]
    def __init__(self, thread_id: _Optional[str] = ..., artifacts: _Optional[_Iterable[_Union[ThreadArtifact, _Mapping]]] = ...) -> None: ...
