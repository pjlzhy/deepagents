# Runtime Data 层 Roadmap

> 状态：核心闭环完成，剩余事项延期
> 最后更新：2026-03-25

## 概述

`libs/runtime` 中的 Runtime Data 层，本质上是 Agent OS 的 `Agent Engine`。

它的职责是接收来自 control plane 的富 `AgentSpec`，将其装配为可运行的 graph，管理 agent-scoped 运行时资源以及 session / checkpoint / execution context 等运行状态，并通过 gRPC 暴露执行入口。

control plane 负责 registry CRUD、资源打包和资源分发。data plane 不承担系统级资源仓库的职责。

## 当前状态

当前实现已经具备 runtime 的核心闭环：

- 已实现 `Run`、`SyncAgentSpec`、`Assemble`、`Health` 等 gRPC 服务
- 已实现 protobuf 请求到内部 runtime spec 的转换
- 已实现 `AgentSpec -> AgentTemplate -> graph` 的装配主链路
- 已实现 agent 本地运行目录，包括 skills、memory、workspace 等
- 已接入基于 SQLite 的 checkpoint 持久化
- 已具备基础的流式执行、HITL 和 cancel 能力
- 已让 gRPC `Run` 走统一的 manager 执行路径
- 已完成 agent-scoped MCP runtime lifecycle 管理
- 已完成 agent-owned sandbox lifecycle 管理
- 已让 `SandboxSpec` 真正驱动 backend 选择
- 已完成 `SessionQuery` gRPC 服务（ListSessions / GetSession / GetSessionMessages / GetLatestSession / DeleteSession）
- 已完成 health / readiness 准确状态输出：`installed / assembled / running / ready`
- 已完成 `SessionSummary.agent_status` 的 live runtime 状态覆盖
- 已统一 CLI `run` 和 gRPC `Run` 的执行路径，统一走 `AgentManager` lifecycle（setup -> define -> assemble -> invoke -> shutdown）
- 已移除兼容残留：`sandbox_pool`、`stop_agent()`、空的 `mcp_middleware.py`、`SandboxPool` 模块
- proto 中半成品字段已通过 `reserved` 标记移除：`prompt.memory`、`tools.builtins`、`tools.mcp`、`subagents.source`、`subagents.path`
- 已补齐 runtime 关键单元测试：spec validation、skill files、manager、sandbox lifecycle、sessions、session query、health、event protocol、proto codegen
- 已补齐 process-local 集成测试：manager/runtime 主链 `define -> assemble -> run`、shutdown cleanup、checkpoint resume / session continuity
- 已补齐进程内 gRPC 集成测试：`ResourceSync + AgentExecutor.Run` 主路径
- 已固定 protobuf 生成脚本，避免生成到错误的嵌套目录

这说明 data 层核心闭环已经完成，可作为稳定的本地 Agent Engine 使用；剩余事项已转入 deferred backlog，不再阻塞当前里程碑收口。

## 延期事项（Deferred Backlog）

当前剩余工作重点已经从“补主链路功能”收缩到“深水区回归、部署形态验证和 northbound 对齐”。

### 1. 深化集成与部署验证

当前已经补齐 process-local manager/runtime 主链、checkpoint resume / session continuity，以及进程内 gRPC `ResourceSync + AgentExecutor.Run` 的主路径验证。

延期项主要包括：

- 真实 client -> server gRPC 路径下的 HITL / cancel / timeout 深度回归
- 跨进程或真实部署形态下的 cleanup / shutdown 验证
- 默认 file-backed `get_checkpointer()` 路径验证

### 2. 边界条件与平台兼容性

当前本地 runtime 主链已经收口，但仍有少量边界条件和平台差异尚未专门验证。

延期项主要包括：

- `RemoveResource` 在 Windows 下删除包含 `AGENTS.md` 目录的兼容性处理
- cancel / timeout / 异常退出时 checkpoint 与 cleanup 的尾部一致性回归
- `k8s` sandbox backend 仍仅预留契约，尚未实现与验证

### 3. 文档与 northbound 对齐

data layer 内部主链路已经收口，但文档和上层接入仍需持续同步：

- roadmap / 设计文档状态持续回填
- control plane / client 对新 health 字段和 `SessionSummary.agent_status` 的消费
- proto 注释与上层调用约定保持一致

## 时间表

