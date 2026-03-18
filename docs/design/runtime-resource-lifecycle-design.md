# Runtime 资源生命周期设计

> 状态：Draft
> 最后更新：2026-03-18
> 范围：Phase 3 / Phase 4

## 1. 背景

当前 data plane 已经完成了 Phase 3 的关键一步：gRPC `Run` 入口收敛到 `AgentManager.invoke()`，统一了 transport 层和 runtime 层的主调用路径。

接下来的核心问题是：MCP 和 sandbox 应该由谁持有，它们的生命周期应该和什么对齐。

当前实现中已经暴露出两个约束：

- MCP 工具已经在 assembly 阶段加载，但对应的 session manager 没有被 `AgentManager` 持有
- sandbox 虽然在 `AgentRun.setup()` 中被获取，但 graph 仍然在 assembly 阶段绑定到固定 backend，导致 sandbox 生命周期讨论尚未真正作用到执行面

因此，Phase 4 的目标不是单纯“什么时候创建资源”，而是先明确 **owner、生命周期边界和运行时注入方式**。

## 2. 设计目标

本设计的目标是：

- 让 `AgentManager` 成为 runtime 资源的唯一 owner
- 明确 agent 级资源与 run 级资源的边界
- 让 `assemble_agent()`、`invoke()`、`stop_agent()`、`shutdown()` 之间的资源行为一致
- 避免 transport 层直接持有 runtime 资源
- 为后续 gRPC `stop` / `start` 管理接口预留清晰语义

## 3. 非目标

本设计不处理以下事项：

- control plane 的 registry CRUD 和 packaging 逻辑
- `AgentSpec` 字段扩展本身
- 外部 API 设计
- K8s / Docker backend 的完整实现细节

## 4. 当前问题

### 4.1 MCP 生命周期分裂

当前存在两条并存路径：

- assembly 阶段通过 `load_mcp_tools_from_configs()` 加载 live MCP tools
- run 阶段通过 `AgentRun.setup()` 尝试创建 per-run MCP client

问题在于：

- assembly 阶段的 `MCPSessionManager` 没有被保存，也没有 cleanup
- run 阶段的 `_start_mcp_client()` 仍然是 placeholder
- 同一个 MCP 生命周期同时出现在 assembly 和 run 两个层级，owner 不明确

### 4.2 sandbox 生命周期尚未接入执行面

当前 `AgentRun.setup()` 会获取 sandbox，但 graph 在 assembly 阶段仍绑定到固定 backend。

这意味着：

- sandbox 已经被“创建”
- 但运行时工具调用未必真正经过它
- 生命周期模型还不能反映真实执行语义

### 4.3 agent 状态机不再适配新模型

如果 MCP 或 sandbox 变为 agent 级资源，单次 `invoke()` 结束后不应直接把 agent 状态设为 `STOPPED`。

Phase 4 之后更合理的状态语义应为：

- `DEFINED`：存在 spec，但未装配 runtime 资源
- `ASSEMBLED`：模板和 agent 级资源已就绪，可复用
- `RUNNING`：当前存在一个或多个 active runs
- `STOPPED`：显式 stop 后，agent 级 runtime 资源已释放

## 5. 核心设计结论

### 5.1 `AgentManager` 是唯一资源 owner

`AgentManager` 应该成为以下资源的唯一 owner：

- assembled agent template
- agent 级 MCP runtime
- agent 级 sandbox factory / sandbox pool
- active runs

gRPC servicer 只负责：

- 读取 client stream
- 转发 HITL / cancel
- 调用 `AgentManager.invoke()`
- 转发事件

`AgentRun` 不再作为长生命周期资源 owner，而只表示一次调用上下文。

### 5.2 MCP 默认与 assembled agent 生命周期对齐

MCP 建议默认采用 **agent-scoped** 生命周期：

- `assemble_agent()` 时创建 MCP runtime
- `ManagedAgent` 持有 MCP runtime
- 每次 `invoke()` 直接复用已装配 agent 的 MCP tools / sessions
- `stop_agent()` 或 `shutdown()` 时统一 cleanup

这样做的原因是：

- 当前 assembly 已经在加载 MCP tools，方向上更接近 agent-scoped
- 可以避免每次 run 重启 MCP server
- owner 明确，cleanup 位置清晰
- 更适合构建 warm runtime

### 5.3 sandbox 由 manager 管理，但默认不是 agent 共享单实例

sandbox 也应由 `AgentManager` 管理，但默认不建议与 agent 绑定为一个共享实例。

推荐模型是：

- `assemble_agent()` 时初始化 sandbox strategy / factory / pool
- `ManagedAgent` 持有 sandbox pool
- `invoke()` 时按 run 获取 sandbox lease / instance
- run 结束后释放 lease
- `stop_agent()` 时销毁该 agent 对应的 sandbox pool 和 warm instances

这意味着 sandbox 是：

- **owner 在 agent 层**
- **具体实例使用在 run 层**

这是本设计推荐的默认模型。

## 6. 为什么 MCP 和 sandbox 不完全对称

MCP 与 sandbox 都是 runtime 资源，但它们的共享语义不同。

### 6.1 MCP 更适合 agent 级复用

