# Runtime AgentManager 并发模型设计

> 状态：Draft
> 最后更新：2026-03-19
> 范围：Phase 4

## 1. 背景

当前 data plane 已经具备 `SyncAgentSpec`、`Assemble`、`Run`、`RemoveResource` 等核心路径，`AgentManager` 也已经成为 gRPC 入口后的统一执行内核。

但从并发语义上看，当前实现仍然偏“单线程思维”：

- gRPC server 以单例 `AgentManager` 同时服务 `AgentExecutorServicer` 和 `ResourceSyncServicer`
- `_agents`、`_active_runs`、`active_run_count` 等共享状态没有明确的并发保护
- `define / assemble / unload / remove / invoke / shutdown` 之间缺少一致的互斥边界
- checkpoint 当前只以 `thread_id` 作为主要隔离键，未显式引入 agent 级 namespace

这会导致 data plane 在多请求并发下出现资源释放、运行可见性和 checkpoint 覆盖风险。

## 2. 设计目标

本设计希望解决以下问题：

- 明确哪些操作需要按同名 agent 串行，哪些操作可以并发
- 保证 run admission 和 run finalize 在 manager 中始终可见，消除“活跃 run 不可见窗口”
- 明确 `thread_id` 的并发语义与 checkpoint 隔离边界
- 让 `shutdown()`、`define_agent()`、`assemble_agent()`、`invoke()`、`remove_agent()` 在同一套并发规则下工作
- 用一期可落地的简单模型先保证正确性，不提前引入复杂 RWLock 或任务调度器

## 3. 非目标

本设计暂不处理以下事项：

- control plane 的 registry CRUD 或打包流程
- `AgentSpec` 字段层面的增量更新协议
- checkpoint schema 重构或历史数据迁移
- 分布式多实例 data plane 之间的协调
- K8s / Docker 等不同 sandbox backend 的并发实现细节

## 4. 当前实现中的并发风险

### 4.1 `AgentManager` 是单例共享入口

gRPC server 启动时只创建一个 `AgentManager` 实例，并分别注入两个 servicer。  
因此，所有 `Run`、`SyncAgentSpec`、`Assemble`、`RemoveResource` 请求都会并发访问同一个 manager。

参考：

- `libs/runtime/deepagents-runtime/deepagents_runtime/entry/server.py:344`
- `libs/runtime/deepagents-runtime/deepagents_runtime/entry/server.py:348`
- `libs/runtime/deepagents-runtime/deepagents_runtime/entry/server.py:349`

### 4.2 `invoke()` 存在活跃 run 不可见窗口

当前 `invoke()` 的关键顺序是：

1. 构造 `AgentRun`
2. `await agent_run.setup(...)`
3. 把 run 放进 `_active_runs`
4. `managed.active_run_count += 1`

这意味着在第 2 步和第 3 步之间，run 可能已经占用了 sandbox 等资源，但 manager 仍然认为“没有活跃 run”。  
此时如果并发进入 `remove_agent()` 或 `unload_agent()`，就可能误判并释放 runtime 资源。

参考：

- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:232`
- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:243`
- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:245`
- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:246`

### 4.3 lifecycle mutation 是典型的 check-then-act 竞态

`define_agent()`、`unload_agent()`、`remove_agent()` 都先读取 `active_run_count`，随后再跨 `await` 执行 registry 写入或 runtime 释放。  
如果中途有新的 run 插入，就会出现“检查时安全，执行时已不安全”的竞态。

参考：

- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:124`
- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:178`
- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:196`

### 4.4 `_get_managed()` 不是原子创建

首次并发访问同名 agent 时，`_get_managed()` 可能从 registry 读取两次并各自创建 `ManagedAgent`，后写覆盖前写。  
这虽然不一定每次都表现为明显错误，但它说明当前 `_agents` 槽位并不具备并发初始化语义。

参考：

- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:343`

