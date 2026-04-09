# Runtime Agent Telemetry 设计

> 状态：Proposed
> 最后更新：2026-04-07
> 设计目标：围绕 Telemetry UI 的产品能力重构 telemetry 模型，统一 live 与 history，并为后续 exporter / OTel 集成保留稳定入口

## 1. 背景

当前仓库已经具备一条最小可用的 live telemetry 主链：

- runtime 通过 `AgentTelemetry.RunTelemetry` 向 control 暴露结构化 telemetry 事件流
- runtime telemetry parser 已经保留 `messages`、`updates`、`debug`、`custom` 和 lifecycle 事件
- control 已提供 `POST /api/v1/agents/{agent}/telemetry/stream`
- UI 已提供 `Trace / Graph / Debug` 页面，并能够消费 live stream

当前实现的优势是：

- live 调试链路已经可用
- runtime 事件粒度已经明显优于 public `Run` 交互流
- Telemetry UI 已经验证了产品方向

当前实现的核心问题也很明确：

- history 没有稳定权威模型
- Trace 视图主要由前端启发式从 raw events 推导，语义不稳定
- Graph 视图查询的是 agent 当前 graph，而不是 run 启动时的 graph 快照
- runtime event 还缺少稳定的 `event_id / seq / attempt / correlation ids`
- 模型调用、工具调用、HITL 等待虽然能“看出来”，但还不是稳定的产品语义对象
- OTel / LangSmith 可以作为外挂 tracing 能力，但不能直接替代本地 telemetry read model

因此，这一轮 telemetry 设计不再以“先做 span 树”为目标，而是先把 Telemetry UI 真正需要的产品模型定稳。

## 2. 产品范围

本轮 telemetry 的目标只服务以下能力：

- run 列表
- run 详情
- 节点执行树
- 模型调用 / 工具调用 / HITL 等待
- 输入输出 / 错误 / reasoning summary
- graph 与 trace 联动

同时必须满足：

- 支持 live stream
- 支持 history 查询
- live 与 history 使用同一套 canonical telemetry 模型
- OTel 先只保留 trace context 注入入口，不把 OTel span 作为产品查询面

## 3. 设计原则

### 3.1 Event First

telemetry 的 source of truth 是事件账本，而不是 span 树。

原因：

- runtime 当前真正稳定产出的就是事件
- span 树如果先行定义，容易把当前并不稳定的执行边界固化成错误抽象
- 产品 UI 需要的是“可解释的执行过程”，而不是“任意层级的通用 span”

因此：

- `TelemetryEvent` 是 canonical fact
- `TelemetryStep` 是 control 侧派生出来的 read model
- 不在 phase 1 引入通用 `span_id / parent_span_id`

### 3.2 Control Owns History

runtime 负责发出执行事实，不负责 telemetry history query。

control 负责：

- run history
- event history
- step projection
- graph snapshot
- northbound live / history query

inbound transport 可以是：

- 当前 southbound live stream 直连持久化
- 后续 `runtime -> MQ -> control ingest`

不论底层 transport 如何变化，control 都是 northbound telemetry read boundary。

### 3.3 Graph Is Run-Bound

Telemetry Graph 不能继续只查 agent 当前 graph。

必须改成：

- run 启动时固化一份 `TelemetryGraphSnapshot`
- run detail、trace 联动、graph 联动都只查这份 run-bound graph

否则：

- 历史 run 会随着 agent 版本变化而漂移
- graph 与 trace 的节点关联无法稳定复现

### 3.4 Product Trace Uses Step Projection

Trace 视图展示的不是 raw events，也不是 generic span tree，而是 `TelemetryStep`。

`TelemetryStep` 是 control 从事件账本增量投影出来的产品语义对象，直接服务：

- 中栏执行树
- 右栏 step 详情
- graph 节点状态联动
- run summary 聚合

### 3.5 OTel Is Infra Trace, Not Product Trace

OTel 在本设计中的角色只有：

- 接收 / 透传 `traceparent`、`tracestate`
- 跨 gateway、runtime、worker、MQ 的基础设施 tracing
- 后续 exporter 的 trace context 入口

OTel 不承担：

