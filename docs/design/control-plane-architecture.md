# Control Layer Architecture Design

> 状态：草案
> 最后更新：2026-03-25
> 目标实现语言：Go

## 1. 背景

当前 `libs/runtime` 已经收敛为稳定的 data layer / agent engine：

- data layer 负责消费富 `AgentSpec`
- data layer 负责 `Assemble -> Run` 执行主链路
- data layer 持有 compiled runtime、MCP runtime、sandbox runtime、checkpoint/session state
- control plane 与 data plane 的唯一边界已经收敛为 `proto/deepagents/runtime/v1/runtime.proto`

下一步需要补齐 control layer，使系统具备完整的 control plane / data plane 分层。

本设计文档的目标是定义一版可落地的 Go control layer 架构，使其与当前 data layer 的边界保持一致，并为后续 CLI、gateway、scheduler、K8s 部署提供稳定控制面。

## 2. 设计目标

control layer 的目标是：

- 作为 skills、MCP configs、AgentSpecs、workspaces 的 authoritative registry
- 负责 authored resources 的引用解析和 runtime-ready packaging
- 负责 `install / compile / execute / cancel / uninstall` 的 southbound 编排
- 负责 northbound API、CLI、gateway、scheduler 的统一入口
- 负责 agent -> runtime endpoint 的路由与部署元数据管理
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
- workspace / shared references 解析
- rich `AgentSpec` packaging
- install / compile / uninstall orchestration
- run stream proxy
- routing / deployment metadata
- northbound API

data layer 负责：

- rich `AgentSpec` -> compiled runtime
- `Run` 执行
- agent-scoped MCP runtime / sandbox runtime
- run-scoped execution state
- checkpoint / session state

### 4.2 协议边界

control layer 只通过以下 southbound gRPC service 与 data layer 通信：

- `ResourceSync`
- `AgentExecutor`
- `SessionQuery`

其中：

- `SyncAgentSpec` 是主同步单元
- `SyncSkill` / `SyncMcp` 仅保留为兼容接口，不作为新主路径
- `Assemble` 承担 compile 语义
- `RemoveResource` 承担 uninstall/delete 语义
- `SessionQuery` 提供 runtime-local session 查询和删除能力

## 5. 总体架构

control layer 建议实现为：

```text
Northbound API / CLI / Gateway / Scheduler
    -> Control Services
        -> Registry
        -> Workspace Resolver
        -> Packager
        -> Orchestrator
        -> Router
        -> Runtime Clients (gRPC)
            -> ResourceSync
            -> AgentExecutor
            -> SessionQuery
                -> Data Plane
```

一句话定义：

```text
deepagents-control = Registry + Packager + Orchestrator + Northbound API
```

## 6. Go 模块拆分

建议新建 Go module：

```text
libs/control/deepagents-control
```

建议的目录结构：

```text
libs/control/deepagents-control/
├── cmd/control/
│   └── main.go
├── internal/config/
├── internal/domain/
├── internal/registry/
├── internal/workspace/
├── internal/packager/
├── internal/router/
├── internal/runtimeclient/
├── internal/orchestrator/
├── internal/api/
├── internal/streamproxy/
└── internal/store/
```

各模块职责如下。

### 6.1 `internal/domain`

纯领域模型，不依赖 gRPC、HTTP、数据库驱动。

建议至少定义：

- `Skill`
- `McpConfig`
- `AuthoredAgentSpec`
- `Workspace`
- `Deployment`
- `RuntimeTarget`
- `Operation`

### 6.2 `internal/registry`

authoritative resource registry。

负责：

- skills CRUD
- MCP configs CRUD
- authored agent specs CRUD
- 资源依赖关系
- 删除前引用检查

### 6.3 `internal/workspace`

workspace 及 shared references 解析层。

负责：

- workspace 定义和绑定关系
- workspace root 解析
- shared reference 展开
- authored resources 到 workspace 的归属

### 6.4 `internal/packager`

将 control layer 中的 authored state 打包成 runtime-ready `AgentSpec`。

负责：

- prompt / model 合成
- skill 目录快照打包
- MCP configs 嵌入
- subagent metadata 展开
- sandbox spec 合法性检查
- 输出 `SyncAgentSpecRequest`

### 6.5 `internal/router`

agent 到 runtime endpoint 的路由层。

第一阶段建议只支持：

- 一个 agent 绑定一个 runtime target
- 手工配置 endpoint
- 健康状态 best-effort 检查

后续再扩展：

