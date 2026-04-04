# Agent OS 当前状态

> 快照日期：2026-03-27
> 状态：单机版主闭环完成，control/data 文档与协议口径已同步

## 1. 结论

当前项目可以认为已经完成了单机版 Agent OS 的主闭环：

- `data layer` 已完成核心 Agent Engine 能力，可被 control plane 作为稳定的本地执行底座使用
- `control plane` 已完成 single `default_target` 模型下的 registry、packaging、orchestration、northbound API 主路径
- 当前剩余事项主要分为两类：
  - 延期 backlog：真实部署验证、多 target、scheduler、K8s 等扩展能力
  - 收尾事项：working tree 正式入库与后续 backlog 排序

## 2. 总体状态

| 领域 | 当前状态 | 说明 |
|------|----------|------|
| Data Layer | 核心闭环完成 | Phase 1-5 完成，Phase 6 已达到“核心闭环完成，剩余延期” |
| Control Plane | 当前范围完成 | Phase 1-6 完成，当前实现范围是 single `default_target` |
| 架构文档 | 已同步 | control / data / overall architecture 已回填到当前实现口径 |
| Proto 结构与生成链 | 已完成 | `proto/runtime.proto`、Go/Python generated 与生成脚本已统一 |

## 3. 已完成事项

### 3.1 Data Layer

当前 `libs/runtime` 已完成：

- `SyncAgentSpec -> Assemble -> Run -> Health` 主链 gRPC 能力
- 富 `AgentSpec` 到 runtime graph 的装配主链
- gRPC `Run` 与 CLI `run` 统一走 `AgentManager` lifecycle
- agent-scoped MCP runtime lifecycle
- agent-owned sandbox lifecycle
- `SandboxSpec` 驱动 backend 选择
- `SessionQuery` 全量查询能力
- thread-scoped session 查询 / 删除收缩为 `agent_name + thread_id`
- health / readiness / live runtime status 输出
- protobuf 生成链固定到根目录 `proto/`
- 关键单元测试、process-local 集成测试、进程内 gRPC 集成测试

对应状态基准以 [runtime-data-layer-roadmap.md](./runtime-data-layer-roadmap.md) 为准。

### 3.2 Control Plane

当前 `libs/control` 已完成：

- Go module 骨架与领域模型
- SQLite-backed registry
- model configs / skills / MCP configs / authored agent specs CRUD
- 资源 list page 分页查询（`page_size / page_number`）
- 引用存在性校验与 authored validation
- authored resources -> runtime-ready `AgentSpec` packager
- `EnsureRunnable` southbound orchestration
- `AgentExecutor.Run` northbound run stream
- `SessionQuery` / `Health` 接入
- HTTP / SSE northbound API

当前 northbound contract 已覆盖：

- `health`
- `models` CRUD
- `skills` CRUD
- `mcps` CRUD
- `agents` CRUD
- `ensure_runnable`
- `runs/stream`
- `sessions` list / latest / detail / message page / delete

补充说明：

- `models / skills / mcps / agents` 的 list API 已统一支持 `page_size / page_number`
- thread-scoped session detail / message / delete 已要求 `agent_name + thread_id`

对应状态基准以 [control-plane-architecture.md](./control-plane-architecture.md) 为准。

### 3.3 架构口径

当前架构口径已经收敛为：

- control plane 不再把 `workspace` 视为当前 northbound contract
- runnable 主路径固定为 single `default_target`
- 当前不支持 per-agent target 选择和 multi-target routing
- `RuntimeTarget` / `Deployment` 仍保留为后续扩展模型，不属于当前 runnable main path

总体口径以 [agent-os-architecture.md](./agent-os-architecture.md) 为准。

## 4. 延期 Backlog

### 4.1 Data Layer Backlog

- 真实 `client -> server` gRPC 场景下的 `HITL / cancel / timeout` 深度回归
- 跨进程或真实部署形态下的 cleanup / shutdown 验证
- 默认 file-backed checkpoint 路径验证
- Windows 下 `RemoveResource` 删除兼容性处理
- `k8s` sandbox backend 实现与验证

### 4.2 Control Plane Backlog

- 多 target 路由
- scheduler / cron
- deployment orchestration
- K8s integration

## 5. 当前在途事项

当前这轮主闭环已经完成协议和文档收口。仍需留意的事项如下：

- 当前 working tree 仍需正式入库
- backlog 优先级仍需在“部署验证 / multi-target / UI”之间排定
- UI 文档本轮未纳入同步范围
- telemetry / 监控 southbound 扩展已进入设计阶段，见 [runtime-agent-telemetry-design.md](./runtime-agent-telemetry-design.md)

这一阶段的重点已经不再是补当前交互主链协议，而是决定下一轮 backlog 的推进顺序，并为监控扩展预留稳定边界。

## 6. 建议的下一步顺序

建议按以下顺序推进：

1. 完成当前 working tree 改动的正式入库。
2. 补真实 `client -> server` gRPC 下的 `HITL / cancel / timeout` 深度回归。
3. 再在 `multi-target`、`scheduler`、`UI` 之间确定下一轮优先级。

## 7. 当前判断

从工程状态看，当前更像是：

- 核心系统已经可用
- 协议与实现边界已经清晰
- 后续工作重心从“补主链路功能”转向“部署验证和扩展能力”

因此，当前最重要的不是继续加功能，而是基于已经收口的协议与文档，开始处理部署验证和下一阶段能力扩展。
