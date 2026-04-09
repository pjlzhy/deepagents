# Control Layer Architecture Design

> 状态：当前范围完成
> 最后更新：2026-04-07
> 目标实现语言：Go
> 当前实现范围：single `default_target`

## 1. 背景

当前 `libs/runtime` 已经收敛为稳定的 data layer / agent engine：

- data layer 负责消费富 `AgentSpec`
- data layer 负责 `Assemble -> Run` 执行主链路
- data layer 持有 compiled runtime、MCP runtime、sandbox runtime、checkpoint/session state
- control plane 与 data plane 的唯一边界已经收敛为 `proto/runtime.proto`

当前 `libs/control` 已经完成 single `default_target` 范围内的主链路落地。

本设计文档的目标，已经从“提出一版可落地的 Go control layer 架构”收敛为“记录当前已落地的 control layer 边界与模块职责”，使其与当前 data layer 的边界保持一致，并为后续 CLI、gateway、scheduler、K8s 部署提供稳定控制面。

## 2. 设计目标

control layer 的目标是：

- 作为 model configs、skills、MCP configs、AgentSpecs 的 authoritative registry
- 负责 authored resources 的引用解析和 runtime-ready packaging
- 负责 `install / compile / execute / cancel / uninstall` 的 southbound 编排
- 作为所有 agent 调用的统一 gateway
- 负责 northbound HTTP / SSE API
- 负责 telemetry / audit 的统一 ingress boundary 与 northbound read boundary
- 对上暴露稳定的资源管理、执行、查询接口

## 3. 非目标

control layer 不负责：

- graph 构建与 agent assembly 细节
- MCP live session 生命周期
- sandbox runtime 生命周期
- checkpoint 文件内容与 session 存储 ownership
- 重新解释 data plane 内部 event protocol
- 在第一阶段实现完整的 K8s operator / controller 体系

这些能力仍属于 data layer。

## 4. 边界定义

### 4.1 Control Plane 与 Data Plane 分工

control layer 负责：

- registry CRUD
- rich `AgentSpec` packaging
- install / compile / uninstall orchestration
- gateway admission / routing
- run / telemetry northbound API
- telemetry ingest / read boundary
- northbound API

data layer 负责：

- rich `AgentSpec` -> compiled runtime
- `Run` 执行
- agent-scoped MCP runtime / sandbox runtime
- run-scoped execution state
- checkpoint / session state
- live telemetry fact 生成与发送

### 4.2 协议边界

control layer 当前 southbound gRPC 边界包括：

- `ResourceSync`
- `AgentExecutor`
- `SessionQuery`
- `AgentTelemetry`

其中：

- `SyncAgentSpec` 是主同步单元
- `SyncSkill` / `SyncMcp` 仅保留为兼容接口，不作为新主路径
- `Assemble` 承担 compile 语义
- `RemoveResource` 承担 uninstall/delete 语义
- `SessionQuery` 提供 runtime-local session 查询和删除能力
- `AgentTelemetry.RunTelemetry` 仅作为 live debug / live tap 路径存在
  - 不承担历史查询
  - 不承担 telemetry store ownership

## 5. 总体架构

当前实现已经收敛为：

```text
HTTP / SSE northbound
    -> API / Gateway
        -> Orchestrator
            -> Registry
            -> Resolver
            -> Packager
            -> Runtime Clients (gRPC)
                -> ResourceSync
                -> AgentExecutor
                -> SessionQuery
                -> AgentTelemetry (live tap)
                    -> Data Plane
```

同时，下一阶段 telemetry 的目标链路应收敛为：

```text
runtime
    -> MQ
        -> control gateway ingest
            -> TelemetryEvent ledger
            -> TelemetryRun / TelemetryStep / TelemetryGraphSnapshot
                -> northbound telemetry query / SSE
```

一句话定义：

```text
deepagents-control = Registry + Resolver + Packager + Gateway + Orchestrator + Telemetry Read Boundary
```