### 4.5 `assemble_agent()` 没有 single-flight 保护

当前同名 agent 可以并发进入 `assemble_agent()`。  
这会带来两个问题：

- 同一个 spec 被并发 compile，多次创建 MCP runtime / sandbox runtime
- 后一个 compile 覆盖前一个结果，前一个 runtime 资源可能泄漏

参考：

- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:149`

### 4.6 `thread_id` 当前是 manager 级冲突键

当前 manager 在 `setup()` 时创建单个全局 checkpointer，`invoke()` 传给 graph 的 config 只有 `thread_id`。  
这意味着 checkpoint state 的隔离边界当前不是 `(agent_name, thread_id)`，而更接近 manager 全局下的 `thread_id`。

因此，即使是不同 agent，只要复用了相同 `thread_id`，仍然可能读写同一份 checkpoint state。

参考：

- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:67`
- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:151`
- `libs/runtime/deepagents-runtime/deepagents_runtime/manager/manager.py:234`
- `libs/runtime/deepagents-runtime/deepagents_runtime/sessions.py:169`

## 5. 核心判断

### 5.1 不需要把同名 agent 的所有 run 串行

LangGraph 的 compiled graph 实例本身支持并发 `invoke / ainvoke / astream`。  
因此，“同一个 agent 只能同时跑一个 run”并不是 LangGraph 的技术约束，也不是当前 data plane 必须接受的设计前提。

这意味着：

- 同一个 compiled agent 可以支持多个 run 并发执行
- 并发控制的重点不在 graph 实例，而在 manager 内部共享资源和 checkpoint key

### 5.2 需要串行的是同名 agent 的 lifecycle mutation

真正需要互斥的，是会改变 agent runtime 结构的操作：

- `define_agent()`
- `assemble_agent()`
- `unload_agent()`
- `remove_agent()`

这些操作会替换 spec、创建或释放 MCP runtime、创建或释放 sandbox runtime、修改 agent 状态。  
因此它们必须在同名 agent 维度串行。

### 5.3 run admission / finalize 必须是原子的 manager 语义

只要 manager 决定“这个 run 已经开始”，它就必须立刻对：

- `remove_agent()`
- `unload_agent()`
- `define_agent()`
- `shutdown()`

变得可见。

也就是说，“starting run” 也属于 active run，不应等到 sandbox setup 完成后才算。

### 5.4 一期先接受 `thread_id` 的全局单飞语义

在当前共享 checkpointer 的前提下，如果不引入 agent namespace，那么相同 `thread_id` 的并发运行必须至少在 manager 范围内禁止。  
否则 checkpoint state 会互相覆盖。

因此一期的务实选择应为：

- 先把 `thread_id` 视为 manager 全局冲突键
- 后续二期再演进为 `(agent_name, thread_id)` 或显式 checkpoint namespace

## 6. 一期并发模型

### 6.1 总体原则

一期采用“全局轻锁 + 每 agent 局部锁”的简单模型：

- 不引入全局大串行
- 不引入读写锁
- 不引入复杂 actor 模型
- 先保证语义正确，再考虑进一步优化吞吐

### 6.2 manager 级状态

`AgentManager` 增加以下 manager 级状态：

- `_manager_lock`：保护 `_agents` 槽位表、全局 thread 索引、manager closing 状态
- `_closing`：标记 manager 是否正在 shutdown，阻止新请求进入
- `_agent_slots`：按 agent name 管理 slot，而不是直接把 `ManagedAgent` 暴露为唯一并发单元
- `_thread_index`：记录当前 inflight 的 `thread_id`

说明：

- `_manager_lock` 不负责串行所有业务操作
- 它只保护 manager 级索引和 gate
- 一旦拿到具体 agent slot，后续大部分操作应尽量在 slot lock 内完成

### 6.3 agent slot

建议为每个 agent 引入独立的 slot 概念：

```python
@dataclass
class AgentSlot:
    name: str
    lock: asyncio.Lock
    managed: ManagedAgent | None
    inflight_runs: dict[str, AgentRun]
