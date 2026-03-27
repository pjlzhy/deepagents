# Runtime 资源生命周期设计

> 状态：Final
> 最后更新：2026-03-24
> 范围：Phase 3 / Phase 4

## 1. 背景

当前 data plane 已经完成了两项关键收敛：

- gRPC `Run` 入口统一走 `AgentManager.invoke()` 执行路径
- `AgentEvent` 公共协议已经收敛为 `run_started / text_delta / text_done / tool_call_* / tool_result / hitl_request / run_ended / run_canceled / error`

接下来的重点不再是单点补功能，而是把 **agent 生命周期** 和 **run 生命周期** 拆开讲清楚，并据此统一 MCP、sandbox、assembly、remove 等语义。

这次设计要解决的核心问题是：

- `SyncAgentSpec`、`Assemble`、`Run`、`CancelRequest`、`RemoveResource` 各自到底代表什么动作
- MCP 和 sandbox 到底跟 agent 对齐，还是跟 run 对齐
- `stop_agent()` / `STOPPED` 这类中间语义是否应该继续作为 public 概念存在

## 2. 设计目标

本设计的目标是：

- 把 public 生命周期收敛成 `install / compile / execute / cancel / uninstall`
- 让 `AgentManager` 成为 data plane runtime 资源的唯一 owner
- 明确 agent 级资源与 run 级资源的边界
- 让 `assemble_agent()`、`invoke()`、`shutdown()`、`RemoveResource` 的资源行为一致
- 去掉 `stop` 这类容易与 run cancel 混淆的 public 语义

## 3. 非目标

本设计不处理以下事项：

- control plane 的 registry CRUD 和 packaging 实现细节
- `AgentSpec` 字段扩展本身
- 外部 northbound API 设计
- K8s / Docker backend 的完整实现细节

## 4. 双层生命周期模型

本设计明确区分两条生命周期：

- `agent artifact lifecycle`
- `run instance lifecycle`

两者相关，但不是一条状态机。

### 4.1 Agent 生命周期

agent 本体的 public 生命周期定义为：

```text
absent -> installed -> compiled(runnable) -> installed -> absent
```

动作映射如下：

- `SyncAgentSpec = install`
- `Assemble = compile`
- `Remove/Delete = uninstall`

其中：

- `installed` 表示 spec 已经被同步到 data plane，可被管理，但尚未保证 runnable
- `compiled` 表示 data plane 已经把该 agent 编译成可运行 runtime
- 从 `compiled` 回到 `installed` 不是 public `stop`，而只是内部 `unload` 语义
- `absent` 表示 data plane 中已不存在该 agent 的 spec 和 runtime

### 4.2 Run 生命周期

run 的 public 生命周期定义为：

```text
created -> running -> ended | canceled | errored
```

动作映射如下：

- `Run = execute`
- `CancelRequest = cancel current run`

这里的关键边界是：

- `cancel` 只作用于当前 run
- `uninstall` 作用于 agent 本体和其 runtime 资源
- `cancel` 绝不是 `remove` / `delete` / `stop` 的别名

### 4.3 `running` 是运行态叠加，不是 install 的替代品

如果需要对外展示状态，建议把 `running` 理解为对 `compiled` 的运行态覆盖：

- `installed`：已安装 spec，但当前不可直接执行
- `compiled`：已编译，可直接执行
- `running`：当前有一个或多个 active runs

换句话说，`running` 是 runtime overlay，不应取代 `installed / compiled` 这条主生命周期。

## 5. 资源 owner 与边界

### 5.1 `AgentManager` 是顶层 runtime owner

`AgentManager` 是 data plane runtime 的顶层 owner，负责：

- 管理 installed / compiled agent pool
- 管理 shared checkpointer
- 统一 run setup / teardown / cancel / timeout / error 收口

gRPC servicer 只负责：

- 读取 client stream
- 转发 HITL / cancel
- 调用 `AgentManager.invoke()`
- 转发事件

control plane 只负责：

- registry CRUD
- packaging
- install / compile / uninstall 的调用编排

### 5.2 MCP 默认与 compiled agent 对齐

MCP 默认采用 **agent-scoped** 生命周期：

- `Assemble` 时创建 MCP runtime
- `ManagedAgent` 持有 MCP runtime
- 每次 `invoke()` 复用同一个 compiled agent 的 MCP tools / sessions
- `unload`、`uninstall` 或 `shutdown()` 时统一 cleanup

原因如下：

- 当前 assembly 已经在加载 MCP tools，天然更接近 compiled-agent scope
- 可以避免每次 run 重启 MCP server
- owner 和 cleanup 位置更清晰
- 更适合 warm runtime

### 5.3 sandbox 默认与 compiled agent 对齐

sandbox 当前采用 **agent-owned backend lifecycle**。

当前实现不是 run-scoped sandbox lease / pool，而是：

