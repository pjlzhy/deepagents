# Telemetry Run 历史页与 Chat 收敛实施方案

> 状态：Draft
> 最后更新：2026-04-09
> 依赖文档：`docs/design/runtime-agent-telemetry-design.md`、`docs/design/runtime-session-query-design.md`、`docs/design/control-ui-implementation-plan.md`
> 目标：将 `telemetry run` 收敛为唯一的 run 模型，补齐历史 run 与 session snapshot 的稳定关联，并按可回滚的顺序将 `chat` 页面收敛到 telemetry 主链

## 1. 背景

当前 control UI 中，`chat` 页面和 `telemetry` 页面仍在消费两条不同的执行入口：

- `chat` 页面走 `Run` 交互流
- `telemetry` 页面走 `RunTelemetry` 结构化流

随着 `telemetry run` 已经覆盖 `Run` 的主要产品能力，继续维护两条 run 主链会带来以下问题：

- 执行模型重复，前后端需要维护两套 northbound stream 语义
- `chat` 与 `telemetry` 之间无法稳定共享 `run_id`
- telemetry history 目前只能看 trace，不能稳定查看“该次 run 对 thread 造成的状态变化”
- session history 目前只能按 `agent_name + thread_id (+ checkpoint_id)` 查询，无法直接从 `run_id` 精确回到某次历史 turn

因此，本轮设计目标不是继续补一套独立的 telemetry 调试页，而是把 telemetry 升级为唯一的 run 模型，并让 chat 与 telemetry 成为同一底层数据的两种视图。

## 2. 模型收敛

本轮设计采用如下统一类比：

- `thread / session` = 一条持续演进的分支
- `session query` = 查询该分支在某个 checkpoint 上的状态快照
- `checkpoint` = 一次可恢复的状态快照
- `telemetry run` = 该分支上的一次 turn 执行
- `telemetry stream events` = 该次 turn 的执行过程日志

这个类比有一个重要约束：

- `stream event` 不是权威状态源
- `session query` 才是 thread 状态的权威读取面

因此：

- `telemetry` 负责回答“这次 run 是怎么执行的”
- `session query` 负责回答“这个 thread 在某个 checkpoint 上到底长什么样”

历史页面要稳定关联两者，必须显式建立：

- `run_id -> thread_id`
- `run_id -> start_checkpoint_id`
- `run_id -> end_checkpoint_id`

## 3. 设计原则

### 3.1 `telemetry run` 是唯一 run 模型

后续所有 run 入口都应统一到 `RunTelemetry`：

- `chat` 页面不再维护独立的旧 `Run` 执行链路
- `telemetry` 页面继续消费同一条 canonical telemetry 流
- `run_id` 成为 chat、trace、history、audit 的统一锚点

### 3.2 历史状态必须通过 checkpoint snapshot 读取

历史 telemetry 页面不应通过重放 `TelemetryEvent` 来拼装历史消息。

原因：

- session history 的真实来源是 runtime checkpoint
- session message 展示存在归一化逻辑，例如 `AIMessage.tool_calls` 与 `ToolMessage` 的折叠
- event replay 得到的是近似态，不应替代快照查询

因此，历史 telemetry 页面应通过 `run` 上记录的 checkpoint 指针回到 session query。

### 3.3 历史 telemetry 页面应收敛为 run detail 页面

live telemetry 页面和历史 telemetry 页面不应继续共用“临时 stream console”模型。

历史页面的权威结构应为：

- `Run Summary`
- `Trace`
- `Session Snapshot`
- `Diff`

这更接近 `git show <commit>`，而不是“回放一次旧 SSE 会话”。

### 3.4 Chat 与 Telemetry 是同源双视图

收敛后：

- `chat` 页面负责 thread 当前状态与用户交互
- `telemetry` 页面负责 run 级排障和执行审计

两者共享：

- 同一个 `run_id`
- 同一个 `thread_id`
- 同一个 `checkpoint` 底座

## 4. 当前缺口

当前实现已经具备以下基础能力：

- `TelemetryRun` 已持久化 `run_id / agent_name / thread_id / status`
- `TelemetryEvent` 已持久化结构化 stream event
- session query 已支持 `agent_name + thread_id + checkpoint_id`
- telemetry UI 已能展示 live trace / graph / debug

当前仍缺以下关键能力：

- `TelemetryRun` 未持久化 `start_checkpoint_id / end_checkpoint_id`
- telemetry 历史页没有稳定的 run detail 路由
- telemetry 历史页不能直接查看 `Before Run / After Run` snapshot
- chat 页面仍未走 telemetry run
- chat 历史消息 DTO 未包含可稳定关联 `run_id` 的 turn 级索引

## 5. 目标能力

完成本方案后，应满足以下产品能力：

### 5.1 历史 telemetry run 可稳定回看

用户打开任意历史 run，应能看到：

- 该次 run 的基本信息
- 该次 run 的 trace / graph / event
- 该次 run 开始前后的 session snapshot

