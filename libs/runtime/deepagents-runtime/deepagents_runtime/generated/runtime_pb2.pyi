import datetime

from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

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
    decisions: _containers.RepeatedCompositeFieldContainer[ToolDecision]
    def __init__(self, interrupt_id: _Optional[str] = ..., decisions: _Optional[_Iterable[_Union[ToolDecision, _Mapping]]] = ...) -> None: ...

class ToolDecision(_message.Message):
    __slots__ = ("tool_call_id", "approved", "reason")
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    APPROVED_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    tool_call_id: str
    approved: bool
    reason: str
    def __init__(self, tool_call_id: _Optional[str] = ..., approved: bool = ..., reason: _Optional[str] = ...) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class AgentEvent(_message.Message):
    __slots__ = ("run_id", "agent_name", "timestamp", "run_started", "text_delta", "text_done", "tool_call_start", "tool_call_done", "tool_result", "hitl_request", "run_ended", "error")
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
    def __init__(self, run_id: _Optional[str] = ..., agent_name: _Optional[str] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., run_started: _Optional[_Union[RunStarted, _Mapping]] = ..., text_delta: _Optional[_Union[TextDelta, _Mapping]] = ..., text_done: _Optional[_Union[TextDone, _Mapping]] = ..., tool_call_start: _Optional[_Union[ToolCallStart, _Mapping]] = ..., tool_call_done: _Optional[_Union[ToolCallDone, _Mapping]] = ..., tool_result: _Optional[_Union[ToolResult, _Mapping]] = ..., hitl_request: _Optional[_Union[HITLRequest, _Mapping]] = ..., run_ended: _Optional[_Union[RunEnded, _Mapping]] = ..., error: _Optional[_Union[ErrorOccurred, _Mapping]] = ...) -> None: ...

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
    __slots__ = ("tool_call_id", "content", "is_error")
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IS_ERROR_FIELD_NUMBER: _ClassVar[int]
    tool_call_id: str
    content: str
    is_error: bool
    def __init__(self, tool_call_id: _Optional[str] = ..., content: _Optional[str] = ..., is_error: bool = ...) -> None: ...

class HITLRequest(_message.Message):
    __slots__ = ("interrupt_id", "action_requests")
    INTERRUPT_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_REQUESTS_FIELD_NUMBER: _ClassVar[int]
    interrupt_id: str
    action_requests: _containers.RepeatedCompositeFieldContainer[ActionRequest]
    def __init__(self, interrupt_id: _Optional[str] = ..., action_requests: _Optional[_Iterable[_Union[ActionRequest, _Mapping]]] = ...) -> None: ...

class ActionRequest(_message.Message):
    __slots__ = ("action", "tool_call_id", "args")
    ACTION_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    action: str
    tool_call_id: str
    args: _struct_pb2.Struct
    def __init__(self, action: _Optional[str] = ..., tool_call_id: _Optional[str] = ..., args: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class RunEnded(_message.Message):
    __slots__ = ("stats",)
    STATS_FIELD_NUMBER: _ClassVar[int]
    stats: UsageStats
    def __init__(self, stats: _Optional[_Union[UsageStats, _Mapping]] = ...) -> None: ...

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

class SyncSkillRequest(_message.Message):
    __slots__ = ("name", "content", "description", "tags")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    name: str
    content: str
    description: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, name: _Optional[str] = ..., content: _Optional[str] = ..., description: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ...) -> None: ...

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
    __slots__ = ("name", "description", "system_prompt", "model", "source", "path")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    system_prompt: str
    model: str
    source: str
    path: str
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., system_prompt: _Optional[str] = ..., model: _Optional[str] = ..., source: _Optional[str] = ..., path: _Optional[str] = ...) -> None: ...

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
    __slots__ = ("system", "memory")
    SYSTEM_FIELD_NUMBER: _ClassVar[int]
    MEMORY_FIELD_NUMBER: _ClassVar[int]
    system: str
    memory: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, system: _Optional[str] = ..., memory: _Optional[_Iterable[str]] = ...) -> None: ...

class ToolsSpec(_message.Message):
    __slots__ = ("builtins", "mcp")
    BUILTINS_FIELD_NUMBER: _ClassVar[int]
    MCP_FIELD_NUMBER: _ClassVar[int]
    builtins: _containers.RepeatedScalarFieldContainer[str]
    mcp: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, builtins: _Optional[_Iterable[str]] = ..., mcp: _Optional[_Iterable[str]] = ...) -> None: ...

class SandboxSpec(_message.Message):
    __slots__ = ("image", "resources", "init")
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
    image: str
    resources: _containers.ScalarMap[str, str]
    init: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, image: _Optional[str] = ..., resources: _Optional[_Mapping[str, str]] = ..., init: _Optional[_Iterable[str]] = ...) -> None: ...

class SkillContent(_message.Message):
    __slots__ = ("name", "content")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    name: str
    content: str
    def __init__(self, name: _Optional[str] = ..., content: _Optional[str] = ...) -> None: ...

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

class HealthResponse(_message.Message):
    __slots__ = ("status", "assembled_agent_count", "uptime_seconds")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ASSEMBLED_AGENT_COUNT_FIELD_NUMBER: _ClassVar[int]
    UPTIME_SECONDS_FIELD_NUMBER: _ClassVar[int]
    status: str
    assembled_agent_count: int
    uptime_seconds: float
    def __init__(self, status: _Optional[str] = ..., assembled_agent_count: _Optional[int] = ..., uptime_seconds: _Optional[float] = ...) -> None: ...