- Telemetry UI 查询
- 产品级节点执行树
- run history source of truth

## 4. Canonical 模型

### 4.1 `TelemetryRun`

`TelemetryRun` 表示一次可查询的 agent 执行。

最少包含：

- `run_id`
- `thread_id`
- `agent_name`
- `runtime_target`
- `status`
- `started_at`
- `finished_at`
- `created_by`
- `request_metadata`
- `graph_snapshot_id`
- `trace_context`

说明：

- `trace_context` 只用于保留 gateway 注入的 `traceparent / tracestate`
- `TelemetryRun` 是 run 列表和 run 详情头部的主对象
- `TelemetryRun` 的统计字段来自 event / step projector 增量更新

建议聚合字段：

- `node_step_count`
- `model_step_count`
- `tool_step_count`
- `hitl_wait_count`
- `error_count`
- `last_event_at`
- `reasoning_summary`

### 4.2 `TelemetryEvent`

`TelemetryEvent` 是 append-only 的 canonical execution fact。

phase 1 目标字段：

- `event_id`
- `run_id`
- `attempt`
- `seq`
- `source`
- `emitted_at`
- `namespace`
- `stream_mode`
- `event_type`
- `node_name`
- `task_id`
- `model_call_id`
- `tool_call_id`
- `interrupt_id`
- `message_id`
- `payload`
- `metadata`
- `public_event`

字段语义：

- `event_id`：全局去重键
- `attempt`：同一 `run_id` 下的重试序号
- `seq`：单个 run attempt 内的严格递增顺序
- `source`：`runtime`、`gateway` 或未来其他 ingest source
- `task_id / model_call_id / tool_call_id / interrupt_id / message_id`：语义相关的稳定关联键

本设计明确要求：

- phase 1 不引入 generic `span_id`
- 优先引入语义相关的 correlation id

原因：

- 产品面真正稳定需要的是“哪个 node task / 哪次 model call / 哪个 tool call / 哪个 interrupt”
- 在这些语义对象稳定之前，通用 span 只会把问题包装得更复杂

### 4.3 `TelemetryStep`

`TelemetryStep` 是 control 侧基于事件账本投影出的产品级执行树节点。

`TelemetryStep.kind` 先收敛为：

- `run`
- `node`
- `model`
- `tool`
- `hitl`

`TelemetryStep` 最少包含：

- `step_id`
- `run_id`
- `parent_step_id`
- `kind`
- `title`
- `status`
- `started_at`
- `finished_at`
- `graph_node_key`
- `task_id`
- `model_call_id`
- `tool_call_id`
- `interrupt_id`
- `input_summary`
- `output_summary`
- `error_summary`
- `reasoning_summary`
- `related_event_ids`

树结构规则：

- 根节点永远是 `run`
- `node` step 挂在 `run` 下，或挂在对应 subgraph 的上层 `node` 下
- `model / tool / hitl` step 挂在最近的活动 `node` step 下
- Graph 视图只与 `node` step 做主关联

这一点非常重要：

- UI 显示的是 `TelemetryStep tree`
- `TelemetryStep` 不是 runtime 直接发出来的 transport object
- 它是 control 的 read model

### 4.4 `TelemetryGraphSnapshot`

`TelemetryGraphSnapshot` 表示 run 启动时冻结的一份 graph。

最少包含：

- `graph_snapshot_id`
- `run_id`
- `agent_name`
- `agent_version`
- `captured_at`
- `graph_payload`
- `graph_hash`

用途：

- run detail graph 视图
- graph 与 trace 的节点联动
- 历史 run 重放和导出

## 5. Runtime 事件模型

### 5.1 保留现有 stream 模式

runtime 继续保留以下 source stream：

- `messages`
- `updates`
- `debug`
- `custom`
- `lifecycle`

这是当前 telemetry parser 已经具备的基础能力，不需要回退。

### 5.2 phase 1 需要补齐的稳定字段

为了支持 live + history，需要在 runtime telemetry 事件中补齐：

- `event_id`
- `attempt`
- `seq`
- `node_name`
- `task_id`
- `message_id`
- `model_call_id`

当前已经基本可用或已存在语义基础的字段：