## 6. Go 模块拆分

当前实现已经落在 `libs/control/`，而不是早期草案里的 `libs/control/deepagents-control/`。

```text
libs/control/
├── main.go
├── app.go
├── pkg/
│   ├── api/
│   ├── config/
│   ├── domain/
│   ├── orchestrator/
│   ├── packager/
│   ├── proto/
│   ├── registry/
│   ├── resolver/
│   ├── router/
│   ├── runtimeclient/
│   ├── store/
│   └── streamproxy/
└── tools/
```

说明：

- `pkg/router/` 当前保留为后续 multi-target 扩展预留
- 当前 runnable 主路径已经不依赖 `pkg/router/`
- 当前 telemetry 相关逻辑仍分散在 `pkg/api`、`pkg/runtimeclient`、`pkg/streamproxy`
- 后续若引入 MQ ingest、event persistence、step projection，再考虑独立 `pkg/telemetry`

各模块职责如下。

### 6.1 `pkg/domain`

纯领域模型，不依赖 gRPC、HTTP、数据库驱动。

当前主资源与预留模型包括：

- `ModelConfig`
- `Skill`
- `McpConfig`
- `AuthoredAgentSpec`
- `Deployment`
- `RuntimeTarget`
- `Operation`

### 6.2 `pkg/registry`

authoritative resource registry。

负责：

- model configs CRUD
- skills CRUD
- MCP configs CRUD
- authored agent specs CRUD
- 通用分页查询
- 引用存在性校验
- authored 结构化校验
- 删除前引用检查

### 6.3 `pkg/resolver`

把 authored resources 聚合成 packager 可消费的输入。

负责：

- 读取 `AuthoredAgentSpec`
- 解析 `model_ref`
- 解析 skill refs
- 解析 MCP refs

当前不再解析：

- workspace
- deployment
- runtime target

### 6.4 `pkg/packager`

将 control layer 中的 authored state 打包成 runtime-ready `AgentSpec`。

负责：

- 将解析后的 `ModelConfig` 展开为 runtime `ModelSpec`
- prompt 合成
- skill 目录快照打包
- MCP configs 嵌入
- subagent metadata 展开
- sandbox spec 合法性检查
- 输出 `SyncAgentSpecRequest`

### 6.5 `pkg/runtimeclient`

对 southbound gRPC 的薄封装。

建议拆成四个 client：

- `ResourceSyncClient`
- `AgentExecutorClient`
- `SessionQueryClient`
- `AgentTelemetryClient`

要求：

- 不在 client 层重写业务状态机
- 尽量保持 proto 语义原样透传
- 统一做连接管理、超时、重试和错误包装

### 6.6 `pkg/orchestrator`

control layer 的核心 service 层。

负责：

- `EnsureRunnable`
- `RunAgent`
- `Health`
- session 查询 / 删除
- telemetry run / event / step / graph snapshot 查询
- telemetry step projection 与 run summary 聚合
- 对 northbound 资源 CRUD / 分页查询的 service 封装

### 6.7 `pkg/api`

northbound API。

当前实现为：

- 管理类接口使用 HTTP
- 流式执行使用 SSE
- live telemetry 也通过 SSE 暴露给 northbound UI

### 6.8 `pkg/streamproxy`

运行流代理层。

负责：

- northbound run request -> southbound `AgentExecutor.Run`
- `AgentEvent` 原样转发
- `HITLRequest` / `HITLDecision` 关联
- `CancelRequest` 转发
- gateway 侧 run 审计事件发射
- 当前 live telemetry stream 的 northbound 适配

不负责：

- telemetry event ledger 持久化 ownership
- 历史 telemetry 查询

## 7. 核心领域模型

### 7.1 资源模型

当前 northbound authoritative resources 为：