以下时间表保留原计划窗口，用于说明推进顺序；当前真实完成度以上文状态为准。

### Phase 1：设计文档收敛（已完成）

**原计划窗口：2026-03-18 至 2026-03-18**

目标：

- 冻结以富 `AgentSpec` 为中心的 runtime 边界
- 统一 control plane / data plane 职责口径
- 更新设计文档，使其与当前实现边界一致
- 更新 proto 注释，去掉旧的资源逐项同步语义
- 明确 `SyncSkill` 和 `SyncMcp` 是兼容接口还是后续弃用接口

### Phase 2：装配能力补齐（已完成）

**原计划窗口：2026-03-19 至 2026-03-19**

目标：

- 移除 `prompt.memory`
- 移除 `tools.builtins`
- 移除 `tools.mcp`
- 移除 `subagents.source` / `subagents.path`
- 将精简后的 `AgentSpec` 契约收敛到 proto / spec / converter / registry / tests

### Phase 3：执行路径统一（已完成）

**原计划窗口：2026-03-20 至 2026-03-24**

已完成：

- gRPC `Run` 走统一的 manager 执行路径
- CLI `run` 命令统一使用 `async with AgentManager()` lifecycle
- run setup / teardown 收敛到 `AgentManager.invoke()` 单一入口
- cancel、timeout、error 场景下的清理逻辑统一由 manager 拥有
- 移除 `RuntimeAgent.ainvoke()` 空方法

### Phase 4：资源生命周期补齐（已完成）

**原计划窗口：2026-03-25 至 2026-03-27**

已完成：

- MCP runtime assemble / release lifecycle
- agent-owned sandbox lifecycle
- `SandboxSpec -> backend` 选择
- 移除兼容残留：`sandbox_pool` 参数和 `SandboxPool` 模块
- 移除兼容残留：`stop_agent()` 方法
- 删除空的 `middleware/mcp_middleware.py` 占位模块
- 文档口径与代码实现统一

### Phase 5：元数据与健康状态补齐（已完成）

**原计划窗口：2026-03-30 至 2026-04-01**

已完成：

- `SessionQuery` service 全量落地
- thread / session metadata 完善：`agent_name`、`updated_at`、`latest_checkpoint_id`、`message_count`、`checkpoint_count`
- `message_count` 与 latest checkpoint `channel_values.messages` 语义对齐
- `GetSessionMessages` 的 snapshot pinning / page token 行为收口
- `HealthResponse` 反映真实 `installed / assembled / running / ready` 状态
- `SessionSummary.agent_status` 提供 live runtime 状态覆盖

### Phase 6：稳定性与验证（核心闭环已完成）

**原计划窗口：2026-04-02 至 2026-04-09**

已完成：

- converters / spec validation / skill files 单元测试
- manager run lifecycle 单元测试
- runtime agent sandbox lifecycle / HITL 单元测试
- sessions / session query / health / event protocol 单元测试
- protobuf codegen 脚本与验证单元测试
- process-local 集成测试：manager/runtime 主链、shutdown cleanup、checkpoint resume / session continuity
- 进程内 gRPC 集成测试：`ResourceSync + AgentExecutor.Run`

延期：

- 真实 client -> server gRPC 路径下的 HITL / cancel / timeout 深度回归
- 默认 file-backed checkpoint 路径验证
- Windows 删除兼容性处理
- K8s backend 实现与验证

## 风险

主要风险已经从“主链路缺失”转移到“边界条件与部署差异”。

- 如果文档继续描述旧的资源同步模型，后续实现仍会被误判为“偏离设计”
- 如果缺少 gRPC HITL / cancel / timeout 的深度回归，跨进程场景下的问题会更晚暴露
- 如果默认 file-backed checkpoint 路径和 Windows 删除语义不尽早验证，平台相关问题会在上层联调时集中出现
- 如果 K8s backend 长期仅停留在契约层，后续接入时仍会有一次独立的实现与验证成本

## 当前结果

经过本轮 roadmap 收口，Runtime Data 层已经成为可用的 Agent Engine，具备以下特征：

- 契约稳定
- 装配完整
- 生命周期一致
- 状态可观测
- 主路径行为可回归验证

在当前范围内，control plane 已可将 data plane 视为稳定的本地执行底座；更深的部署级验证和 K8s 能力转入后续 backlog。
