# Runtime Agent Telemetry 接口设计

> 状态：Active
> 最后更新：2026-04-04
> 范围：runtime telemetry 已完成 Phase 0-3 主链；本文同步记录当前实现与下一阶段缺口
> 落地状态：协议、runtime server、control southbound client、northbound telemetry SSE、graph 查询、Telemetry UI 已实现；trace store / replay / 指标聚合 / 稳定 span 模型 尚未实现

## 1. 背景

当前 runtime 已经具备稳定的执行主链：

- `SyncAgentSpec -> Assemble -> Run -> SessionQuery`
- gRPC `AgentExecutor.Run`
- control northbound HTTP / SSE `runs/stream`
- UI 聊天页实时消费 `run_started / text_delta / tool_call_* / run_ended`

但针对 agent 级监控，这条主链存在一个明确问题：

- 它是面向交互消费的运行流，不是面向监控和审计的完整遥测流

前面排查已经确认，当前链路会主动丢弃大量 LangGraph / Deep Agents 原生流信息：

- runtime 只订阅 `messages` 和 `updates`
- 不订阅 `debug` 和 `custom`
- 只处理 root namespace，非空 `ns` 的 subgraph / subagent 事件直接丢弃
- `updates` 只保留 `__interrupt__`
- `messages` 只保留 `text` 和 `tool_call*`
- `reasoning` block 不进入现有 public event 协议

这意味着现有 `Run` 流可以继续服务 UI 和 HITL，但不适合作为完整监控的基础协议。

同时，本轮约束非常明确：

- 不能破坏当前功能
- 现有 `Run` 协议和 northbound HTTP / SSE 行为要保持稳定
- runtime 可以单独实现新的 proto 端点承载 telemetry

## 2. 设计目标

本设计希望解决以下问题：

- 为 data plane 增加一条面向监控的独立 gRPC telemetry 流
- 保留 LangGraph v2 stream 的关键信息，不再沿用当前 lossy 解析链
- 支持 `messages`、`updates`、`debug`、`custom` 四类原生流
- 保留 `ns` 以支持 subgraph / subagent 级观测
- 为后续控制面、审计存储、指标聚合提供稳定 southbound 契约
- 在不改动现有 `AgentExecutor.Run` 的前提下，引入增量能力

### 2.1 当前实现快照（2026-04-04）

当前代码已经落地以下能力：

- `proto/runtime.proto`
  - 已新增 `AgentTelemetry.RunTelemetry`
  - 已新增 `TelemetryEvent`
- `libs/runtime/deepagents-runtime/deepagents_runtime/telemetry.py`
  - 已实现独立 telemetry parser
  - 已保留 `messages`、`updates`、`debug`、`custom`
- `libs/runtime/deepagents-runtime/deepagents_runtime/agent.py`
  - 已实现 `RuntimeAgent.atelemetry()`
  - 已以 `subgraphs=True` 订阅 telemetry 原始流
- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py`
  - 已实现 `invoke_telemetry()`
- `libs/runtime/deepagents-runtime/deepagents_runtime/entry/server.py`
  - 已实现 `AgentTelemetryServicer`
- `libs/control/pkg/runtimeclient/`
  - 已实现 telemetry gRPC client 与 protobuf 映射
- `libs/control/pkg/api/http_handler.go`
  - 已暴露 northbound telemetry SSE：`POST /api/v1/agents/{agent}/telemetry/stream`
  - 已暴露 graph 查询：`GET /api/v1/agents/{agent}/graph`
- `libs/control/ui/src/pages/telemetry/index.tsx`
  - 已实现 `Trace / Graph / Debug` 三视图
  - 已支持筛选、分组、HITL 处理、graph 交互查看

因此，本文后半段的“分阶段落地”和“追踪矩阵”不再表示“尚未开始的总设计”，而是用来区分：

- 已经交付的 telemetry 主链
- 仍然缺失的监控 / 审计 / 回放能力

## 3. 初始非目标（Phase 0 约束）

本设计明确不处理以下事项：

- 不替换现有 `AgentExecutor.Run`
- 不修改现有 HTTP / SSE `runs/stream` contract
- 不在本阶段重做 UI
- 不在本阶段引入完整的 trace store 或 checkpoint replay store
- 不承诺暴露模型供应商未公开的内部状态
- 不将 telemetry 端点包装成“完整审计系统”

这些约束在当前实现里仍然成立，尤其是：

- 当前 telemetry 仍然是“实时遥测流 + 调试 UI”
- 还不是“完整审计和回放系统”
- 还没有持久化 trace store

## 4. 当前现实约束

### 4.1 现有 public 运行流已经是收敛后的兼容协议

当前 public runtime event 枚举只覆盖：

- `run_started`
- `text_delta`
- `text_done`
- `tool_call_start`
- `tool_call_done`
- `tool_result`
- `hitl_request`
- `run_ended`
- `run_canceled`
- `error`

这条协议已经被下面几层消费：

- data plane protobuf `AgentEvent`
- control runtime client
- northbound HTTP / SSE
- control UI chat reducer

因此，这条协议应视为“稳定交互协议”，而不是可自由扩张的内部实验面。

### 4.2 LangGraph 原生流能力比当前 public event 丰富得多

按当前依赖 `langgraph==1.1.2`，原生 v2 `StreamPart` 支持：

- `values`
- `updates`
- `messages`
- `checkpoints`
- `tasks`
- `debug`
- `custom`

其中：

- `debug` 本质上是 `checkpoints` 和 `tasks` 的包装
- `messages` 里会带 `message` + `metadata`
- `metadata` 包含 `langgraph_node`、`langgraph_step`、`langgraph_triggers` 等
- 开启 `subgraphs=True` 时，`ns` 可以表达 subgraph / subagent 路径

也就是说，监控协议最理想的输入不是当前 `RuntimeEvent`，而是更靠近原始 `StreamPart` 的结构化流。

### 4.3 telemetry 最稳的落点是新增 service，而不是扩写旧 event

如果直接在现有 `AgentEvent` 上继续追加字段或 oneof：

- 会放大 control client 和 UI 的兼容面
- 会把“交互流”和“监控流”混成一套协议
- 会提高现有 northbound 回归风险

在已有“不可破坏当前功能”的要求下，新增一个独立 service 更稳。

## 5. 设计原则

### 5.1 保持现有 `Run` 主链不变

本设计的第一原则是：

- `AgentExecutor.Run` 不变
- `RuntimeEvent -> AgentEvent -> HTTP / SSE -> UI` 主链不变

telemetry 端点是新增能力，不是替换能力。

### 5.2 telemetry 直接面向监控，不为 UI 兼容做信息压缩

新协议应优先满足：

- 结构化保真
- 可筛选
- 可聚合
- 可持久化

而不是优先满足聊天 UI 的最小渲染需求。

### 5.3 保留原始上下文，而不是过早翻译成展示语义

telemetry 事件应保留：

- 原始 `stream_mode`
- 原始 `ns`
- 原始 `metadata`
- 可 JSON 化的 `payload`

后续 control plane 和监控系统可以在此基础上做二次投影，但 southbound 协议不应过早丢信息。

## 6. 协议方案

### 6.1 新增独立 service

建议在 `runtime.proto` 中新增：

```proto
service AgentTelemetry {
  rpc RunTelemetry(stream ClientMessage) returns (stream TelemetryEvent);
}
```

设计意图：

- 复用现有 `ClientMessage`，避免重造 run 启动 / HITL / cancel 控制消息
- 复用当前 server run lifecycle
- 新 client 可以只接 telemetry 端点
- 旧 client 完全不受影响

### 6.2 新增 `TelemetryEvent`

建议定义独立 message，而不是复用 `AgentEvent`：

```proto
message TelemetryEvent {
  string run_id = 1;
  string agent_name = 2;
  google.protobuf.Timestamp timestamp = 3;
  repeated string ns = 4;
  string stream_mode = 5;
  string event_type = 6;
  google.protobuf.Struct metadata = 7;
  google.protobuf.Value payload = 8;
  AgentEvent public_event = 9;
}
```

字段语义如下：

- `run_id`
  - 当前运行唯一标识
- `agent_name`
  - 产生该事件的 agent 名称
- `timestamp`
  - telemetry 事件生成时间
- `ns`
  - LangGraph namespace path；空数组表示 root graph
- `stream_mode`
  - 原始 stream mode，例如 `messages`、`updates`、`debug`、`custom`
- `event_type`
  - telemetry 投影后的细粒度类型，例如 `text`、`reasoning`、`tool_call`、`checkpoint`
- `metadata`
  - 原始 `messages` metadata 或 telemetry 级补充元数据
- `payload`
  - 结构化 JSON-like 主负载
- `public_event`
  - 如果当前 telemetry 事件可以无损映射到既有 `AgentEvent`，则可选填充

### 6.3 `stream_mode` 订阅策略

`RunTelemetry` 建议固定订阅：

- `messages`
- `updates`
- `debug`
- `custom`

并保持：

- `subgraphs=True`
- `version="v2"`

原因如下：

- `messages` 提供 LLM token、tool call、reasoning、message metadata
- `updates` 提供 state update 与 interrupt
- `debug` 提供 task / task_result / checkpoint
- `custom` 提供业务自定义埋点

`values` 暂不纳入默认 telemetry 订阅，原因是：

- payload 体积通常更大
- 对在线监控价值低于 `updates + debug`
- 会显著增加传输压力

后续如果有需要，可以追加显式 opt-in 参数。

### 6.4 telemetry event type 投影

建议先定义稳定的一层 event type 投影，而不是把原始对象裸奔给上游。

#### `messages`

建议拆分为：

- `text`
- `reasoning`
- `tool_call_chunk`
- `tool_call`
- `message_metadata`

说明：

- `text` 对应 `content_blocks[type="text"]`
- `reasoning` 对应 `content_blocks[type="reasoning"]`
- `tool_call_chunk` 和 `tool_call` 保持区分，避免监控端丢失 streamed args 粒度
- `message_metadata` 可选，仅在需要时输出；否则可放入同一事件的 `metadata`

#### `updates`

建议拆分为：

- `state_update`
- `interrupt`
- `update_metadata`

说明：

- 普通 node update 不再丢弃
- `__interrupt__` 仍单独标识
- `__metadata__` 单独保留

#### `debug`

建议直接透传三类：

- `task`
- `task_result`
- `checkpoint`

这是 `langgraph` 当前 `debug` payload 的稳定语义边界。

#### `custom`

建议统一标识为：

- `custom`

`payload` 保留 node 通过 `StreamWriter` 写出的原始数据。

### 6.5 lifecycle 事件

telemetry 流仍应补齐 run lifecycle：

- `run_started`
- `run_ended`
- `run_canceled`
- `error`

这些事件并非全部来自 LangGraph 原始 stream，而是来自 runtime 运行壳层。

建议统一用：

- `stream_mode = "lifecycle"`

这样 telemetry client 可以明确区分：

- 图内事件
- 运行壳层事件

## 7. 服务端实现策略

### 7.1 独立 parser，不复用当前 `RuntimeEvent` parser

当前 `deepagents_runtime/streams.py` 是面向 public event 协议的 lossy parser。

新 telemetry 端点应新增独立 parser，例如：

- `deepagents_runtime/telemetry.py`

其职责是：

- 消费原始 `StreamPart`
- 生成 `TelemetryEvent`
- 不依赖现有 `RuntimeEventType`

### 7.2 复用现有 run lifecycle，但分离输出流

`RunTelemetry` 可以复用现有：

- `RunRequest` 校验
- `thread_id` / `run_id` 分配
- HITL coordinator
- cancel 机制
- timeout 机制

但输出队列和 protobuf 映射应独立于 `Run()`。

### 7.3 保持 server 端 ownership 简单

Phase 0 不做：

- 一次执行同时 fan-out 到 `Run()` 和 `RunTelemetry()` 两条不同客户端流
- 跨请求订阅现有 run 的旁路监听

Phase 0 只支持：

- 调用哪个 RPC，就启动哪种 run stream

这样实现最小，风险最低。

## 8. 兼容性要求

### 8.1 必须保持的稳定面

以下内容在本设计中必须保持不变：

- `proto/runtime.proto` 中现有 `AgentExecutor.Run`
- 现有 `AgentEvent` message 结构
- 现有 Python generated stubs 的兼容导入路径
- 现有 Go generated stubs 的包路径与现有调用点
- control plane northbound `runs/stream`
- control UI chat 页事件 reducer

### 8.2 允许变化的面

本设计允许新增：

- 新 service
- 新 message
- 新 Go / Python client 映射层
- 新 southbound 监控接入客户端

## 9. 分阶段落地

### Phase 0：设计与协议落点

已完成。

- 补设计文档
- 明确非破坏性边界
- 明确 proto service / message 草案

### Phase 1：runtime proto + data plane server

已完成。

- 在 `proto/runtime.proto` 中新增 `AgentTelemetry`
- 生成 Python / Go stubs
- 在 runtime server 中新增 `AgentTelemetryServicer`
- 实现 telemetry parser
- 覆盖最小集成测试

### Phase 2：control side southbound client

已完成。

- 为 control 增加 telemetry gRPC client
- 支持消费 `TelemetryEvent`
- 已接入后续 northbound 与 UI 适配层

### Phase 3：监控接入

已完成最小可用链路，但仍未完成“监控产品化”。

- 已提供 northbound telemetry SSE
- 已提供 graph 查询 API
- 已提供实时 Telemetry 页面

### Phase 4：监控产品化与审计能力

下一阶段建议优先处理：

- 引入 telemetry trace store / run store
- 提供 run 级历史查询、回放、导出
- 将 runtime 下发的稳定 `span_id / parent_span_id / node_id` 纳入协议
- 增加 timeline / waterfall 视图
- 增加指标聚合与告警友好的统计投影

### Phase 5：生产化治理

- 请求级过滤参数
  - 例如关闭 `debug` 或仅订阅特定 `stream_mode`
- `values` opt-in
- payload 截断、敏感字段脱敏、采样策略
- 跨 run 对比与深链接

## 10. 验收标准

当前实现已经满足的基础验收项：

- 新增 telemetry 端点不会改变现有 `Run` 行为
- 监控 client 可收到 root graph 和 subgraph 的 `ns`
- `messages` 中的 `reasoning` 不再丢失
- `debug` 中的 `task / task_result / checkpoint` 可稳定接收
- `custom` 事件可原样透传
- 现有 HTTP / SSE 和 UI 回归测试全部保持通过

下一阶段的补充验收项建议为：

- 历史 run 可查询、可回放、可导出
- 运行链路具备稳定 span 关联，而不是仅由 UI 启发式拼装
- UI 可直接呈现 timeline / critical path / node latency
- 至少提供基础聚合指标
  - 总时长
  - 节点耗时
  - token / reasoning token
  - tool 次数
  - HITL 等待时间
  - 失败类型

## 11. 追踪矩阵

| 项目 | 当前状态 | 目标落点 |
|------|----------|----------|
| 设计文档 | 已完成 | `docs/design/runtime-agent-telemetry-design.md` |
| Proto service | 已完成 | `proto/runtime.proto` |
| Python stubs | 已完成 | `libs/runtime/deepagents-runtime/deepagents_runtime/generated/` |
| Go stubs | 已完成 | `libs/control/pkg/proto/` |
| Runtime server | 已完成 | `libs/runtime/deepagents-runtime/deepagents_runtime/entry/server.py` |
| Telemetry parser | 已完成 | `libs/runtime/deepagents-runtime/deepagents_runtime/telemetry.py` |
| Control southbound client | 已完成 | `libs/control/pkg/runtimeclient/` |
| Northbound HTTP / SSE | 已完成 | `libs/control/pkg/api/http_handler.go` |
| Telemetry UI | 已完成 | `libs/control/ui/src/pages/telemetry/index.tsx` |
| Trace store / replay store | 未开始 | 新增 telemetry persistence 层 |
| 稳定 span / correlation 模型 | 未开始 | runtime telemetry 协议与 parser |
| Timeline / waterfall 视图 | 未开始 | `libs/control/ui/src/pages/telemetry/` |
| 指标聚合 / 概览统计 | 未开始 | control aggregation / UI |
| 请求级过滤 / 采样 / 脱敏 | 未开始 | runtime + control northbound |

## 12. 开放问题

- `TelemetryEvent.metadata` 是否应允许 `google.protobuf.Value`，而不是 `Struct`
- 是否需要为 `RunTelemetry` 增加请求级过滤参数，例如关闭 `debug`
- `values` 是否应作为可选订阅引入，用于状态快照回放
- runtime 是否应直接下发稳定 `span_id / parent_span_id / node_id`
- trace store 应位于 runtime、本地 control，还是外部 observability backend
- telemetry payload 的截断、脱敏、采样边界如何定义
- `public_event` 继续保留为兼容投影，还是逐步收缩为可选字段
- 当前 northbound SSE 已经存在；后续是否还需要旁路 southbound 直连模式供监控系统直接消费

## 13. 当前决策

当前建议先按以下决策推进：

1. 现有 `Run` 主链不变。
2. telemetry 通过新增独立 gRPC service 落地。
3. telemetry parser 直接消费原始 `StreamPart`，不复用当前 `RuntimeEvent` parser。
4. 当前 northbound telemetry SSE、graph API 与 Telemetry UI 继续保留，不回退到“仅 southbound 可见”。
5. 下一阶段优先补“历史 run / replay / 稳定 span 模型 / timeline / 指标聚合”，而不是继续堆单次 live 调试细节。
