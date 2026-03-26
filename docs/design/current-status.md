# Agent OS 当前状态

> 快照日期：2026-03-26
> 状态：单机版主闭环完成，扩展能力与迁移收口进行中

## 1. 结论

当前项目可以认为已经完成了单机版 Agent OS 的主闭环：

- `data layer` 已完成核心 Agent Engine 能力，可被 control plane 作为稳定的本地执行底座使用
- `control plane` 已完成 single `default_target` 模型下的 registry、packaging、orchestration、northbound API 主路径
- 当前剩余事项主要分为两类：
  - 延期 backlog：真实部署验证、多 target、scheduler、K8s 等扩展能力
  - 在途收口：`proto/` 目录迁移、生成链统一、工作区改动正式入库

## 2. 总体状态

| 领域 | 当前状态 | 说明 |
|------|----------|------|
| Data Layer | 核心闭环完成 | Phase 1-5 完成，Phase 6 已达到“核心闭环完成，剩余延期” |
| Control Plane | 当前范围完成 | Phase 1-6 完成，当前实现范围是 single `default_target` |
| 架构文档 | 基本同步 | control / data / overall architecture 已收缩到当前实现口径 |
| Proto 迁移 | 在途 | 新 `proto/runtime.proto` 已落地，生成链和入库仍在收口 |

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
- health / readiness / live runtime status 输出
- 关键单元测试、process-local 集成测试、进程内 gRPC 集成测试

对应状态基准以 [runtime-data-layer-roadmap.md](./runtime-data-layer-roadmap.md) 为准。

### 3.2 Control Plane

当前 `libs/control` 已完成：

- Go module 骨架与领域模型
- SQLite-backed registry
- skills / MCP configs / authored agent specs CRUD
- 引用存在性校验与 authored validation
- authored resources -> runtime-ready `AgentSpec` packager
- `EnsureRunnable` southbound orchestration
- `AgentExecutor.Run` northbound run stream
- `SessionQuery` / `Health` 接入
- HTTP / SSE northbound API

当前 northbound contract 已覆盖：

- `health`
- `skills` CRUD
- `mcps` CRUD
- `agents` CRUD
- `ensure_runnable`
- `runs/stream`
- `sessions` list / latest / detail / message page / delete

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

以下事项不是 backlog，而是当前工作区中已经开始、但尚未正式收口的改动：

- `proto` 结构从旧路径迁移到新的 [runtime.proto](../../proto/runtime.proto)
- Go 侧生成产物已经落到 `libs/control/pkg/proto/`
- Python runtime 侧 generated 文件和 `proto_codegen.py` 正在跟随新 proto 结构调整
- control / data / overall architecture 文档都已同步到当前实现口径，但仍处于未提交状态

这一阶段的目标不是新增功能，而是把协议路径、代码生成链、生成产物和文档一次性统一下来。

## 6. 建议的下一步顺序

建议按以下顺序推进：

1. 先收口 `proto` 迁移和生成链，避免后续继续生成到错误目录。
2. 跑一轮 control/runtime 相关测试，确认新 proto 路径下的编译和调用链稳定。
3. 完成当前 working tree 改动的正式入库。
4. 再评估是否进入 Phase 7，而不是提前展开 multi-target 设计。

## 7. 当前判断

从工程状态看，当前更像是：

- 核心系统已经可用
- 协议与实现边界已经清晰
- 后续工作重心从“补主链路功能”转向“协议收口、部署验证和扩展能力”

因此，当前最重要的不是继续加功能，而是先把这轮主闭环对应的协议、生成链、文档和测试全部收口。