| 资源 | 说明 | authoritative owner |
|------|------|---------------------|
| `ModelConfig` | 可复用 model 配置模板 | control layer |
| `Skill` | 技能目录快照与元数据 | control layer |
| `McpConfig` | MCP server 配置模板 | control layer |
| `AuthoredAgentSpec` | 用户编写的 agent 定义；通过 `model_ref` / `skill_refs` / `mcp_refs` 引用其他资源 | control layer |

以下模型当前仍保留在 `domain` / `registry`，但不属于当前 northbound contract：

| 资源 | 当前状态 | 说明 |
|------|----------|------|
| `RuntimeTarget` | 预留 / bootstrap 使用 | 当前只记录默认 target 元数据 |
| `Deployment` | 预留 | 为未来 multi-target agent -> target 绑定保留 |
| `Operation` | 预留 | 为 operation journal / gateway audit 保留 |

### 7.2 状态模型

建议把状态拆成两层。

第一层是 authored state：

- `draft`
- `published`
- `deleted`

第二层是 deployment / runtime observed state：

- `absent`
- `installed`
- `compiled`
- `running`
- `degraded`

关键原则：

- control layer 可以维护 desired state
- observed runtime state 以 data plane 回执和查询结果为准
- control layer 不自己发明第二套 authoritative compiled state

## 8. 存储设计

当前实现使用 SQLite。

已落地的表结构为：

| 表 | 用途 |
|----|------|
| `model_configs` | model 配置模板 |
| `skills` | skill 元数据与 `files_json` |
| `mcp_configs` | MCP 配置 |
| `agent_specs` | authored agent specs |
| `runtime_targets` | 默认 target bootstrap 元数据与未来扩展预留 |
| `deployments` | future multi-target 绑定预留 |
| `operations` | operation journal / gateway audit 预留 |

说明：

- skill files 当前不拆独立表
- 所有主表当前都以自增 `id` 作为主键，并对 `name` 建唯一索引
- `agent_specs.model_ref` 额外建立索引，支持引用校验与查询
- `workspaces` / `workspace_resources` 已移除
- `runtime_targets` / `deployments` 当前不属于 northbound 主资源

## 9. Packaging 设计

control layer 的核心能力不是执行，而是 packaging。

### 9.1 输入

packager 的输入包括：

- `AuthoredAgentSpec`
- resolver 展开的 `ModelConfig`
- skill 引用及其快照
- MCP config 引用及其展开结果

### 9.2 输出

packager 的输出是 runtime-ready `SyncAgentSpecRequest`。

输出要求：

- `skills` 使用嵌入式目录快照
- `mcp_servers` 使用完整 runtime 配置
- `model_ref` 在 control layer 被解析，并收敛为 runtime 可执行 `model`
- `subagents` 使用结构化定义
- `sandbox` 明确传给 data plane

### 9.3 原则

- data plane 把同步后的 `AgentSpec` 当 assembly input，而不是 control layer 的远程 registry 镜像
- control layer 负责把 authoring-time indirection 解析掉
- 尽量减少增量同步协议，优先走整包 `SyncAgentSpec`

## 10. Southbound 编排

### 10.1 生命周期映射

与当前 data layer 保持一致：

| 控制面动作 | southbound RPC | 语义 |
|------------|----------------|------|
| install | `SyncAgentSpec` | 安装 runtime-ready spec |
| compile | `Assemble` | 构建 runnable runtime |
| execute | `AgentExecutor.Run` | 运行 agent |
| cancel | `CancelRequest` | 取消当前 run |
| uninstall | `RemoveResource` | 删除 agent spec 与 runtime |

### 10.2 `EnsureRunnable`

control layer 内部建议提供 `EnsureRunnable(agent_name)`：

1. 读取 authored spec
2. 解析 `model_ref`、skill refs 与 MCP refs
3. packaging 为 runtime-ready `AgentSpec`
4. 调用 `SyncAgentSpec`
5. 调用 `Assemble`

这个 helper 只是一层编排便利接口，不改变 southbound 协议语义。

### 10.3 `RunAgent`

