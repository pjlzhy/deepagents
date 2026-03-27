# Runtime HITL Transport Hardening Design

> 状态：Draft
> 最后更新：2026-03-27
> 范围：`runtime.proto` Phase 1

## 1. 背景

`runtime.proto` 事件协议的审查已经确认一件事：

- 当前 approve / reject 主路径可用
- 但 `HITLDecision.interrupt_id` 的语义在文档层强于实现层

当前 runtime gRPC server 的实际行为是：

1. client 发来的 `HITLDecision` 被放入一个全局 FIFO queue
2. 正在等待的 `hitl_handler()` 直接 `queue.get()`
3. server 不校验该 decision 是否对应当前 interrupt

因此，当前 transport 层更接近“按到达顺序消费 decision”，而不是“按 `interrupt_id` 路由 decision”。

这会导致两个直接问题：

- 错误或迟到的 decision 可能被错误消费
- `runtime.proto` 对 `interrupt_id` 的契约没有被真正兑现

本设计用于收敛 **Phase 1：先补 transport 边界校验**，不处理正式协议重构。

## 2. 设计目标

本阶段只解决一个问题：

- 让现有 `runtime.proto` 的 HITL transport 语义和实现重新一致

具体目标如下：

- 在不改 proto 形状的前提下，严格校验 `interrupt_id`
- 在单次 `Run` 流内显式维护 pending HITL interrupt 状态
- 校验 decision 数量与该 interrupt 的 action 数量一致
- 避免错误 decision 被 FIFO 误消费
- 对无效 HITL 控制消息尽早失败，而不是把错误下沉到 graph 执行层

## 3. 非目标

本设计明确不做以下事项：

- 不修改 `runtime.proto` 的字段结构
- 不引入 `edit` 的正式 transport 能力
- 不收敛 `ActionRequest.description` / `review_configs` / `edited_action`
- 不修改 control-web 的审批交互形态
- 不一次性重构 control / runtime / web 全链路 HITL 协议

换句话说，这一阶段只做 **hardening**，不做 **protocol redesign**。

## 4. 当前问题拆解

### 4.1 `interrupt_id` 目前没有被真正使用

当前 server 只读取 `HITLDecision`，但不会：

- 校验 `interrupt_id` 是否存在
- 校验 `interrupt_id` 是否属于当前 run
- 校验该 interrupt 当前是否还处于 pending 状态

这意味着 proto 中最关键的关联字段，在 transport 行为里事实上是“摆设”。

### 4.2 decision 数量没有在 transport 层校验

底层 LangChain middleware 会在恢复阶段校验 decision 数量是否和 hanging tool call 数量一致，但这个校验发生得太晚。

transport 层已经知道：

- 当前 interrupt 的 `action_requests` 数量
- client 发回来的 `decisions` 数量

因此这个约束应在 transport 层先收紧，而不是把错误留到 graph 恢复时再抛出。

### 4.3 错误控制消息的失败位置不合理

当前一旦 client 发来错误的 HITL 决策，失败位置通常会非常靠后：

- 要么被错误 interrupt 消费
- 要么直到 graph resume 才暴露为 runtime error

这会让 northbound 很难区分：

- 是 transport 输入错了
- 还是 agent 运行本身出错了

本阶段的目标之一，就是让这两类错误在运行面上分开。

## 5. 设计方案

### 5.1 引入 run-scoped HITL coordinator

在 `AgentExecutorServicer.Run()` 内引入一个 run-scoped 的 HITL 协调器，生命周期与单次 gRPC `Run` 流一致。

该对象负责：

- 注册 pending interrupt
- 为每个 interrupt 单独等待 decision
- 校验 decision 合法性
- 标记 interrupt 已完成 / 已关闭

它不需要成为独立模块对外暴露，但语义上应是单独的 owner，而不是散落在 queue 和闭包里。

### 5.2 run 内维护显式的 pending interrupt 表

server 在转发 `HITL_REQUEST` 事件前，应先从事件中提取：

- `interrupt_id`
- `action_requests`
- `expected_decision_count`

并在当前 run 的 pending 表中注册一条记录，例如：

```text
pending_interrupts[interrupt_id] = {
  expected_decision_count,
  status: pending,
  waiter: future/queue
}
```

关键约束：

- 同一个 `interrupt_id` 在单次 run 内只能注册一次
- 一旦该 interrupt 被成功消费 decision，就必须转为 resolved
- resolved interrupt 不可再次提交 decision

### 5.3 HITLDecision 必须按 `interrupt_id` 路由，而不是按 FIFO 消费

当前全局 FIFO queue 的行为需要改成：

- reader task 收到 `HITLDecision`
- 先读取其中的 `interrupt_id`
- 在 pending 表中找到目标 interrupt
- 将该 decision 投递给对应 interrupt 的 waiter

而不是：

- 谁先在等，就给谁

这一步是本阶段最核心的行为收敛。

### 5.4 进入 waiter 之前先做 transport 校验

server 在接收 `HITLDecision` 后，先做以下校验：

1. `interrupt_id` 不能为空
2. `interrupt_id` 必须存在于当前 run 的 pending 表
3. `interrupt_id` 对应状态必须是 `pending`
4. `len(decisions)` 必须等于该 interrupt 的 `expected_decision_count`

本阶段不做的校验：

- 不校验 `tool_call_id`
- 不校验 approve / reject 之外的正式 decision 结构
- 不校验 `reason` 的具体内容

