"""Converters between RuntimeEvent (Python) and protobuf messages.

This module provides the serialization boundary between the internal
RuntimeEvent dataclass and the gRPC AgentEvent / ClientMessage protobufs.
"""

from __future__ import annotations

import math
import time
from typing import Any

from google.protobuf import struct_pb2, timestamp_pb2

from deepagents_runtime.events import RuntimeEvent
from deepagents_runtime.generated import runtime_pb2 as pb2
from deepagents_runtime.spec import (
    AgentSpec,
    McpConfig,
    ModelConfigSpec,
    RuntimeEventType,
    SkillContentItem,
    SkillFileSpec,
    SkillSpec,
    SubagentMetadata,
)


# ══════════════════════════════════════════════════════════════════
#  RuntimeEvent → AgentEvent (server side: Python → protobuf)
# ══════════════════════════════════════════════════════════════════


def runtime_event_to_agent_event(event: RuntimeEvent) -> pb2.AgentEvent:
    """Convert a RuntimeEvent to a protobuf AgentEvent.

    Returns an ``AgentEvent`` message ready to be sent over gRPC.

    Raises:
        ValueError: If the RuntimeEvent type is not part of the public
            gRPC AgentEvent contract.
    """
    ts = _float_timestamp_to_proto(event.timestamp)

    kwargs: dict[str, Any] = {
        "run_id": event.run_id,
        "agent_name": event.agent_name,
        "timestamp": ts,
    }

    if event.type == RuntimeEventType.RUN_START:
        kwargs["run_started"] = pb2.RunStarted(
            thread_id=event.data.get("thread_id", ""),
        )
    elif event.type == RuntimeEventType.TEXT_DELTA:
        kwargs["text_delta"] = pb2.TextDelta(
            text=event.data.get("text", ""),
        )
    elif event.type == RuntimeEventType.TEXT_DONE:
        kwargs["text_done"] = pb2.TextDone(
            text=event.data.get("text", ""),
        )
    elif event.type == RuntimeEventType.TOOL_CALL_START:
        tool_call_kwargs: dict[str, Any] = {
            "tool_name": event.data.get("tool_name", ""),
            "tool_call_id": event.data.get("tool_call_id", ""),
        }
        args = event.data.get("args")
        if isinstance(args, dict):
            tool_call_kwargs["args"] = _dict_to_struct(args)
        kwargs["tool_call_start"] = pb2.ToolCallStart(**tool_call_kwargs)
    elif event.type == RuntimeEventType.TOOL_CALL_DONE:
        kwargs["tool_call_done"] = pb2.ToolCallDone(
            tool_name=event.data.get("tool_name", ""),
            tool_call_id=event.data.get("tool_call_id", ""),
        )
    elif event.type == RuntimeEventType.TOOL_RESULT:
        tool_result_kwargs: dict[str, Any] = {
            "tool_call_id": event.data.get("tool_call_id", ""),
            "content": event.data.get("content", ""),
            "is_error": event.data.get("is_error", False),
        }
        if "payload" in event.data:
            payload_value = _python_to_value(event.data["payload"])
        else:
            payload_value = None
        if payload_value is not None:
            tool_result_kwargs["payload"] = payload_value
        kwargs["tool_result"] = pb2.ToolResult(**tool_result_kwargs)
    elif event.type == RuntimeEventType.HITL_REQUEST:
        action_requests = []
        for ar in event.data.get("action_requests", []):
            action_name = ar.get("name", "") or ar.get("action", "")
            action_requests.append(pb2.ActionRequest(
                name=action_name,
                args=_dict_to_struct(ar.get("args", {})),
                description=ar.get("description", ""),
            ))
        review_configs = []
        for config in event.data.get("review_configs", []):
            review_kwargs: dict[str, Any] = {
                "action_name": config.get("action_name", ""),
                "allowed_decisions": list(config.get("allowed_decisions", [])),
            }
            args_schema = config.get("args_schema")
            if isinstance(args_schema, dict):
                review_kwargs["args_schema"] = _dict_to_struct(args_schema)
            review_configs.append(pb2.ReviewConfig(**review_kwargs))
        kwargs["hitl_request"] = pb2.HITLRequest(
            interrupt_id=event.data.get("interrupt_id", ""),
            action_requests=action_requests,
            review_configs=review_configs,
        )
    elif event.type == RuntimeEventType.RUN_END:
        stats = event.data.get("stats", {})
        kwargs["run_ended"] = pb2.RunEnded(
            stats=pb2.UsageStats(
                request_count=stats.get("request_count", 0),
                input_tokens=stats.get("input_tokens", 0),
                output_tokens=stats.get("output_tokens", 0),
                wall_time_seconds=stats.get("wall_time_seconds", 0.0),
            ),
        )
    elif event.type == RuntimeEventType.RUN_CANCELED:
        kwargs["run_canceled"] = pb2.RunCanceled(
            reason=event.data.get("reason", ""),
        )
    elif event.type == RuntimeEventType.ERROR:
        kwargs["error"] = pb2.ErrorOccurred(
            message=event.data.get("message", ""),
            error_type=event.data.get("error_type", ""),
        )
    else:
        msg = f"Unsupported RuntimeEventType for AgentEvent transport: {event.type}"
        raise ValueError(msg)

    return pb2.AgentEvent(**kwargs)