`RunAgent` 的当前流程：

1. 标准化 `agent_name`
2. 调用 `EnsureRunnable`
3. 建立 `AgentExecutor.Run` 双向流
4. 发送 `RunRequest`
5. 原样转发 `AgentEvent`
6. 收到 `HITLRequest` 时等待 northbound decision
7. 转发 `HITLDecision`
8. 用户取消时转发 `CancelRequest`

关键原则：

- control layer 不重新解释 `AgentEvent` 细节语义
- control layer 不重做 parser state machine
- event 扩展应优先通过 proto 扩展，而不是在 control layer 写死逻辑

### 10.4 `RunTelemetry` 与 telemetry ingress

当前 northbound telemetry live 调试链路可以通过 southbound `AgentTelemetry.RunTelemetry` 建立。

它的定位应收敛为：

- live debug / live tap
- Telemetry UI 的开发期或在线调试观察路径
- 对 runtime 原始 stream 的旁路观测

它不代表最终 telemetry 持久化 ownership 位于 runtime。

control layer 下的长期 telemetry 边界应定义为：

- 所有 northbound agent 调用都经过 control gateway
- runtime 在执行时产生 telemetry event
- telemetry durable path 走 `runtime -> MQ -> control gateway`
- control gateway 负责 `TelemetryEvent` 账本、`TelemetryRun`/`TelemetryStep`/`TelemetryGraphSnapshot` 投影，以及历史查询

因此，`RunTelemetry` 只能视为 southbound live stream，而不能视为 telemetry query / audit 的权威路径。

## 11. Session / Health / Telemetry 设计

### 11.1 Session 与 Health

当前把 session 与 health 视为 runtime query，而不是 control-owned state。

control layer 提供 northbound 查询接口，但 southbound 直接代理：

- `Health`
- `ListSessions(agent_name?, page_size, page_token)`
- `GetLatestSession(agent_name?)`
- `GetSession(agent_name, thread_id)`
- `GetSessionMessages(agent_name, thread_id, checkpoint_id?, page_size, page_token, mode, include_raw?)`
- `DeleteSession(agent_name, thread_id)`

这样可以保证：

- session 真相仍然来自 data plane checkpoint store
- control layer 只做统一入口和必要聚合
- 不引入第二套 session source of truth

当前 northbound HTTP 仍保留以 `thread_id` 为 path 的资源路径，但 thread-scoped 查询 / 删除必须额外提供 `agent_name` query 参数。也就是说，control layer 对外的 session detail / history / delete 已经与 data plane southbound 一起收缩为 `agent_name + thread_id` 双键定位。

### 11.2 Telemetry

Telemetry 不应与 `SessionQuery` 复用同一语义模型。

control layer 对 telemetry 的定位是：

- gateway / ingest boundary
- northbound read boundary
- UI 与外部系统的统一查询入口

data layer 对 telemetry 的定位是：

- live execution fact producer
- raw `StreamPart` 的最近来源
- MQ 上游 sender

关键原则：

- control layer 不从 UI live stream 反推 telemetry 持久化
- runtime 不拥有 telemetry history query
- telemetry store 不与 `sessions.db` 混表
- telemetry 账本允许追加 gateway 自身的 audit event
- 产品 Trace 由 control 侧 `TelemetryStep` 投影提供，而不是 runtime 直接提供 span 树
- graph 查询必须逐步切换到 run-bound `TelemetryGraphSnapshot`

当前已存在的 northbound telemetry 接口包括：

- `POST /api/v1/agents/{agent}/telemetry/stream`
- `GET /api/v1/agents/{agent}/graph`

说明：

- 当前 live Telemetry UI 仍会复用 `GET /api/v1/agents/{agent}/graph` 作为 agent current graph
- 下一阶段 telemetry history / detail 必须切到 run-bound graph snapshot，而不是继续复用 agent current graph
- 历史 telemetry read API 继续挂在 control gateway 下，而不是回到 runtime southbound query