- `Assemble` 时根据 `SandboxSpec` 创建一个 concrete sandbox backend
- `RuntimeAgent` 持有 `SandboxRuntime`
- `invoke()` / `astream()` 时将该 backend 注入 runtime context
- `release`、`uninstall` 或 `shutdown()` 时统一 cleanup

这意味着 sandbox 是：

- **owner 在 compiled agent 层**
- **backend 在 run 期间复用，而不是按 run 租用**

### 5.4 `SandboxSpec` 驱动 backend 选择

当前 runtime 使用如下解析顺序：

1. 优先读取 `sandbox.resources.backend`
2. 兼容读取 `sandbox.resources.kind`
3. 兼容读取 `sandbox.resources.provider`
4. 如果未声明 backend，但声明了 `image`，默认视为 `docker`
5. 否则默认视为 `local`

当前支持的 backend kind：

- `local`
- `docker`
- `k8s`

兼容别名：

- `filesystem -> local`
- `shell -> local`
- `kubernetes -> k8s`

## 6. Public 语义与 internal 语义

### 6.1 不再引入 public `StopAgent`

`StopAgent` 不应作为 public 语义继续扩散，原因是它会同时混淆三种不同动作：

- cancel 当前 run
- 卸载 compiled runtime
- 删除 agent 本体

其中：

- 取消当前 run 已由 `CancelRequest` 覆盖
- 删除 agent 本体应该走 `Remove/Delete`
- 仅释放 compiled runtime 如果仍有需要，应保留为内部 `unload_agent()`

### 6.2 `stop_agent()` 只应被视为临时内部实现名

如果代码里暂时仍保留 `stop_agent()`，它的正确理解也应该是：

- **不是 cancel**
- **不是 uninstall**
- **只是 internal unload**

长期目标应是把它改名为更准确的内部能力：

- `unload_agent()`
- 或 `release_agent_runtime()`

## 7. 运行时分层

建议把 runtime 资源分为三层：

### 7.1 `AgentSpec` 层

纯声明层，不持有 live 资源。

包含：

- `sandbox_spec`
- `mcp_configs`
- prompt / skills / subagents

### 7.2 `RuntimeAgent` / compiled runtime 层

长生命周期资源层，由 `AgentManager` 持有、由 `RuntimeAgent` 实际承载。

建议包含：

- `graph`
- `mcp_runtime`
- `sandbox_runtime`
- `status`
- `last_invoked`

### 7.3 `AgentRun` 层

单次调用上下文层。

建议包含：

- `run_id`
- `thread_id`
- hitl handler
- run stats
- cancel / timeout 控制状态

## 8. 数据结构建议

### 8.1 `RuntimeAgent`

当前代码已经收敛到 `RuntimeAgent` 持有 compiled runtime，结构近似为：

```python
class RuntimeAgent:
    spec: AgentSpec
    graph: CompiledStateGraph | None = None
    mcp_runtime: MCPRuntime | None = None
    sandbox_runtime: SandboxRuntime | None = None
    runtime_status: str | None = None
    last_invoked: datetime | None = None
```

### 8.2 `MCPRuntime`

建议新增运行时结构，用于封装 assembly 后的 MCP live 资源。

```python
@dataclass
class MCPRuntime:
    session_manager: MCPSessionManager
    tools: list[BaseTool]
    server_infos: list[MCPServerInfo]
```

### 8.3 `SandboxRuntime`

当前 `SandboxRuntime` 已用于封装 agent-owned sandbox backend。

```python
@dataclass
class SandboxRuntime:
    spec: SandboxSpec
    backend: Any
```

### 8.4 `AgentRun`

当前没有独立的 `AgentRun` 对象。run 级上下文由 `AgentManager.invoke()` 与 `RuntimeAgent.astream()` 共同承载。

```python
run_id: str
thread_id: str
hitl_handler: HITLHandler | None
cancel_event: asyncio.Event | None
timeout_seconds: float | None
```

run 层不再创建 MCP clients，也不再持有 sandbox lease。

## 9. 动作语义

### 9.1 `install = SyncAgentSpec`

行为：

- 持久化 spec
- 创建或更新 `ManagedAgent`
- 不创建 live runtime 资源

结束语义：

- `installed`

### 9.2 `compile = Assemble`

行为：

1. 读取 `RuntimeAgent.spec`
2. 构建 compiled graph
3. 初始化 `mcp_runtime`
4. 初始化 `sandbox_runtime`
5. 将 runtime 资源挂到 `RuntimeAgent`

结束语义：

- `compiled`
- `runnable`

### 9.3 `execute = Run`

行为：

1. 要求 agent 已处于 compiled 状态
2. `AgentManager` 统一准备 `run_id`、`thread_id`、timeout、cancel 控制
3. `RuntimeAgent.astream()` 使用 compiled graph 执行 run
4. MCP 直接复用 `RuntimeAgent.mcp_runtime`
5. sandbox 直接复用 `RuntimeAgent.sandbox_runtime.backend`