# ══════════════════════════════════════════════════════════════════
#  AgentEvent → RuntimeEvent (client side: protobuf → Python)
# ══════════════════════════════════════════════════════════════════

# AgentEvent oneof field name → RuntimeEventType
_PROTO_FIELD_TO_EVENT_TYPE: dict[str, RuntimeEventType] = {
    "run_started": RuntimeEventType.RUN_START,
    "text_delta": RuntimeEventType.TEXT_DELTA,
    "text_done": RuntimeEventType.TEXT_DONE,
    "tool_call_start": RuntimeEventType.TOOL_CALL_START,
    "tool_call_done": RuntimeEventType.TOOL_CALL_DONE,
    "tool_result": RuntimeEventType.TOOL_RESULT,
    "hitl_request": RuntimeEventType.HITL_REQUEST,
    "run_ended": RuntimeEventType.RUN_END,
    "run_canceled": RuntimeEventType.RUN_CANCELED,
    "error": RuntimeEventType.ERROR,
}


def agent_event_to_runtime_event(msg: pb2.AgentEvent) -> RuntimeEvent:
    """Convert a protobuf AgentEvent to a RuntimeEvent.

    Uses ``WhichOneof("payload")`` to determine which event type is set.
    """
    run_id = msg.run_id
    agent_name = msg.agent_name
    timestamp = msg.timestamp.seconds + msg.timestamp.nanos / 1e9 if msg.HasField("timestamp") else time.time()

    payload_field = msg.WhichOneof("payload")
    if payload_field is None:
        return RuntimeEvent(
            type=RuntimeEventType.ERROR,
            data={"message": "AgentEvent has no payload"},
            run_id=run_id,
            agent_name=agent_name,
        )

    event_type = _PROTO_FIELD_TO_EVENT_TYPE.get(payload_field)
    if event_type is None:
        return RuntimeEvent(
            type=RuntimeEventType.ERROR,
            data={"message": f"Unknown payload field: {payload_field}"},
            run_id=run_id,
            agent_name=agent_name,
        )

    payload = getattr(msg, payload_field)
    data = _extract_event_data(event_type, payload)

    return RuntimeEvent(
        type=event_type,
        data=data,
        timestamp=timestamp,
        run_id=run_id,
        agent_name=agent_name,
    )