原因很简单：当前 transport 仍然是兼容模型，校验应与当前协议能力边界一致，不应提前引入下一阶段模型。

### 5.5 错误语义：无效 HITL 控制消息应转为 terminal runtime error

本阶段建议的失败语义是：

- 如果 client 发来无效的 `HITLDecision`
- 当前 run 立即结束
- server 向上游发出 terminal `error` 事件

建议错误类型使用新的 transport 级分类，例如：

- `invalid_hitl_decision`

错误信息应尽量明确，例如：

- `unknown interrupt_id: xxx`
- `interrupt_id xxx is no longer pending`
- `decision count mismatch for interrupt xxx: expected N, got M`

这样 northbound 可以明确知道：

- 这是控制消息错误
- 不是 agent 执行本身失败

### 5.6 命中成功后再恢复 graph

当某个 interrupt 的 decision 校验通过后：

- waiter 才返回给 `hitl_handler()`
- `hitl_handler()` 再执行现有兼容翻译逻辑
- 之后恢复 graph

也就是说：

- `校验 -> 路由 -> 交付 -> 翻译 -> resume`

而不是：

- `先交给 graph，再看会不会炸`

## 6. 分层职责

### 6.1 runtime 层职责

runtime 是 Phase 1 的唯一语义 owner。

runtime 需要负责：

- pending interrupt 注册
- interrupt_id / count 校验
- decision 定向投递
- transport 错误收口

这是因为只有 runtime 同时拥有：

- 当前 run 上下文
- 当前 interrupt 集合
- 当前 graph resume 时机

### 6.2 control 层职责

control 层本阶段不做协议重构，只做配合：

- 继续透传 northbound HITL decision
- 保留 `interrupt_id` 必填
- 保持 `tool_call_id` 为可选
- 在收到 runtime terminal `error` 事件时，如实向 northbound 暴露

control 本阶段不应自作主张引入新的 decision 模型。

### 6.3 web 层职责

web 层本阶段也不做协议升级。

web 只需要继续：

- 提交当前 UI 已有的 approve / reject decisions
- 正确携带 `interrupt_id`
- 在收到 terminal `error` 时展示明确提示

如果 runtime 返回 `invalid_hitl_decision`，前端只需要把它当成一次运行失败显示出来，不需要额外协议分叉。

## 7. 状态机收敛

本阶段建议把单个 interrupt 的 transport 生命周期明确成：

```text
registered -> pending -> resolved
                  |
                  -> failed
```

含义如下：

- `registered`：runtime 已看到 `HITL_REQUEST`，但尚未对外完成挂起登记
- `pending`：对外已发布，等待 client 提交 decision
- `resolved`：已收到并校验通过，decision 已交付给 waiter
- `failed`：收到无效 decision，run 终止

注意：

- `failed` 是 run 级失败，不是 interrupt 自己静默丢弃
- 本阶段不支持“忽略错误 decision，等待下一次重发”

原因是当前 northbound 没有设计良好的 retry / ack 机制，静默继续等待会让状态更难理解。

## 8. 兼容性策略

本阶段必须保持以下兼容性：

- `runtime.proto` 不变
- control HTTP contract 不变
- control-web 请求体不变
- approve / reject 主路径行为保持不变

因此，兼容性边界是：

- 合法输入继续通过
- 非法输入更早失败

这属于行为收紧，不属于 northbound 破坏性变更。

## 9. 测试建议

本阶段最少应补以下测试：

### 9.1 runtime 单元测试

- 合法 `interrupt_id` + 正确 decision count 可以正常恢复
- 未知 `interrupt_id` 会生成 terminal `error`
- 已 resolved interrupt 再次提交 decision 会生成 terminal `error`
- decision 数量不匹配会生成 terminal `error`

### 9.2 runtime gRPC server 单元测试

- reader task 能按 `interrupt_id` 将 decision 路由到正确 waiter
- 不再依赖 FIFO queue 顺序命中

### 9.3 control 集成测试

- runtime 返回 `invalid_hitl_decision` 时，control 能如实透传 `error` 事件

这里不要求 web 端新增测试矩阵，因为 northbound 契约本阶段不变。

## 10. 落地顺序

建议按以下顺序落地：

1. 在 runtime server 内抽出 run-scoped HITL coordinator 语义
2. 在发送 `HITL_REQUEST` 事件前注册 pending interrupt
3. 将 `HITLDecision` 从 FIFO 消费改为按 `interrupt_id` 路由
4. 在 reader task 中补齐 count / state 校验
5. 将无效 decision 统一收口为 terminal `error`
6. 回填 runtime / control 相关测试

这个顺序的好处是：

- 改动集中在 runtime server
- 不需要先改 proto
- control / web 几乎不需要联动修改

## 11. 后续衔接

本阶段完成后，协议会达到一个更健康的中间状态：

- 现有 `runtime.proto` 契约终于被真正兑现
- approve / reject 主路径更稳
- 下一阶段正式重构 HITL proto 时，迁移面会更清晰

Phase 1 完成后，下一阶段再进入：

- `description`
- `review_configs`
- `Decision.type`
- `edit / edited_action`

等正式协议收敛，而不是把这些问题继续叠加在未加固的 transport 边界上。

## 12. 当前结论

Phase 1 不应被理解为“修一个小 bug”，而应被理解为：

- 给当前 HITL transport 补上最基本的协议执行力

在当前实现基础上，这是成本最低、收益最高、也最不容易引发大面积联调回归的一步。