### 5.2 chat 页面直接跳转到本轮 trace

用户在 chat 中发起一次新 turn 后，应能直接从该 turn 跳到其对应的 telemetry run detail 页面。

### 5.3 chat 历史 turn 可回溯到历史 run

在后续阶段，用户刷新页面后仍应能从 thread 中的历史 turn 反查其对应的 `run_id`，并打开对应 trace。

## 6. 数据模型调整

### 6.1 `telemetry_runs`

phase 1 增加以下字段：

- `start_checkpoint_id`
- `end_checkpoint_id`

phase 3 再增加：

- `turn_index`

字段语义：

- `start_checkpoint_id`：本次 run 开始前 thread 所在的 checkpoint
- `end_checkpoint_id`：本次 run 结束后 thread 落到的 checkpoint
- `turn_index`：同一 `(agent_name, thread_id)` 下第几次 turn，用于 chat 历史 turn 和 run 做稳定关联

### 6.2 Snapshot Facade

为避免前端自己拼接 session query，control 应新增 run 级 snapshot facade：

- `GET /api/v1/telemetry/runs/:run_id/snapshot?position=before`
- `GET /api/v1/telemetry/runs/:run_id/snapshot?position=after`

control 内部流程：

1. 读取 `TelemetryRun`
2. 根据 `position` 选择 `start_checkpoint_id` 或 `end_checkpoint_id`
3. 调用 session query：
   - `agent_name`
   - `thread_id`
   - `checkpoint_id`
4. 返回标准 session message page DTO

### 6.3 Thread-scoped Run History

为支持历史 chat turn 的 run 关联，control 的 telemetry run list 应支持：

- `thread_id`
- `agent_name`

至少需要支持：

- `GET /api/v1/telemetry/runs?thread_id=...`

这条接口后续可作为 thread run history 面板的数据源。

## 7. 分阶段实施

建议按 `PR1 -> PR2 -> PR3` 的顺序推进，每个 PR 都保持可验收和可回滚。

### 7.1 PR1：先把 Telemetry 历史页做成 Run Detail

#### 目标

先把“历史 run 可回看”打通，不改 chat 执行入口。

#### 后端改动

数据层：

- `libs/control/pkg/store/sqlite.go`
  - 为 `telemetry_runs` 增加 `start_checkpoint_id`
  - 为 `telemetry_runs` 增加 `end_checkpoint_id`
  - 增加 `thread_id` 相关索引
  - 使用已有 `ensureSQLiteColumn` 做 schema migration

domain 与 store：

- `libs/control/pkg/domain/telemetry.go`
  - `TelemetryRun` 增加 checkpoint 字段
- `libs/control/pkg/telemetry/sqlite.go`
  - 在 `RecordEvent` / `upsertRunSummary` 中解析 `checkpoint` event
  - 第一次看到的 parent checkpoint 回填 `start_checkpoint_id`
  - 最新 resolved checkpoint 回填 `end_checkpoint_id`

service 与 API：

- `libs/control/pkg/orchestrator/service.go`
  - 新增 run snapshot 查询方法
- `libs/control/pkg/api/server.go`
  - 暴露 snapshot facade 能力
- `libs/control/pkg/api/http_handler_telemetry.go`
  - 增加 `GET /telemetry/runs/:run_id/snapshot`
- `libs/control/pkg/api/http_handler.go`
  - 增加对应 DTO

建议 northbound contract：

- `GET /api/v1/telemetry/runs`
  - 支持 `thread_id`、`agent_name`
- `GET /api/v1/telemetry/runs/:run_id`
  - 返回 `start_checkpoint_id / end_checkpoint_id`
- `GET /api/v1/telemetry/runs/:run_id/steps`
- `GET /api/v1/telemetry/runs/:run_id/events`
- `GET /api/v1/telemetry/runs/:run_id/snapshot?position=before|after`

#### 前端改动

路由与链接：

- `libs/control/ui/src/app/router.tsx`
  - 新增 `/telemetry/runs/:runId`
- `libs/control/ui/src/app/links.ts`
  - 新增 run detail link builder

client 与 types：

- `libs/control/ui/src/shared/api/controlClient.ts`
  - 新增 `getTelemetryRunSnapshot`
- `libs/control/ui/src/shared/types/api.ts`
  - 补 `HTTPTelemetryRunDTO.start_checkpoint_id`
  - 补 `HTTPTelemetryRunDTO.end_checkpoint_id`

页面：

- `libs/control/ui/src/pages/telemetry/index.tsx`
  - 保留现有 `/telemetry/:agentName` 作为 live telemetry 页面
- 新增历史 run detail 页面
  - 可复用现有 trace / graph / debug 组件
  - 顶部显示 `Run Summary`
  - 右侧增加 `Session Snapshot`
  - 默认展示 `After Run`
  - 有 `start_checkpoint_id` 时展示 `Before Run`

#### 验收条件