## 12. Routing 与 Deployment 设计

### 12.1 第一阶段

当前阶段只支持：

- 单一 `default_target`
- 单一共享 southbound gRPC client
- 启动时 bootstrap 默认 target 元数据
- 所有 runnable 主路径统一打到该共享 client

这足以支撑：

- 本地开发
- 单机部署
- 基础 CLI / gateway 流程
- 当前单 gateway 版本的 telemetry read / live tap

### 12.2 后续扩展

后续再扩展以下能力：

- 多 runtime target
- target health-based routing
- `deployment/runtime_target` 的正式 northbound 模型
- cron / scheduler
- K8s deployment orchestration

## 13. Northbound API 设计

当前 northbound 以 HTTP / SSE 为准。

### 13.1 资源管理接口

- `GET /api/v1/models`
- `PUT /api/v1/models/{name}`
- `GET /api/v1/models/{name}`
- `DELETE /api/v1/models/{name}`
- `GET /api/v1/skills`
- `PUT /api/v1/skills/{name}`
- `GET /api/v1/skills/{name}`
- `DELETE /api/v1/skills/{name}`
- `GET /api/v1/mcps`
- `PUT /api/v1/mcps/{name}`
- `GET /api/v1/mcps/{name}`
- `DELETE /api/v1/mcps/{name}`
- `GET /api/v1/agents`
- `PUT /api/v1/agents/{name}`
- `GET /api/v1/agents/{name}`
- `DELETE /api/v1/agents/{name}`

其中：

- `GET /api/v1/models`
- `GET /api/v1/skills`
- `GET /api/v1/mcps`
- `GET /api/v1/agents`

统一支持 `page_size` 与 `page_number` 分页参数。

### 13.2 生命周期接口

- `POST /api/v1/agents/{agent}/ensure_runnable`
- `POST /api/v1/agents/{agent}/runs/stream`
- `POST /api/v1/run_sessions/{session_id}/cancel`
- `POST /api/v1/run_sessions/{session_id}/hitl_decisions`

### 13.3 查询接口