MCP session 的价值在于：

- 避免重复启动 server
- 复用连接和工具元数据
- 降低装配后首次调用延迟

因此更适合跟 assembled agent 生命周期对齐。

### 6.2 sandbox 更适合 run 级租用

sandbox 如果默认作为 agent 单例，会带来以下问题：

- 多次 run 共享文件系统状态
- 并发 run 相互污染
- cancel / retry 后副作用难以推断
- 很难保证不同 launch mode 的隔离性一致

因此默认应该是“agent 级 owner + run 级 lease”，而不是“agent 级共享单实例”。

## 7. 建议的运行时分层

建议把 runtime 资源分为三层：

### 7.1 `AgentSpec` 层

纯声明，不持有 live 资源。

包含：

- `sandbox_spec`
- `mcp_configs`
- prompt / memory / tools / subagents

### 7.2 `ManagedAgent` / `AssembledAgent` 层

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
- cancel token
- hitl handler
- run stats

## 8. 建议的数据结构调整

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

## 9. 生命周期设计

### 9.1 `define_agent(spec)`

行为：

- 持久化 spec
- 创建或更新 `ManagedAgent`
- 不创建 live runtime 资源

结束状态：

- `DEFINED`

### 9.2 `assemble_agent(name)`

行为：

1. 读取 `ManagedAgent.spec`
2. 构建 graph / template
3. 初始化 `mcp_runtime`
4. 初始化 `sandbox_runtime`
5. 将 runtime 资源挂到 `ManagedAgent`

结束状态：

- `ASSEMBLED`

### 9.3 `invoke(name, run_config)`

行为：

1. 若未装配，则先 `assemble_agent()`
2. 从 `sandbox_runtime.pool` 获取 sandbox lease
3. 使用 assembled graph 执行 run
4. MCP 直接复用 `ManagedAgent.mcp_runtime`
5. run 结束后释放 sandbox lease

状态变化：

- `ASSEMBLED -> RUNNING`
- 当 `active_run_count` 回到 `0` 时，恢复为 `ASSEMBLED`

### 9.4 `stop_agent(name)`

行为：

1. 拒绝新的 run 进入
2. 处理 active runs
3. cleanup `mcp_runtime`
4. shutdown `sandbox_runtime`
5. 清空 `template`

结束状态：

- `STOPPED`

### 9.5 `shutdown()`

行为：

- 遍历所有 `ManagedAgent`
- 统一关闭 assembled 级 runtime 资源
- 关闭 checkpointer

## 10. 并发语义

### 10.1 MCP

默认假设同一个 assembled agent 的 MCP runtime 可被多个 run 复用。

如果后续验证发现某些 MCP provider 不支持并发共享，则扩展方案为：

- 保留 agent 级 `MCPRuntimeFactory`
- run 从 factory 中借用 session

但默认不做 per-run MCP client 重建。

### 10.2 sandbox

默认支持并发 run，但每个 run 获取各自的 sandbox lease。

不默认允许多个 run 共享同一个 concrete sandbox 实例。

## 11. 与当前实现的收敛方向

### 11.1 先做的事

建议优先顺序：

1. 删除或下线 `AgentRun._start_mcp_client()` 这条 placeholder 路径
2. 让 `assemble_agent()` 真正持有 `MCPSessionManager`
3. 在 `ManagedAgent` 上挂 `mcp_runtime` / `sandbox_runtime`
4. 调整 `invoke()` 结束后的状态回落逻辑
5. 新增 `stop_agent()`，先做 manager 内部 API，再考虑 gRPC 暴露

### 11.2 必须先解决的前置问题

sandbox 生命周期要真正生效，必须先解决 graph backend 注入问题。

只要 graph 仍在 assembly 阶段绑定固定 `LocalShellBackend`，sandbox runtime 的生命周期设计就无法真实作用到工具执行。

因此，sandbox 部分的落地前提是：

- graph 的 backend 能在 assembled agent 层或 run 层正确注入
- 或 graph 能消费 manager 提供的 backend router / sandbox adapter

## 12. `stop_agent()` 的语义建议

虽然 gRPC 层暂未支持 stop，但 manager 层可以先定义该能力。

建议语义如下：

- `stop_agent()` 是显式释放 assembled 级资源的操作
- 它不是“取消当前 run”的别名
- 它释放的是：
  - `mcp_runtime`
  - `sandbox_runtime`
  - `template`
- 它保留的是：
  - `spec`
  - registry 中的 agent 定义

后续若需要 gRPC 支持，可以再增加显式的 runtime 管理 RPC。

## 13. 结论

本设计的核心结论是：

- `AgentManager` 是 MCP 和 sandbox 的唯一 owner
- MCP 默认采用 **assembled agent scoped** 生命周期
- sandbox 默认采用 **agent-scoped owner + run-scoped lease** 生命周期
- `AgentRun` 不再持有跨调用的 live 资源，只持有单次调用上下文
- `stop_agent()` 负责释放 assembled 级 runtime 资源，并为未来的 gRPC 管理接口预留语义

这套模型兼顾了 owner 清晰、资源复用、执行隔离和后续扩展性，是当前 runtime 进入 Phase 4 的推荐方向。
