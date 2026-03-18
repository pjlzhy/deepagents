"""Converters between RuntimeEvent (Python) and protobuf messages.

This module provides the serialization boundary between the internal
RuntimeEvent dataclass and the gRPC AgentEvent / ClientMessage protobufs.

The gRPC layer is purely a transport boundary -- RuntimeEvent and AgentEvent
carry exactly the same information.
"""

from __future__ import annotations

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
    SkillSpec,
    SubagentMetadata,
)


# ══════════════════════════════════════════════════════════════════
#  RuntimeEvent → AgentEvent (server side: Python → protobuf)
# ══════════════════════════════════════════════════════════════════


def runtime_event_to_agent_event(event: RuntimeEvent) -> pb2.AgentEvent:
    """Convert a RuntimeEvent to a protobuf AgentEvent.

    Returns an ``AgentEvent`` message ready to be sent over gRPC.
    Internal-only events (HITL_RESPONSE, STATS) are mapped to a
    no-payload AgentEvent (caller should filter these out).
    """
    ts = timestamp_pb2.Timestamp()
    ts.FromSeconds(int(event.timestamp))

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
        args_struct = _dict_to_struct(event.data.get("args", {}))
        kwargs["tool_call_start"] = pb2.ToolCallStart(
            tool_name=event.data.get("tool_name", ""),
            tool_call_id=event.data.get("tool_call_id", ""),
            args=args_struct,
        )
    elif event.type == RuntimeEventType.TOOL_CALL_DONE:
        kwargs["tool_call_done"] = pb2.ToolCallDone(
            tool_name=event.data.get("tool_name", ""),
            tool_call_id=event.data.get("tool_call_id", ""),
        )
    elif event.type == RuntimeEventType.TOOL_RESULT:
        kwargs["tool_result"] = pb2.ToolResult(
            tool_call_id=event.data.get("tool_call_id", ""),
            content=event.data.get("content", ""),
            is_error=event.data.get("is_error", False),
        )
    elif event.type == RuntimeEventType.HITL_REQUEST:
        action_requests = []
        for ar in event.data.get("action_requests", []):
            action_requests.append(pb2.ActionRequest(
                action=ar.get("action", ""),
                tool_call_id=ar.get("tool_call_id", ""),
                args=_dict_to_struct(ar.get("args", {})),
            ))
        kwargs["hitl_request"] = pb2.HITLRequest(
            interrupt_id=event.data.get("interrupt_id", ""),
            action_requests=action_requests,
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
    elif event.type == RuntimeEventType.ERROR:
        kwargs["error"] = pb2.ErrorOccurred(
            message=event.data.get("message", ""),
            error_type=event.data.get("error_type", ""),
        )
    # HITL_RESPONSE, STATS -- internal events, no proto payload

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
        return {
            "tool_name": payload.tool_name,
            "tool_call_id": payload.tool_call_id,
            "args": _struct_to_dict(payload.args) if payload.HasField("args") else {},
        }
    elif event_type == RuntimeEventType.TOOL_CALL_DONE:
        return {
            "tool_name": payload.tool_name,
            "tool_call_id": payload.tool_call_id,
        }
    elif event_type == RuntimeEventType.TOOL_RESULT:
        return {
            "tool_call_id": payload.tool_call_id,
            "content": payload.content,
            "is_error": payload.is_error,
        }
    elif event_type == RuntimeEventType.HITL_REQUEST:
        action_requests = []
        for ar in payload.action_requests:
            action_requests.append({
                "action": ar.action,
                "tool_call_id": ar.tool_call_id,
                "args": _struct_to_dict(ar.args) if ar.HasField("args") else {},
            })
        return {
            "interrupt_id": payload.interrupt_id,
            "action_requests": action_requests,
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


def sync_agent_spec_request_to_agent_spec(msg: pb2.SyncAgentSpecRequest) -> AgentSpec:
    """Convert a SyncAgentSpecRequest protobuf to an AgentSpec."""
    prompt: dict[str, Any] = {}
    if msg.HasField("prompt"):
        prompt = {
            "system": msg.prompt.system,
            "memory": list(msg.prompt.memory),
        }

    tools: dict[str, Any] = {}
    if msg.HasField("tools"):
        tools = {
            "builtins": list(msg.tools.builtins),
            "mcp": list(msg.tools.mcp),
        }

    sandbox: dict[str, Any] = {}
    if msg.HasField("sandbox"):
        sandbox = {
            "image": msg.sandbox.image,
            "resources": dict(msg.sandbox.resources),
            "init": list(msg.sandbox.init),
        }

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
        if sa.source:
            sa_meta["source"] = sa.source
        if sa.path:
            sa_meta["path"] = sa.path
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
        skills.append({"name": skill.name, "content": skill.content})

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