```

一期不需要额外引入复杂状态机。  
只要这个 slot 能承担以下责任即可：

- 串行同名 agent 的 lifecycle mutation
- 保存该 agent 当前的 inflight runs
- 作为 run admission / finalize 的原子边界

### 6.4 source of truth

一期明确以下约束：

- `slot.inflight_runs` 或其计数是“是否存在活跃 run”的权威来源
- `managed.active_run_count` 是对外状态字段和统计字段，不应单独作为并发判断依据
- manager 级 `_active_runs` 只作为按 `run_id` 查找的辅助索引，不再承担生命周期判断职责

这可以避免“一个地方改了，另一个地方还没改”的松散一致性问题。

## 7. 各操作的并发语义

### 7.1 `define_agent(spec)`

语义：

- 同名 agent 串行
- 如果该 agent 存在 inflight runs，则直接失败
- 不等待 run 自然结束
- 在持有 slot lock 的前提下替换 spec，并释放旧 runtime

说明：

- `define_agent()` 属于 lifecycle mutation，不应与 `invoke()` 并发穿插修改同一个 agent 的 runtime
- 一期采用 fail-fast，比“等待所有 run 结束后再重定义”更简单且更清晰

### 7.2 `assemble_agent(name)`

语义：

- 同名 agent 串行 single-flight
- 如果 agent 已有 live runtime，则直接返回现有 template
- 如果 agent 当前有 inflight runs，则允许复用已有 runtime，但不允许在无协调的情况下重建 runtime

建议：

- compile 过程整体放在 slot lock 保护下完成
- 一期先接受“同名 agent compile 串行且会暂时阻塞该 agent 的新 run admission”

这是一个可以接受的吞吐权衡，因为 compile 本身不是高频路径。

### 7.3 `invoke(name, run_config)`

语义：

1. 获取 agent slot
2. 如无 compiled runtime，则通过同一 slot 上的 assemble 路径补齐
3. 在第一个 `await` 之前完成 run reservation：
   - 确定 `run_id`
   - 确定 `thread_id`
   - 注册到 slot 的 inflight runs
   - 注册到 manager 级 `_active_runs`
   - 递增 `managed.active_run_count`
   - 注册到 `_thread_index`
   - 将 agent 状态标为 `RUNNING`
4. 释放锁后再执行 `agent_run.setup()` 和 graph run
5. 无论成功、取消还是失败，都进入统一 finalize 路径回收状态

关键点：

- reservation 必须发生在第一个 `await` 之前
- finalize 必须幂等
- 如果 `setup()` 失败，也要走 finalize 清理 reservation

### 7.4 `unload_agent(name)`

语义：

- 同名 agent 串行
- 如果存在 inflight runs，则直接失败
- 仅释放 compiled runtime，保留 installed spec

这里的判断必须基于 slot 内 inflight runs，而不是只看 `active_run_count`。

### 7.5 `remove_agent(name)`

语义：

- 同名 agent 串行
- 如果存在 inflight runs，则直接失败
- 释放 runtime 并删除 registry 中的 agent spec
- 从 manager 索引中移除该 slot 或清空 slot 内的 `managed`

说明：

- `remove` 是 uninstall 语义
- 它不应该与 run cancel 混淆
- 它也不应该在有 inflight runs 时隐式强制回收资源

### 7.6 `shutdown()`

语义：

- 先在 manager 级将 `_closing` 置为 `True`
- 从这一刻起拒绝新的 `define / assemble / invoke / unload / remove`
- 然后遍历各 agent slot，清理 active runs 和 compiled runtime
- 最后关闭 sandbox pool 和 checkpointer

关键点：

- `shutdown()` 必须首先建立 gate，而不是一边清理一边允许新请求进入
- 否则会出现“正在 shutdown 时又创建新 run”的竞态

## 8. `thread_id` 与 checkpoint 隔离策略

### 8.1 一期策略：全局单飞

在不修改 checkpoint namespace 的前提下，一期定义为：

- 同一 manager 内，相同 `thread_id` 不允许并发运行
- 冲突时直接返回错误，而不是排队等待

返回错误的好处是语义更清晰：

- client 立刻知道该 thread 已经被占用
- manager 不需要引入额外排队和唤醒机制
- 更符合当前 runtime 的简单模型

### 8.2 二期策略：agent-scoped checkpoint namespace

更合理的长期方案是把 checkpoint key 扩展为 agent 级命名空间，例如：

- `(agent_name, thread_id)`
- 或在 `configurable` 中注入独立的 checkpoint namespace 字段

完成后可以把 thread 单飞边界从 manager 全局收缩为：

- 同一 agent 内的相同 `thread_id` 不并发
- 不同 agent 即使 thread_id 相同，也不会互相覆盖

本设计建议将该项列为二期演进，不阻塞一期并发模型落地。

## 9. 锁顺序与死锁规约

一期必须明确固定锁顺序：

1. 先拿 `_manager_lock`
2. 再拿某个 agent 的 `slot.lock`

禁止：

- 先拿 slot lock 再回头拿 `_manager_lock`
- 同时持有两个不同 agent 的 slot lock

这样可以把死锁规约降到最简单的级别。

## 10. 建议的数据结构调整

一期不要求大改 public 数据模型，但建议在 manager 内部做以下收敛：

- `_agents: dict[str, ManagedAgent]` 逐步演进为 `_agent_slots: dict[str, AgentSlot]`
- `_active_runs: dict[str, AgentRun]` 保留，但仅作为 `run_id -> AgentRun` 辅助索引
- `ManagedAgent.active_run_count` 继续保留，但统一由 slot 内 inflight runs 派生更新

如果希望最小代码改动，也可以保留 `_agents` 命名，只是在内部让 value 从 `ManagedAgent` 换成 slot 包装对象。

## 11. 一期落地顺序

建议按以下顺序实现：

1. 为 manager 增加 `_closing`、`_manager_lock`、agent slot、`_thread_index`
2. 改造 `_get_managed()` 为“获取或创建 slot，再读取/填充 managed”
3. 改造 `invoke()`，先做 reservation，再做 `agent_run.setup()`
4. 改造 `define_agent()`、`assemble_agent()`、`unload_agent()`、`remove_agent()`，统一走 slot lock
5. 改造 `shutdown()`，先建立 closing gate，再执行清理
6. 最后补充并发单测和 thread 冲突测试

## 12. 需要配套验证的测试场景

一期建议至少覆盖以下测试：

- 同一 agent 并发两次 `assemble`，只生成一份有效 runtime
- `invoke()` 与 `remove_agent()` 并发，remove 必须因 inflight run 被拒绝
- `invoke()` 在 sandbox setup 失败后能正确回滚 reservation
- 同一 agent 并发多个不同 `thread_id` 的 run 可以成功
- 同一 manager 内相同 `thread_id` 的并发 run 被拒绝
- `shutdown()` 开始后，新 `invoke()` 被拒绝

## 13. 结论

本设计的一期结论如下：

- 不需要把同名 agent 的所有 `Run` 串行
- 必须串行的是同名 agent 的 lifecycle mutation
- `invoke()` 的 run reservation 必须在第一个 `await` 之前完成
- 活跃 run 的权威状态应位于 agent slot，而不是松散分布在 `_active_runs` 和 `active_run_count`
- 在当前共享 checkpointer 的前提下，`thread_id` 一期应按 manager 全局单飞处理
- `shutdown()` 必须先建立 closing gate，再执行资源清理

这套模型优先保证正确性和资源边界清晰，足以支撑当前 data plane 进入可维护、可继续演进的并发阶段。