def _extract_event_data(
    event_type: RuntimeEventType, payload: Any
) -> dict[str, Any]:
    """Extract RuntimeEvent.data from a protobuf payload message."""
    if event_type == RuntimeEventType.RUN_START:
        return {"thread_id": payload.thread_id}
    elif event_type == RuntimeEventType.TEXT_DELTA:
        return {"text": payload.text}
    elif event_type == RuntimeEventType.TEXT_DONE:
        return {"text": payload.text}
    elif event_type == RuntimeEventType.TOOL_CALL_START:
        data = {
            "tool_name": payload.tool_name,
            "tool_call_id": payload.tool_call_id,
        }
        if payload.HasField("args"):
            data["args"] = _struct_to_dict(payload.args)
        return data
    elif event_type == RuntimeEventType.TOOL_CALL_DONE:
        return {
            "tool_name": payload.tool_name,
            "tool_call_id": payload.tool_call_id,
        }
    elif event_type == RuntimeEventType.TOOL_RESULT:
        data = {
            "tool_call_id": payload.tool_call_id,
            "content": payload.content,
            "is_error": payload.is_error,
        }
        if payload.HasField("payload"):
            data["payload"] = _value_to_python(payload.payload)
        return data
    elif event_type == RuntimeEventType.HITL_REQUEST:
        action_requests = []
        for ar in payload.action_requests:
            action_requests.append({
                "name": ar.name,
                "args": _struct_to_dict(ar.args) if ar.HasField("args") else {},
                "description": ar.description,
            })
        review_configs = []
        for config in payload.review_configs:
            review_configs.append({
                "action_name": config.action_name,
                "allowed_decisions": list(config.allowed_decisions),
                "args_schema": (
                    _struct_to_dict(config.args_schema)
                    if config.HasField("args_schema")
                    else {}
                ),
            })
        return {
            "interrupt_id": payload.interrupt_id,
            "action_requests": action_requests,
            "review_configs": review_configs,
        }
    elif event_type == RuntimeEventType.RUN_END:
        stats = payload.stats if payload.HasField("stats") else None
        if stats:
            return {
                "stats": {
                    "request_count": stats.request_count,
                    "input_tokens": stats.input_tokens,
                    "output_tokens": stats.output_tokens,
                    "wall_time_seconds": stats.wall_time_seconds,
                }
            }
        return {"stats": {}}
    elif event_type == RuntimeEventType.RUN_CANCELED:
        return {"reason": payload.reason}
    elif event_type == RuntimeEventType.ERROR:
        return {
            "message": payload.message,
            "error_type": payload.error_type,
        }
    return {}


# ══════════════════════════════════════════════════════════════════
#  Resource Spec Converters (for ResourceSync RPCs)
# ══════════════════════════════════════════════════════════════════


def sync_skill_request_to_skill_spec(msg: pb2.SyncSkillRequest) -> SkillSpec:
    """Convert a SyncSkillRequest protobuf to a SkillSpec."""
    return SkillSpec(
        name=msg.name,
        content=msg.content,
        files=[
            SkillFileSpec(path=file.path, content=file.content)
            for file in msg.files
        ],
        description=msg.description,
        tags=list(msg.tags),
    )


def sync_mcp_request_to_mcp_config(msg: pb2.SyncMcpRequest) -> McpConfig:
    """Convert a SyncMcpRequest protobuf to a McpConfig."""
    return McpConfig(
        name=msg.name,
        command=msg.command,
        args=list(msg.args),
        env=dict(msg.env),
        transport="stdio",
        description=msg.description,
    )


def _image_pull_policy_from_proto(value: int) -> str:
    """Convert a protobuf image pull policy enum into the runtime string value."""
    mapping = {
        pb2.IMAGE_PULL_POLICY_UNSPECIFIED: "",
        pb2.IMAGE_PULL_POLICY_IF_NOT_PRESENT: "if_not_present",
        pb2.IMAGE_PULL_POLICY_ALWAYS: "always",
        pb2.IMAGE_PULL_POLICY_NEVER: "never",
    }
    return mapping.get(value, "")


