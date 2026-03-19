# Runtime 资源生命周期设计

> 状态：Draft
> 最后更新：2026-03-19
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

### 5.1 `AgentManager` 是唯一 runtime owner

`AgentManager` 应该成为以下资源的唯一 owner：

- compiled `AgentTemplate`
- agent-scoped MCP runtime
- agent-scoped sandbox owner / pool
- active runs

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

### 5.3 sandbox 由 manager 持有 owner，但默认按 run 租用实例

sandbox 也由 `AgentManager` 管理，但默认不作为 agent 共享单实例。

推荐模型是：

- `Assemble` 时初始化 sandbox factory / strategy / pool
- `ManagedAgent` 持有 sandbox owner
- `invoke()` 时按 run 获取 sandbox lease / instance
- run 结束后释放 lease
- `unload`、`uninstall` 或 `shutdown()` 时回收该 agent 对应的 sandbox owner 和 warm instances

这意味着 sandbox 是：

- **owner 在 agent 层**
- **具体实例使用在 run 层**

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
- prompt / memory / tools / subagents

### 7.2 `ManagedAgent` / compiled runtime 层

长生命周期资源层，由 `AgentManager` 持有。

建议包含：

- `template`
- `mcp_runtime`
- `sandbox_runtime`
- `status`
- `active_run_count`

### 7.3 `AgentRun` 层

单次调用上下文层。

建议包含：

- `run_id`
- `thread_id`
- `sandbox_lease`
- hitl handler
- run stats

## 8. 数据结构建议

### 8.1 `ManagedAgent`

建议扩展为：

```python
@dataclass
class ManagedAgent:
    name: str
    spec: AgentSpec
    template: AgentTemplate | None = None
    mcp_runtime: MCPRuntime | None = None
    sandbox_runtime: SandboxRuntime | None = None
    status: AgentStatus = AgentStatus.DEFINED
    active_run_count: int = 0
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

建议新增运行时结构，用于封装 agent 级 sandbox 策略。

```python
@dataclass
class SandboxRuntime:
    spec: SandboxSpec
    pool: SandboxPool
```

### 8.4 `AgentRun`

建议收缩职责，不再创建 MCP clients。

```python
@dataclass
class AgentRun:
    template: AgentTemplate
    run_id: str
    thread_id: str
    sandbox: Any | None = None
```

`AgentRun` 只负责持有本次 run 的 sandbox lease 和上下文信息。

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

1. 读取 `ManagedAgent.spec`
2. 构建 graph / template
3. 初始化 `mcp_runtime`
4. 初始化 `sandbox_runtime`
5. 将 runtime 资源挂到 `ManagedAgent`

结束语义：

- `compiled`
- `runnable`

### 9.3 `execute = Run`

行为：

1. 若未 compile，则先 compile
2. 从 `sandbox_runtime.pool` 获取 sandbox lease
3. 使用 compiled graph 执行 run
4. MCP 直接复用 `ManagedAgent.mcp_runtime`
5. run 结束后释放 sandbox lease

运行态变化：

- `compiled -> running`
- 当 `active_run_count` 回到 `0` 时，恢复为 `compiled`

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

- 遍历所有 `ManagedAgent`
- 统一关闭 compiled 级 runtime 资源
- 清理 active runs
- 关闭 checkpointer

## 10. 并发语义

### 10.1 MCP

默认假设同一个 compiled agent 的 MCP runtime 可被多个 run 复用。

如果后续验证发现某些 MCP provider 不支持并发共享，则扩展方案为：

- 保留 agent 级 `MCPRuntimeFactory`
- run 从 factory 中借用 session

但默认不做 per-run MCP client 重建。

### 10.2 sandbox

默认支持并发 run，但每个 run 获取各自的 sandbox lease。

不默认允许多个 run 共享同一个 concrete sandbox 实例。

## 11. 与当前实现的映射关系

当前代码中的术语与目标语义建议映射如下：

| 当前实现 | 建议解释 | 说明 |
|----------|----------|------|
| `define_agent()` | `install` | 同步 spec，不创建 live runtime |
| `assemble_agent()` | `compile` | 构建 runnable runtime |
| `invoke()` | `execute` | 执行单次 run |
| `CancelRequest` | `cancel current run` | 只影响当前执行流 |
| `stop_agent()` | internal `unload` | 不应继续作为 public 语义 |
| `RemoveResource` | `uninstall/delete` | 最终承担删除语义 |

状态枚举建议映射如下：

| 当前状态 | 目标语义 | 备注 |
|----------|----------|------|
| `DEFINED` | `installed` | spec 已存在 |
| `ASSEMBLED` | `compiled` / `runnable` | 已可执行 |
| `RUNNING` | `running overlay` | active run 覆盖态 |
| `STOPPED` | internal unloaded | 长期不建议作为 public 状态 |

## 12. 收敛顺序建议

建议按以下顺序继续推进：

1. 先统一文档语义，明确 `install / compile / execute / cancel / uninstall`
2. 把 public 协议和外部术语中的 `stop` 全部收掉
3. 将代码中的 `stop_agent()` 重命名为 `unload_agent()` 或等价内部名
4. 让 `RemoveResource` 对 agent 场景明确承接 uninstall/delete 语义
5. 统一 health / status 输出，不再把 `STOPPED` 当成产品态

## 13. 结论

本设计的最终结论是：

- `SyncAgentSpec = install`
- `Assemble = compile`
- `Run = execute`
- `CancelRequest = cancel current run`
- `Remove/Delete = uninstall`

同时：

- `AgentManager` 是 MCP 和 sandbox 的唯一 runtime owner
- MCP 默认采用 **agent-scoped / compiled-agent-scoped** 生命周期
- sandbox 默认采用 **agent-scoped owner + run-scoped lease** 生命周期
- `AgentRun` 只持有单次调用上下文，不持有跨 run 的 live 资源
- `stop` 不再作为 public 生命周期概念继续扩散

这套模型把 public 语义、runtime owner、资源边界和执行协议统一到了同一条线上，是 Phase 4 后续实现和文档的基准口径。