运行态变化：

- `compiled -> running`
- run 结束后恢复为 `compiled`

### 9.4 `cancel = CancelRequest`

行为：

- 仅取消当前 `Run` 流对应的执行实例
- 终态事件流结束于 `run_canceled`
- 不删除 spec
- 不释放 compiled agent runtime

### 9.5 `uninstall = Remove/Delete`

行为：

1. 校验目标 agent 当前没有 active runs
2. 清理 `mcp_runtime`
3. 清理 `sandbox_runtime`
4. 清理 `template`
5. 删除 synced spec / runtime cache

结束语义：

- `absent`

默认约束：

- 有 active runs 时拒绝 uninstall
- 后续如果要支持强制删除，再单独引入 `force`

### 9.6 internal `unload`

如仍需要“只释放 compiled runtime，但保留 spec”的能力，应视为内部动作：

- `compiled -> installed`
- 不暴露为 public `stop`
- 仅用于 manager 内部资源管理或调试运维

### 9.7 `shutdown()`

行为：

- 遍历所有 `RuntimeAgent`
- 统一关闭 compiled 级 runtime 资源
- 跳过仍在 running 的 agent
- 关闭 checkpointer

## 10. 并发语义

### 10.1 MCP

默认复用同一个 compiled agent 的 MCP runtime。

如果后续验证发现某些 MCP provider 不支持并发共享，则扩展方案为：

- 保留 agent 级 `MCPRuntimeFactory`
- run 从 factory 中借用 session

但当前默认不做 per-run MCP client 重建。

### 10.2 sandbox

当前 runtime 采用“同 agent 单 run”并发模型。

因此，当前 sandbox 语义是：

- 不存在 run-scoped sandbox lease
- 同一个 compiled agent 的 run 复用同一个 owned backend
- 如后续放开同 agent 多 run，需要重新定义 sandbox 并发语义

### 10.3 backend 语义边界

`local`：

- 使用 `LocalShellBackend`
- root 指向 agent workspace
- 具备本地文件系统和本地 shell 执行能力
- 不提供进程隔离

`docker`：

- assemble 时创建 long-lived container
- run 期间复用该 container
- release 时销毁 container
- 当前要求镜像内具备 `sh` 和 `python3`
- 当前不支持 per-command timeout override

`k8s`：

- 契约中已保留
- 当前 runtime 仍返回 `NotImplementedError`
- 在实现完成前，不应作为可用 backend 对外承诺

## 11. 与当前实现的映射关系

当前代码中的术语与目标语义建议映射如下：

| 当前实现 | 建议解释 | 说明 |
|----------|----------|------|
| `define_agent()` | `install` | 同步 spec，不创建 live runtime |
| `assemble_agent()` | `compile` | 构建 runnable runtime |
| `invoke()` | `execute` | 执行单次 run |
| `CancelRequest` | `cancel current run` | 只影响当前执行流 |
| `unload_agent()` | internal `unload` | 释放 compiled runtime，保留 spec |
| `RemoveResource` | `uninstall/delete` | 最终承担删除语义 |

状态枚举建议映射如下：

| 当前状态 | 目标语义 | 备注 |
|----------|----------|------|
| `INSTALLED` | `installed` | spec 已存在 |
| `COMPILED` | `compiled` / `runnable` | 已可执行 |
| `RUNNING` | `running overlay` | active run 覆盖态 |

## 12. 收敛状态

以下收敛工作已完成：

1. ✅ 统一文档语义，明确 `install / compile / execute / cancel / uninstall`
2. ✅ 把 public 协议和外部术语中的 `stop` 全部收掉
3. ✅ 将代码中的 `stop_agent()` 移除，仅保留 `unload_agent()`
4. ✅ 让 `RemoveResource` 对 agent 场景明确承接 uninstall/delete 语义
5. ✅ 移除 `sandbox_pool` 兼容残留
6. ⏳ 统一 health / status 输出（Phase 5 范围）

## 13. 结论

本设计的最终结论是：

- `SyncAgentSpec = install`
- `Assemble = compile`
- `Run = execute`
- `CancelRequest = cancel current run`
- `Remove/Delete = uninstall`

同时：

- `AgentManager` 是顶层 runtime owner，`RuntimeAgent` 是 compiled runtime 的直接 owner
- MCP 默认采用 **agent-scoped / compiled-agent-scoped** 生命周期
- sandbox 默认采用 **agent-owned backend lifecycle**
- 当前不存在独立的 `AgentRun` 对象，也不存在 run-scoped sandbox lease
- `stop` 已从代码和 public 语义中移除

这套模型把 public 语义、runtime owner、资源边界和执行协议统一到了同一条线上，是 Phase 5 及后续实现的基准口径。