- `tool_call_id`
- `interrupt_id`
- `namespace`
- `stream_mode`
- `event_type`

### 5.3 语义事件分组

为了支撑产品 UI，control 至少要能从 runtime 事件中稳定识别以下几类过程。

#### Run lifecycle

- `run_started`
- `run_ended`
- `run_canceled`
- `error`

#### Node execution

优先复用 `debug.task` / `debug.task_result`，并稳定暴露：

- `task_id`
- `node_name`
- `step`
- `triggers`

这组事件用于投影 `node` step。

#### Model execution

产品上需要“模型调用”这一层，但 phase 1 不强制把它抽象成 generic span。

本设计要求 runtime 至少稳定提供：

- `message_id`
- `model_call_id`
- `reasoning`
- `text`
- `text_done`

control projector 以 `model_call_id` 为主键投影 `model` step。

如果某些 runtime 场景下暂时拿不到天然 `model_call_id`，则需要 runtime 合成一个 run-local 稳定键，而不是把这一层继续留给前端猜。

#### Tool execution

工具调用继续使用已有语义：

- `tool_call_start`
- `tool_call_done`
- `tool_result`

并以 `tool_call_id` 为稳定键投影 `tool` step。

#### HITL wait

runtime 发出：

- `interrupt`

control gateway 追加：

- `hitl_decision_sent`
- `hitl_decision_acked`
- `cancel_requested`

`hitl` step 的关闭不能只依赖 runtime 原始 stream，需要把 gateway 侧控制事实也纳入同一条 event ledger。

#### State / custom detail

以下事件仍保留为 detail surface：

- `state_update`
- `update_metadata`
- `custom`

它们用于：

- Debug 视图
- step detail 的补充信息
- 后续导出 / replay

## 6. Step 投影规则

control projector 对 event ledger 做增量投影。

### 6.1 `run` step

打开条件：

- `run_started`

关闭条件：

- `run_ended`
- `run_canceled`
- `error`

### 6.2 `node` step

打开条件：

- `debug.task`

关闭条件：

- `debug.task_result`
- 运行级 terminal 事件兜底关闭

关联键：

- `task_id`

### 6.3 `model` step

打开条件：

- 某个活动 `node` 下首次出现指定 `model_call_id` 的 message 事件

关闭条件：

- 该 `model_call_id` 的完成事件
- 同一 node 内新的 `model_call_id` 开始且旧 step 仍未关闭时的保守收口
- 所属 `node` 关闭时兜底关闭

`model` step 聚合内容：

- `reasoning_summary`
- `output_summary`
- `message count`
- `text chunks`

### 6.4 `tool` step

打开条件：

- `tool_call_start`

关闭条件：

- `tool_result`
- 运行级 terminal 事件兜底关闭

### 6.5 `hitl` step

打开条件：

- `interrupt`

关闭条件：

- `hitl_decision_acked`
- `cancel_requested`
- 运行级 terminal 事件兜底关闭

这部分必须允许 gateway 事件参与投影，否则 live 和 history 会出现“看到等待，但看不到谁批准了”的断层。

## 7. Storage 设计

control 侧建议至少维护以下对象：

- `telemetry_runs`
- `telemetry_events`
- `telemetry_steps`
- `telemetry_graph_snapshots`

建议语义：

- `telemetry_events`：append-only，不做覆盖更新
- `telemetry_steps`：projected read model，允许 upsert
- `telemetry_runs`：summary read model，允许增量更新
- `telemetry_graph_snapshots`：run 启动时固化

这四者的关系是：

- `events` 是真相
- `runs / steps / graph_snapshots` 都是可重建的 read model

## 8. Live 与 History 一体化

### 8.1 统一 contract

live 与 history 必须共享同一套事件模型。

换句话说：

- live SSE 看到的 `TelemetryEvent`
- history API 查到的 `TelemetryEvent`

在字段和语义上必须一致。

### 8.2 Resumable stream

live stream 应支持断线续传。

建议：

- SSE `id` 使用 `event_id`
- control 支持 `Last-Event-ID`
- 若 client 已经拉过 history，可从最后一个 `event_id` 开始接 live tail

这部分可以直接借鉴 LangGraph API 的 resumable stream 思路，但不复用其内部 run store 语义。