- 任意历史 `run_id` 可打开 run detail 页面
- 页面可同时展示 trace 和 snapshot
- 对没有 checkpoint 的历史 run，trace 仍可查看，snapshot 展示 unavailable

### 7.2 PR2：把 Chat 切到 Telemetry Run

#### 目标

让所有新产生的 run 都走 telemetry 主链，但暂不处理“历史 chat turn 精确关联”。

#### 后端改动

- `libs/control/pkg/api/http_handler_runs.go`
  - 旧 `Run` northbound 标记为 deprecated
  - `chat` 页面改走 `telemetry/stream`
- 保留旧 `/runs/stream` 一段时间，避免一次性删除影响回滚

#### 前端改动

chat 页面主链：

- `libs/control/ui/src/pages/chat/index.tsx`
  - `startRun()` 从 `controlClient.runs.stream()` 切到 `streamTelemetry()`
  - 继续保留原有 `run_session` / cancel / HITL 交互

适配层：

- `libs/control/ui/src/features/chat/runtimeEventParser.ts`
  - 增加 telemetry `public_event -> chat runtime event` 的适配
  - 复用现有 chat reducer，避免重写整套 timeline 逻辑

跳转能力：

- 当前一次 chat turn 完成后，UI 保存本轮 `run_id`
- 当前 turn 增加 `View Trace`
- 点击后跳转 `/telemetry/runs/:runId`

#### 验收条件

- chat 新 run 全部走 telemetry stream
- cancel / HITL / thread switch 行为与旧 chat 一致
- 用户可从当前完成的 turn 直接打开对应 trace

### 7.3 PR3：补历史 Chat Turn 和 Run 的稳定映射

#### 目标

让用户刷新页面后，仍然能从 thread 中任意历史 turn 跳到对应 trace。

#### 后端改动

数据层：

- `libs/control/pkg/store/sqlite.go`
  - 为 `telemetry_runs` 增加 `turn_index`
- `libs/control/pkg/domain/telemetry.go`
  - `TelemetryRun` 增加 `turn_index`
- `libs/control/pkg/telemetry/sqlite.go`
  - 在 run summary 投影中维护 `(agent_name, thread_id)` 下的 `turn_index`

查询面：

- `GET /api/v1/telemetry/runs`
  - 正式支持 `thread_id` 过滤
  - 返回 `turn_index`

#### 前端改动

chat 历史关联：

- `libs/control/ui/src/pages/chat/index.tsx`
  - 在拉 `session messages` 的同时拉 `telemetry runs by thread`
- `libs/control/ui/src/features/chat/runtimeEventParser.ts`
  - 先按 human turn 做分组
  - 再按 `turn_index` 将历史 turn 与 `run_id` 关联

历史跳转：

- 每个历史 turn 都可展示 `View Trace`
- 刷新页面后仍然可用

可选增强：

- thread run history 面板
- 按 `turn_index` 展示 `a -> b -> c`
- 类似 `git log`

#### 验收条件

- 任意历史 thread 刷新后仍能把历史 turn 关联到 `run_id`
- 用户可从任意历史 turn 跳到对应 run detail

## 8. 推荐顺序

推荐严格按以下顺序推进：

1. 先做 `PR1`，优先解决“历史 run 看不全”的问题
2. 再做 `PR2`，统一所有新流量到 telemetry 主链
3. 最后做 `PR3`，补齐历史 turn 和 `run_id` 的稳定映射

这样拆分的好处是：

- 每一步都能独立上线
- 每一步都能独立验收
- 即使 `PR3` 延后，系统仍然已经完成主链统一

## 9. 风险与注意事项

### 9.1 不要用 event replay 代替 snapshot query

这是本设计最重要的约束之一。

原因：

- session history 的真实来源是 checkpoint
- event replay 容易与 session normalization 逻辑产生偏差
- “trace 可看”和“状态可查”必须分层

### 9.2 旧 `Run` 接口不要过早物理删除

建议在 `PR2` 稳定后，或 `PR3` 完成后，再删除旧 `/runs/stream`。

在 `PR2` 中直接把调用方切走即可，保留一段过渡期更利于回滚。

### 9.3 `turn_index` 的定义必须稳定

`turn_index` 应定义为：

- 同一 `(agent_name, thread_id)` 下
- 以用户发起的一次 run 为单位
- 单调递增

不要把 `assistant draft`、HITL 重试、工具调用等中间态误计为新的 turn。

## 10. 最终形态

本方案完成后，系统应收敛为如下关系：

- `chat` 页面：查看和编辑 thread 当前状态
- `telemetry run detail`：查看一次 run 的执行过程和状态变化
- `session query`：查看 thread 在任意 checkpoint 上的权威快照
- `telemetry run history`：查看 thread 的 turn 历史

对应类比：

- `thread` 像 branch
- `run` 像 commit
- `trace` 像 commit 生成过程日志
- `snapshot` 像 commit 前后 tree

这也是后续扩展 `run diff`、`artifact diff`、`workspace diff` 的自然基础。