def _sandbox_from_proto(msg: pb2.SandboxSpec) -> dict[str, Any]:
    """Convert a protobuf sandbox message into the runtime's raw sandbox mapping."""
    sandbox: dict[str, Any] = {}
    if msg.HasField("execution"):
        execution: dict[str, Any] = {}
        if msg.execution.command_timeout_seconds:
            execution["command_timeout_seconds"] = (
                msg.execution.command_timeout_seconds
            )
        if msg.execution.setup_timeout_seconds:
            execution["setup_timeout_seconds"] = (
                msg.execution.setup_timeout_seconds
            )
        if msg.execution.startup_timeout_seconds:
            execution["startup_timeout_seconds"] = (
                msg.execution.startup_timeout_seconds
            )
        if msg.execution.max_output_bytes:
            execution["max_output_bytes"] = msg.execution.max_output_bytes
        if execution:
            sandbox["execution"] = execution

    if msg.env:
        sandbox["env"] = [
            {"name": item.name, "value": item.value}
            for item in msg.env
        ]
    if msg.setup_commands:
        sandbox["setup_commands"] = list(msg.setup_commands)

    backend_field = msg.WhichOneof("backend")
    if backend_field == "local":
        sandbox["local"] = {}
    elif backend_field == "docker":
        docker: dict[str, Any] = {}
        if msg.docker.HasField("image"):
            docker_image: dict[str, Any] = {
                "reference": msg.docker.image.reference,
            }
            pull_policy = _image_pull_policy_from_proto(
                msg.docker.image.pull_policy
            )
            if pull_policy:
                docker_image["pull_policy"] = pull_policy
            docker["image"] = docker_image
        if msg.docker.HasField("resources"):
            resources: dict[str, Any] = {}
            if msg.docker.resources.cpu:
                resources["cpu"] = msg.docker.resources.cpu
            if msg.docker.resources.memory:
                resources["memory"] = msg.docker.resources.memory
            if msg.docker.resources.shm_size:
                resources["shm_size"] = msg.docker.resources.shm_size
            if msg.docker.resources.pids_limit:
                resources["pids_limit"] = msg.docker.resources.pids_limit
            if resources:
                docker["resources"] = resources
        sandbox["docker"] = docker
    elif backend_field == "kubernetes":
        kubernetes: dict[str, Any] = {}
        if msg.kubernetes.HasField("image"):
            kubernetes_image: dict[str, Any] = {
                "reference": msg.kubernetes.image.reference,
            }
            pull_policy = _image_pull_policy_from_proto(
                msg.kubernetes.image.pull_policy
            )
            if pull_policy:
                kubernetes_image["pull_policy"] = pull_policy
            kubernetes["image"] = kubernetes_image
        if msg.kubernetes.HasField("resources"):
            resources: dict[str, Any] = {}
            if msg.kubernetes.resources.requests:
                resources["requests"] = dict(msg.kubernetes.resources.requests)
            if msg.kubernetes.resources.limits:
                resources["limits"] = dict(msg.kubernetes.resources.limits)
            if resources:
                kubernetes["resources"] = resources
        sandbox["kubernetes"] = kubernetes

    if sandbox:
        return sandbox

    return {
        "image": msg.image,
        "resources": dict(msg.resources),
        "init": list(msg.init),
    }


def sync_agent_spec_request_to_agent_spec(msg: pb2.SyncAgentSpecRequest) -> AgentSpec:
    """Convert a SyncAgentSpecRequest protobuf to an AgentSpec."""
    prompt: dict[str, Any] = {}
    if msg.HasField("prompt"):
        prompt = {"system": msg.prompt.system}

    tools: dict[str, Any] = {}

    sandbox: dict[str, Any] = {}
    if msg.HasField("sandbox"):
        sandbox = _sandbox_from_proto(msg.sandbox)

    # Parse structured subagents
    subagents: list[SubagentMetadata] = []
    for sa in msg.subagents:
        sa_meta: SubagentMetadata = {
            "name": sa.name,
            "description": sa.description,
            "system_prompt": sa.system_prompt,
        }
        if sa.model:
            sa_meta["model"] = sa.model
        subagents.append(sa_meta)

    # Parse MCP server configs
    mcp_servers: list[McpConfig] = []
    for mcp in msg.mcp_servers:
        mcp_servers.append(McpConfig(
            name=mcp.name,
            command=mcp.command,
            args=list(mcp.args),
            env=dict(mcp.env),
            transport=mcp.transport or "stdio",
            description=mcp.description,
        ))

    # Parse skills (SkillContent messages → SkillContentItem)
    skills: list[SkillContentItem] = []
    for skill in msg.skills:
        skill_item: SkillContentItem = {
            "name": skill.name,
            "content": skill.content,
        }
        if skill.files:
            skill_item["files"] = [
                {"path": file.path, "content": file.content}
                for file in skill.files
            ]
        skills.append(skill_item)

    # Parse model_config
    model_config: ModelConfigSpec | None = None
    if msg.HasField("model_config"):
        mc = msg.model_config
        model_config = {}
        if mc.provider:
            model_config["provider"] = mc.provider
        if mc.model:
            model_config["model"] = mc.model
        if mc.base_url:
            model_config["base_url"] = mc.base_url
        if mc.api_key:
            model_config["api_key"] = mc.api_key
        if mc.api_key_env:
            model_config["api_key_env"] = mc.api_key_env
        if mc.extra_params:
            model_config["extra_params"] = dict(mc.extra_params)

    # Determine model string: prefer model_config if it has provider+model
    model_str = msg.model or "anthropic:claude-sonnet-4-6"
    if model_config and model_config.get("provider") and model_config.get("model"):
        model_str = f"{model_config['provider']}:{model_config['model']}"

    return AgentSpec(
        name=msg.name,
        version=msg.version or "1.0.0",
        description=msg.description,
        tags=list(msg.tags),
        model=model_str,
        model_config=model_config,
        prompt=prompt,
        skills=skills,
        tools=tools,
        subagents=subagents,
        mcp_servers=mcp_servers,
        sandbox=sandbox,
        interrupt_on=list(msg.interrupt_on),
    )