- `GET /api/v1/health`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/latest`
- `GET /api/v1/sessions/{thread_id}?agent_name=...`
- `GET /api/v1/sessions/{thread_id}/message_page?agent_name=...`
- `GET /api/v1/sessions/{thread_id}/messages?agent_name=...`
- `DELETE /api/v1/sessions/{thread_id}?agent_name=...`

其中：

- `GET /api/v1/sessions` 支持 `agent_name`、`page_size`、`page_token`
- `GET /api/v1/sessions/latest` 支持可选 `agent_name`
- `message_page` 额外支持 `checkpoint_id`、`mode`、`page_size`、`page_token`、`include_raw`
- `messages` 额外支持 `mode`、`page_size`、`page_token`

### 13.4 Telemetry 接口

当前已经暴露：

- `POST /api/v1/agents/{agent}/telemetry/stream`
- `GET /api/v1/agents/{agent}/graph`

下一阶段建议补齐：

- `GET /api/v1/telemetry/runs`
- `GET /api/v1/telemetry/runs/{run_id}`
- `GET /api/v1/telemetry/runs/{run_id}/events`
- `GET /api/v1/telemetry/runs/{run_id}/steps`
- `GET /api/v1/telemetry/runs/{run_id}/graph`
- `GET /api/v1/telemetry/runs/{run_id}/stream`

### 13.5 当前未暴露的接口

- northbound gRPC
- `deployment` CRUD
- `runtime_target` CRUD

## 14. 可观测性

当前应区分“已落地基础能力”和“后续补齐项”。

已落地基础能力：

- southbound gRPC 请求日志
- northbound HTTP / SSE 行为测试
- run stream proxy 行为测试
- telemetry SSE / graph API 主链
- registry / resolver / orchestrator / runtime client 单元测试

后续补齐项：

- operation journal 接入主链路
- gateway audit event 持久化
- MQ ingest / dedup / ordering
- telemetry event ledger / step projection / run summary
- run-bound graph snapshot
- resumable telemetry SSE
- target health cache
- northbound request tracing
- trace context propagation (`traceparent` / `tracestate`)

关键指标建议包括：

- `install_latency`
- `compile_latency`
- `run_setup_latency`
- `active_runs`
- `hitl_pending_count`
- `runtime_target_health`
- `session_query_latency`
- `telemetry_ingest_lag`
- `telemetry_events_ingested`
- `telemetry_dedup_hits`
- `telemetry_query_latency`

## 15. 安全与一致性原则

- 当前 single-target 阶段不对外暴露伪多 target 能力
- `DeleteAgent` 默认走 uninstall 语义，不引入 public `stop`
- `CancelRun` 只作用于当前 execution stream
- control layer 不缓存 compiled runtime 对象
- resource delete 需要依赖检查
- 不允许 control layer 持有 data plane 私有资源 owner

## 16. 线性落地计划

以下时间表同步为当前实现状态。

### Phase 1：Go 工程骨架与领域模型

状态：已完成

- 建立 `libs/control/` Go module
- 建立 `domain`、`registry`、`resolver`、`packager`、`runtimeclient`、`orchestrator`、`api` 包结构
- 定义核心领域模型与接口

### Phase 2：Registry 与 Authored Validation

状态：已完成

- 落地 SQLite schema
- 实现 model configs / skills / MCP configs / agent specs CRUD
- 实现引用存在性校验与 authored 结构化校验

### Phase 3：Packager

状态：已完成

- authored resources -> rich `AgentSpec` packaging
- skill files 快照打包
- MCP 配置嵌入
- runtime-ready spec 校验

### Phase 4：Southbound Lifecycle Orchestration

状态：已完成（single `default_target` 版本）

- 接入 `ResourceSync` gRPC client
- 实现 `EnsureRunnable`
- runnable 主路径收缩为 single `default_target`

### Phase 5：Run Stream Proxy

状态：已完成

- 接入 `AgentExecutor.Run`
- 实现 northbound run stream
- 实现 HITL / cancel 转发
- 补齐 run audit

### Phase 6：Query 面、初版 API 与 Live Telemetry

状态：已完成

- 接入 `SessionQuery` 与 `Health`
- 提供 northbound HTTP / SSE 资源管理 / 生命周期 / 查询接口
- 提供资源列表的 `page_size / page_number` 分页能力
- 将 thread-scoped session 查询 / 删除统一收敛为 `agent_name + thread_id`
- 提供 northbound telemetry SSE 与 graph 查询

### Phase 7：Telemetry Gateway 化与持久化

状态：设计完成，待实现

- 明确 telemetry ownership 在 control gateway
- telemetry durable path 收敛为 `runtime -> MQ -> control gateway`
- 引入 `TelemetryEvent` 账本、`TelemetryRun`/`TelemetryStep`/`TelemetryGraphSnapshot`
- 支持 live/history 统一查询与 resumable stream
- 保留 `RunTelemetry` 作为 live tap，而非 history query

### Phase 8：Routing 与调度扩展

状态：backlog

- 多 target 路由
- scheduler / cron
- 部署编排
- K8s integration

## 17. 目标结果

当该设计落地后，control layer 应成为：

- authored resources 的 authoritative control plane
- runtime-ready `AgentSpec` 的统一 packager
- install / compile / execute / cancel / uninstall 的统一编排入口
- northbound HTTP / SSE 的统一 gateway
- telemetry / audit 的统一 ingress 与 read boundary

与此同时，data layer 继续保持为：

- compiled runtime owner
- execution owner
- session / checkpoint owner
- MCP / sandbox runtime owner
- telemetry live event producer

后续若进入 multi-target / deployment orchestration，再在当前 single-target 边界之上扩展，而不是回退当前主链路。