- 多 target 路由
- 权重 / 优先级
- scheduler
- K8s discovery

### 6.6 `internal/runtimeclient`

对 southbound gRPC 的薄封装。

建议拆成三个 client：

- `ResourceSyncClient`
- `AgentExecutorClient`
- `SessionQueryClient`

要求：

- 不在 client 层重写业务状态机
- 尽量保持 proto 语义原样透传
- 统一做连接管理、超时、重试和错误包装

### 6.7 `internal/orchestrator`

control layer 的核心 service 层。

负责：

- `InstallAgent`
- `CompileAgent`
- `EnsureRunnable`
- `RunAgent`
- `CancelRun`
- `DeleteAgent`
- `QuerySessions`
- `GetHealth`

### 6.8 `internal/api`

northbound API。

第一阶段可选两种实现：

- gRPC northbound
- HTTP + SSE / WebSocket

如果优先考虑 CLI 和 Web UI，对开发效率更友好的选择是：

- 管理类接口使用 HTTP
- 流式执行使用 SSE 或 WebSocket

### 6.9 `internal/streamproxy`

运行流代理层。

负责：

- northbound run request -> southbound `AgentExecutor.Run`
- `AgentEvent` 原样转发
- `HITLRequest` / `HITLDecision` 关联
- `CancelRequest` 转发
- run 审计记录

## 7. 核心领域模型

### 7.1 资源模型

第一阶段建议在 control layer 管理以下资源：

| 资源 | 说明 | authoritative owner |
|------|------|---------------------|
| `Skill` | 技能目录快照与元数据 | control layer |
| `McpConfig` | MCP server 配置模板 | control layer |
| `AuthoredAgentSpec` | 用户编写的 agent 定义 | control layer |
| `Workspace` | authoring / packaging / deployment 分组 | control layer |
| `Deployment` | agent 到 runtime target 的绑定 | control layer |
| `RuntimeTarget` | data plane endpoint 描述 | control layer |

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

第一阶段建议使用 SQLite，避免过早引入分布式 control store。

建议表结构如下：

| 表 | 用途 |
|----|------|
| `skills` | skill 元数据 |
| `skill_files` | skill 目录快照 |
| `mcp_configs` | MCP 配置 |
| `agent_specs` | authored agent specs |
| `workspaces` | workspace 定义 |
| `workspace_resources` | workspace 到资源的绑定 |
| `runtime_targets` | data plane endpoint 定义 |
| `deployments` | agent 到 target 的绑定与 desired state |
| `operations` | install / compile / run / delete 审计记录 |

第一阶段不建议做：

- 独立 session registry
- 分布式锁服务
- CRD/operator 型 registry

## 9. Packaging 设计

control layer 的核心能力不是执行，而是 packaging。

### 9.1 输入

packager 的输入包括：

- `AuthoredAgentSpec`
- skill 引用
- MCP config 引用
- workspace / shared references
- runtime target 约束

### 9.2 输出

packager 的输出是 runtime-ready `SyncAgentSpecRequest`。

输出要求：

- `skills` 使用嵌入式目录快照
- `mcp_servers` 使用完整 runtime 配置
- `model` 与 `model_config` 收敛成可执行形式
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

1. 读取 deployment 和 target
2. 读取 authored spec
3. packaging 为 rich `AgentSpec`
4. 调用 `SyncAgentSpec`
5. 调用 `Assemble`
6. 记录 operation 结果

这个 helper 只是一层编排便利接口，不改变 southbound 协议语义。

### 10.3 `RunAgent`

`RunAgent` 的推荐流程：

1. 解析 agent -> deployment -> runtime target
2. 调用 `EnsureRunnable`
3. 建立 `AgentExecutor.Run` 双向流
4. 发送 `RunRequest`
5. 原样转发 `AgentEvent`
6. 收到 `HITLRequest` 时，等待 northbound decision
7. 转发 `HITLDecision`
8. 用户取消时转发 `CancelRequest`
9. 流结束后写 operation / run audit

关键原则：

- control layer 不重新解释 `AgentEvent` 细节语义
- control layer 不重做 parser state machine
- event 扩展应优先通过 proto 扩展，而不是在 control layer 写死逻辑

## 11. Session 与 Health 设计

第一阶段建议把 session 与 health 视为 runtime query，而不是 control-owned state。

control layer 提供 northbound 查询接口，但 southbound 直接代理：

- `Health`
- `ListSessions`
- `GetSession`
- `GetSessionMessages`
- `GetLatestSession`
- `DeleteSession`

这样可以保证：