# ══════════════════════════════════════════════════════════════════
#  Struct helpers
# ══════════════════════════════════════════════════════════════════


def _dict_to_struct(d: dict[str, Any]) -> struct_pb2.Struct:
    """Convert a Python dict to a google.protobuf.Struct."""
    s = struct_pb2.Struct()
    s.update(d)
    return s


def _struct_to_dict(s: struct_pb2.Struct) -> dict[str, Any]:
    """Convert a google.protobuf.Struct to a Python dict."""
    from google.protobuf.json_format import MessageToDict

    return MessageToDict(s)


def _float_timestamp_to_proto(value: float) -> timestamp_pb2.Timestamp:
    """Convert a float UNIX timestamp to protobuf Timestamp without truncation."""
    seconds = math.floor(value)
    nanos = int(round((value - seconds) * 1_000_000_000))

    if nanos >= 1_000_000_000:
        seconds += 1
        nanos -= 1_000_000_000
    elif nanos < 0:
        seconds -= 1
        nanos += 1_000_000_000

    return timestamp_pb2.Timestamp(seconds=int(seconds), nanos=nanos)


def _python_to_value(value: Any) -> struct_pb2.Value | None:
    """Convert a JSON-like Python value to a protobuf Value."""
    if not _is_json_like(value):
        return None

    result = struct_pb2.Value()
    _populate_value(result, value)
    return result


def _populate_value(target: struct_pb2.Value, value: Any) -> None:
    """Populate a protobuf Value from a JSON-like Python value."""
    if value is None:
        target.null_value = struct_pb2.NullValue.NULL_VALUE
        return
    if isinstance(value, bool):
        target.bool_value = value
        return
    if isinstance(value, (int, float)):
        target.number_value = float(value)
        return
    if isinstance(value, str):
        target.string_value = value
        return
    if isinstance(value, dict):
        target.struct_value.CopyFrom(_dict_to_struct(value))
        return
    if isinstance(value, list):
        values = struct_pb2.ListValue()
        for item in value:
            child = _python_to_value(item)
            if child is None:
                msg = f"Value is not JSON-like: {item!r}"
                raise ValueError(msg)
            values.values.add().CopyFrom(child)
        target.list_value.CopyFrom(values)
        return

    msg = f"Value is not JSON-like: {value!r}"
    raise ValueError(msg)


def _value_to_python(value: struct_pb2.Value) -> Any:
    """Convert a protobuf Value back to a Python value."""
    kind = value.WhichOneof("kind")
    if kind == "null_value":
        return None
    if kind == "bool_value":
        return value.bool_value
    if kind == "number_value":
        return value.number_value
    if kind == "string_value":
        return value.string_value
    if kind == "struct_value":
        return _struct_to_dict(value.struct_value)
    if kind == "list_value":
        return [_value_to_python(item) for item in value.list_value.values]
    return None


def _is_json_like(value: Any) -> bool:
    """Return True when a value can be losslessly encoded as protobuf Value."""
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_like(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_like(item)
            for key, item in value.items()
        )
    return False