### 8.3 UI 使用方式

Telemetry UI 的推荐加载顺序：

1. 进入 run 详情页先拉：
   - `run`
   - `steps`
   - `graph`
   - 首屏 `events`
2. 如果 run 仍在执行，再接 `stream`
3. live 增量到达后：
   - Debug 视图直接追加 raw event
   - Trace / Graph 视图优先消费 control 投影后的 step / summary 更新

兼容策略：

- phase 1 仍允许 UI 用 raw events 做本地补丁
- 目标状态是 UI 不再负责“发明 step”，而是只渲染 control 的 `TelemetryStep`

## 9. Northbound / Southbound 接口

### 9.1 Southbound

当前保留：

- `AgentTelemetry.RunTelemetry`

它的定位是：

- runtime -> control 的 live execution facts stream
- 当前 live telemetry 主链的 transport

它不承担：

- history query
- step query
- graph snapshot query

### 9.2 Northbound

目标 northbound 接口：

- `POST /api/v1/agents/{agent}/telemetry/stream`
- `GET /api/v1/telemetry/runs`
- `GET /api/v1/telemetry/runs/{run_id}`
- `GET /api/v1/telemetry/runs/{run_id}/events`
- `GET /api/v1/telemetry/runs/{run_id}/steps`
- `GET /api/v1/telemetry/runs/{run_id}/graph`
- `GET /api/v1/telemetry/runs/{run_id}/stream`

说明：

- 当前 `POST /api/v1/agents/{agent}/telemetry/stream` 继续保留，作为 live run 入口
- history 面统一走 `/api/v1/telemetry/runs/*`
- `graph` 必须是 run-bound graph，而不是 agent current graph

## 10. OTel 与外部 tracing

### 10.1 当前约束

本轮不把 OTel span 作为产品查询面。

### 10.2 需要保留的入口

保留：

- gateway 接收 `traceparent`
- control 在 `TelemetryRun.trace_context` 中记录该值
- control 向 runtime 透传 `traceparent / tracestate`

这样后续可以无缝接上：

- OTel exporter
- MQ / worker / webhook distributed tracing
- LangSmith 或其他外部 tracing exporter

### 10.3 明确不做的事情

本轮不做：

- 以 OTel span 树替代 `TelemetryStep`
- 以 LangSmith run tree 替代本地 telemetry store
- 让 Telemetry UI 直接查询外部 tracing backend

外部 tracing 只能是 optional exporter，不能成为 source of truth。

## 11. 分阶段落地

### Phase 0：当前基线

当前已经具备：

- runtime live telemetry event stream
- northbound live telemetry SSE
- Telemetry UI 原型

### Phase 1：稳定 event ledger

目标：

- 给 runtime telemetry event 补齐 `event_id / attempt / seq`
- 补齐 `node_name / task_id / message_id / model_call_id`
- control 持久化 `TelemetryRun` 和 `TelemetryEvent`
- live SSE 支持 resumable stream

### Phase 2：server-side step projection

目标：

- control 增量投影 `TelemetryStep`
- 增量维护 `TelemetryRun` summary
- gateway 控制事件纳入同一条 event ledger
- UI Trace 视图从“前端推导 span”切到“服务端 steps”

### Phase 3：run-bound graph 与联动

目标：

- run 启动时固化 `TelemetryGraphSnapshot`
- `GET /api/v1/telemetry/runs/{run_id}/graph`
- Trace / Graph 双向联动改为 run-bound

### Phase 4：外部 tracing / exporter

目标：

- 保持本地 telemetry model 不变
- 在此基础上增加 optional exporter：
  - OTel exporter
  - LangSmith-like exporter

## 12. 当前决策

本轮设计明确采用以下决策：

1. telemetry 先做 `event ledger first`
2. 产品 Trace 使用 `TelemetryStep`，而不是通用 span
3. graph 查询必须切到 run-bound snapshot
4. live 与 history 共享同一套 canonical event model
5. gateway 侧控制事实要进入同一条 telemetry event ledger
6. OTel 先只保留 trace context 注入入口
7. LangSmith 或其他 tracing backend 未来只能作为 optional exporter