- session 真相仍然来自 data plane checkpoint store
- control layer 只做统一入口和必要聚合
- 不引入第二套 session source of truth

## 12. Routing 与 Deployment 设计

### 12.1 第一阶段

第一阶段只支持：

- 单 runtime target
- 手工 endpoint 配置
- 单 agent -> 单 target 映射

这足以支撑：

- 本地开发
- 单机部署
- 基础 CLI / gateway 流程

### 12.2 后续扩展

后续再扩展以下能力：

- 多 runtime target
- target health-based routing
- tenant / workspace 级路由
- cron / scheduler
- K8s deployment orchestration

## 13. Northbound API 设计

第一阶段建议对上提供三类接口。

### 13.1 资源管理接口

- `CreateSkill`
- `UpdateSkill`
- `DeleteSkill`
- `CreateMcpConfig`
- `UpdateMcpConfig`
- `DeleteMcpConfig`
- `CreateAgentSpec`
- `UpdateAgentSpec`
- `DeleteAgentSpec`
- `ListResources`
- `GetResolvedAgentSpec`

### 13.2 生命周期接口

- `InstallAgent`
- `CompileAgent`
- `RunAgent`
- `CancelRun`
- `DeleteAgent`
- `GetAgentStatus`

### 13.3 查询接口

- `Health`
- `ListSessions`
- `GetSession`
- `GetSessionMessages`
- `GetLatestSession`
- `DeleteSession`

## 14. 可观测性

control layer 至少应补齐以下观测面：

- southbound gRPC 请求日志
- operation journal
- run 审计日志
- target health cache
- northbound request tracing

关键指标建议包括：

- `install_latency`
- `compile_latency`
- `run_setup_latency`
- `active_runs`
- `hitl_pending_count`
- `runtime_target_health`
- `session_query_latency`

## 15. 安全与一致性原则

- 所有 southbound 动作必须记录 operation journal
- `DeleteAgent` 默认走 uninstall 语义，不引入 public `stop`
- `CancelRun` 只作用于当前 execution stream
- control layer 不缓存 compiled runtime 对象
- resource delete 需要依赖检查
- 不允许 control layer 持有 data plane 私有资源 owner

## 16. 线性落地计划

以下时间表是 control layer 的建议实现顺序。

### Phase 1：Go 工程骨架与领域模型

**2026-03-26 至 2026-03-28**

目标：

- 建立 `libs/control/deepagents-control` Go module
- 建立 `domain`、`registry`、`packager`、`runtimeclient`、`orchestrator`、`api` 包结构
- 定义核心领域模型与接口

### Phase 2：Registry 与 Workspace

**2026-03-29 至 2026-04-02**

目标：

- 落地 SQLite schema
- 实现 skills / MCP configs / agent specs / workspaces CRUD
- 实现依赖检查和 workspace 绑定

### Phase 3：Packager

**2026-04-03 至 2026-04-06**

目标：

- authored resources -> rich `AgentSpec` packaging
- skill files 快照打包
- MCP 配置嵌入
- runtime-ready spec 校验

### Phase 4：Southbound Lifecycle Orchestration

**2026-04-07 至 2026-04-10**

目标：

- 接入 `ResourceSync` gRPC client
- 实现 `InstallAgent` / `CompileAgent` / `DeleteAgent`
- 实现 `EnsureRunnable`

### Phase 5：Run Stream Proxy

**2026-04-11 至 2026-04-14**

目标：

- 接入 `AgentExecutor.Run`
- 实现 northbound run stream
- 实现 HITL / cancel 转发
- 补齐 run audit

### Phase 6：Query 面与初版 API

**2026-04-15 至 2026-04-17**

目标：

- 接入 `SessionQuery` 与 `Health`
- 提供 northbound 资源管理 / 生命周期 / 查询接口
- 支撑 CLI 或简化 gateway

### Phase 7：Routing 与调度扩展

**2026-04-18 之后**

目标：

- 多 target 路由
- scheduler / cron
- 部署编排
- K8s integration

## 17. 目标结果

当该设计落地后，control layer 应成为：

- authored resources 的 authoritative control plane
- rich `AgentSpec` 的统一 packager
- install / compile / execute / cancel / uninstall 的统一编排入口
- northbound API、CLI、gateway、scheduler 的基础底座

与此同时，data layer 继续保持为：

- compiled runtime owner
- execution owner
- session / checkpoint owner
- MCP / sandbox runtime owner

这两层的边界将保持清晰、稳定，并可分别独立演进。
