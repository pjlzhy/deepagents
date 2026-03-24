# Runtime Session Query 接口设计

> 状态：Final
> 最后更新：2026-03-24
> 范围：Phase 5
> 落地状态：已实现到 `runtime.proto`、`deepagents_runtime/sessions.py`、`deepagents_runtime/entry/server.py`

## 1. 背景

当前 runtime data 层已经具备基础的 session / thread 能力：

- `RunRequest.thread_id` 已经作为会话恢复主键
- data plane 已接入 SQLite checkpointer
- runtime 已能查询 thread 基础元数据
- CLI 已验证可以直接从 latest checkpoint 恢复 thread history

当前已有实现主要集中在两个地方：

- `libs/runtime/deepagents-runtime/deepagents_runtime/sessions.py`
- `libs/cli/deepagents_cli/sessions.py`
- `libs/cli/deepagents_cli/app.py`

但对外协议层目前仍缺少一组正式的 session 查询接口。现有 `ResourceSync` 更偏向 control plane 和 data plane 之间的资源同步 / 生命周期控制，不适合继续承载 session 查询语义。

本设计的目标，是在不改变当前 checkpoint 持久化模型的前提下，定义一组稳定、诚实、可落地的 session 查询接口。

## 2. 设计目标

本设计希望解决以下问题：

- 为 runtime 暴露正式的 session 查询接口
- 明确 `message_count` 的准确口径
- 明确 history message 的返回语义
- 让分页和一致性行为可预期
- 让接口可以在 agent 未 assemble 时仍然工作
- 让 session 摘要在可用时带上 owning agent 的 live runtime 状态

## 3. 非目标

本设计不处理以下事项：

- 新增独立的 session registry
- 让 control plane 接管 session CRUD
- 将 checkpoint API 扩展为完整审计日志系统
- 在本轮设计中引入 append-only transcript / event ledger
- 修改现有 `Run` 流协议

## 4. 当前现实约束

### 4.1 session 主键就是 `thread_id`

当前 runtime 中，session 的稳定主键已经是 `thread_id`：

- `RunRequest.thread_id` 用于恢复已有会话
- SQLite checkpoint 以 `thread_id` 作为查询键
- 当前 `sessions.py` 的查询函数也围绕 `thread_id` 组织

因此本设计不再引入新的 `session_id` 概念。对外可称为 session，但协议主键继续使用 `thread_id`。

### 4.2 可靠数据源是 checkpoint，而不是独立 messages 表

当前没有单独的 `messages` 表。session 查询的可靠数据源有两类：

- `checkpoints.metadata`
- latest checkpoint 的 `channel_values`

其中：

- thread 列表、agent 归属、`updated_at` 等轻量元数据可从 `checkpoints.metadata` 提取
- `message_count`、`initial_prompt`、history messages 应从 latest checkpoint 的 `channel_values.messages` 提取

### 4.3 history 语义应定义为 “resume view”

当前 checkpoint 更接近“最新可恢复状态”，而不是“完整不可变审计流水”。

这意味着：

- history messages 默认表示“下次 resume 时 agent 会看到的会话视图”
- 它可能经过 compaction / summarization
- 它不承诺保留所有历史原始消息

因此本设计不会在 v1 中承诺 full transcript，只会明确支持 `resume view`

## 5. 设计原则

### 5.1 查询接口独立于 `ResourceSync`

新增独立的 `SessionQuery` service，而不是继续向 `ResourceSync` 塞 session 接口。原因如下：

- `ResourceSync` 偏资源同步与生命周期动作
- session 查询是 runtime 本地运行态读取
- 查询接口应尽量保持无副作用

### 5.2 先做“线程索引层”，再做“线程内容层”

session 接口按两层拆分：

- 线程索引层：列表、最近会话、摘要、删除
- 线程内容层：history messages

这样可以避免所有接口都直接背负大 payload 和复杂一致性约束。

### 5.3 先定义诚实语义，再扩能力

如果当前能力只能稳定返回 latest checkpoint state，就应明确写成 `resume view`，而不是用一个模糊的 `history` 字段名称，让调用方误以为它是完整 transcript。

## 6. 协议草案

### 6.1 Service

```proto
service SessionQuery {
  rpc ListSessions(ListSessionsRequest) returns (ListSessionsResponse);
  rpc GetSession(GetSessionRequest) returns (GetSessionResponse);
  rpc GetSessionMessages(GetSessionMessagesRequest)
      returns (GetSessionMessagesResponse);
  rpc GetLatestSession(GetLatestSessionRequest)
      returns (GetLatestSessionResponse);
  rpc DeleteSession(DeleteSessionRequest) returns (DeleteSessionResponse);
}
```

### 6.2 Enums

```proto
enum SessionHistoryMode {
  SESSION_HISTORY_MODE_UNSPECIFIED = 0;
  SESSION_HISTORY_MODE_RESUME_VIEW = 1;
  SESSION_HISTORY_MODE_FULL_TRANSCRIPT = 2;
}

enum SessionMessageRole {
  SESSION_MESSAGE_ROLE_UNSPECIFIED = 0;
  SESSION_MESSAGE_ROLE_SYSTEM = 1;
  SESSION_MESSAGE_ROLE_HUMAN = 2;
  SESSION_MESSAGE_ROLE_AI = 3;
  SESSION_MESSAGE_ROLE_TOOL = 4;
}

enum AgentRuntimeStatus {
  AGENT_RUNTIME_STATUS_UNSPECIFIED = 0;
  AGENT_RUNTIME_STATUS_UNKNOWN = 1;
  AGENT_RUNTIME_STATUS_INSTALLED = 2;
  AGENT_RUNTIME_STATUS_COMPILED = 3;
  AGENT_RUNTIME_STATUS_RUNNING = 4;
}
```

说明：

- v1 实际只保证 `SESSION_HISTORY_MODE_RESUME_VIEW`
- `FULL_TRANSCRIPT` 仅作为后续协议保留位，不代表当前 runtime 已支持

### 6.3 Requests / Responses

```proto
message ListSessionsRequest {
  string agent_name = 1;
  int32 page_size = 2;
  string page_token = 3;
}

message ListSessionsResponse {
  repeated SessionSummary sessions = 1;
  string next_page_token = 2;
}

message GetSessionRequest {
  string thread_id = 1;
}

message GetSessionResponse {
  bool found = 1;
  SessionDetail session = 2;
}

message GetLatestSessionRequest {
  string agent_name = 1;
}

message GetLatestSessionResponse {
  bool found = 1;
  SessionSummary session = 2;
}

message DeleteSessionRequest {
  string thread_id = 1;
}

message DeleteSessionResponse {
  bool deleted = 1;
}

message GetSessionMessagesRequest {
  string thread_id = 1;
  string checkpoint_id = 2;
  int32 page_size = 3;
  string page_token = 4;
  SessionHistoryMode requested_mode = 5;
  bool include_raw = 6;
}

message GetSessionMessagesResponse {
  string thread_id = 1;
  string resolved_checkpoint_id = 2;
  SessionHistoryMode actual_mode = 3;
  int32 total_message_count = 4;
  repeated SessionMessage messages = 5;
  string next_page_token = 6;
}

message SessionSummary {
  string thread_id = 1;
  string agent_name = 2;
  google.protobuf.Timestamp updated_at = 3;
  string latest_checkpoint_id = 4;
  int32 message_count = 5;
  string initial_prompt = 6;
  SessionHistoryMode history_mode = 7;
  AgentRuntimeStatus agent_status = 8;
}

message SessionDetail {
  SessionSummary summary = 1;
  int32 checkpoint_count = 2;
}

message SessionMessage {
  int32 index = 1;
  SessionMessageRole role = 2;
  string text = 3;
  string tool_call_id = 4;
  string tool_name = 5;
  bool is_error = 6;
  google.protobuf.Struct raw = 7;
}
```

## 7. 字段语义

### 7.1 `thread_id`

- session 的唯一稳定主键
- 与 `RunRequest.thread_id` 语义一致
- 与本地 checkpoint 存储主键一致

### 7.2 `agent_name`

- 表示 thread 当前归属 agent
- 优先从 `checkpoints.metadata.agent_name` 读取
- 若兼容旧数据，可回退到 `assistant_id`

### 7.3 `updated_at`

- 表示 thread 最近一次 checkpoint metadata 写入时间
- 来自 latest checkpoint metadata
- 用于列表排序与增量刷新比较

### 7.4 `latest_checkpoint_id`

- 表示当前 thread 最新 checkpoint
- 主要用于：
  - 列表去重与 freshness 比较
  - 作为 history snapshot 的默认锚点

### 7.5 `message_count`

`message_count` 的语义定义为：

- latest checkpoint 的 `channel_values.messages` 中逻辑消息条数

它**不是**：

- `checkpoints` 表中的行数
- run 次数
- user turn 数

这样定义的原因是，它和“resume 时 agent 实际看到的消息视图”一致。

### 7.6 `checkpoint_count`

`checkpoint_count` 的语义定义为：

- 当前 thread 在 `checkpoints` 表中的持久化快照数量

它是诊断型字段，不应与 `message_count` 混用。

### 7.7 `initial_prompt`

- 来自 latest checkpoint message list 中第一条 human message
- 只用于列表展示和快速识别 thread
- 不保证在 compaction 后仍等于最早原始用户输入

### 7.8 `history_mode`

用于明确返回内容的语义层级：

- `RESUME_VIEW`：latest checkpoint 对应的可恢复会话视图
- `FULL_TRANSCRIPT`：保留位，当前不保证支持

### 7.9 `resolved_checkpoint_id`

该字段只出现在 `GetSessionMessagesResponse` 中，用于：

- 固定本次 history 查询对应的 checkpoint snapshot
- 保证分页期间不会因为 thread 新增 checkpoint 而切换到底层新状态

### 7.10 `agent_status`

- 表示 `SessionSummary.agent_name` 对应 agent 的当前 runtime 生命周期状态
- 该字段来自 live runtime manager snapshot，而不是 checkpoint 本身
- 当 data plane 无法解析当前 agent 状态时，可返回 `UNKNOWN` 或 `UNSPECIFIED`
- 它是 session 摘要的观测性增强字段，不改变 checkpoint-backed session 查询的事实来源

## 8. History 语义与分页

### 8.1 默认 history 语义

`GetSessionMessages` 在 v1 中默认返回：

- `requested_mode = RESUME_VIEW`
- `actual_mode = RESUME_VIEW`

即使调用方请求 `FULL_TRANSCRIPT`，runtime 也可以在 v1 中回落到 `RESUME_VIEW`，前提是 `actual_mode` 明确返回真实语义。

### 8.2 消息顺序

`messages` 建议按逻辑顺序升序返回：

- `index = 0` 表示最早一条消息
- 后续消息按会话顺序递增

这样可以直接用于聊天 UI 渲染，也更符合 checkpoint 中 `messages` 列表的天然顺序。

### 8.3 分页一致性

分页必须基于固定 checkpoint snapshot。

建议行为如下：

1. 当请求中未提供 `checkpoint_id` 时，服务端先解析 latest checkpoint
2. 返回 `resolved_checkpoint_id`
3. `page_token` 应隐式绑定该 `resolved_checkpoint_id`
4. 后续翻页必须继续针对同一 snapshot

这样可以避免 thread 在翻页期间继续运行，导致第二页读取到另一份状态。

### 8.4 `page_token` 语义

`page_token` 应被视为 opaque token，内部可编码：

- `resolved_checkpoint_id`
- `next_start_index`

调用方不应自行构造或解析该 token。

## 9. gRPC 行为约定

### 9.1 not found 处理

对于 thread 不存在的情况，优先返回业务布尔值，而不是 gRPC `NOT_FOUND`：

- `GetSessionResponse.found = false`
- `GetLatestSessionResponse.found = false`
- `DeleteSessionResponse.deleted = false`

原因是：

- session 查询是高频 UI / control plane 调用
- “不存在”是正常业务状态，不是 transport 级异常

### 9.2 参数错误

以下情况建议返回 `INVALID_ARGUMENT`：

- `thread_id` 为空
- `page_size <= 0`
- 非法 `page_token`
- `checkpoint_id` 与 `page_token` 不匹配

### 9.3 存储失败

以下情况建议返回 `INTERNAL`：

- checkpoint 反序列化失败
- SQLite 读取失败
- checkpointer 读取 latest tuple 失败

如果只是某些字段无法提取，但主查询仍然可返回，则可采用 best-effort：

- `initial_prompt = ""`
- `message_count = 0`
- `messages = []`

同时记录 warning 日志。

## 10. 实现映射

### 10.1 可直接复用当前 runtime `sessions.py` 的接口

以下能力基本可直接复用：

- `ListSessions` 对应现有 `list_threads()`
- `GetLatestSession` 对应现有 `get_most_recent()`
- `DeleteSession` 对应现有 `delete_thread()`
- thread 归属信息可复用 `get_thread_agent()`
- 当前 runtime 已经切换到 latest checkpoint `channel_values.messages` 语义来计算 `message_count`
- `SessionSummary.agent_status` 由 gRPC 层基于 `AgentManager.list_agents()` 做 live overlay

### 10.2 可复用 CLI 已验证的 checkpoint 解码逻辑

以下逻辑已经在 CLI 中被验证过，可以迁移到 runtime：

- 从 latest checkpoint 反序列化 `channel_values.messages`
- 从该 message list 计算 `message_count`
- 提取 `initial_prompt`
- 将 checkpoint state 转换为 history message payload

对应参考实现包括：

- `deepagents_cli.sessions._summarize_checkpoint()`
- `deepagents_cli.sessions._load_latest_checkpoint_summary()`
- `deepagents_cli.app._fetch_thread_history_data()`
- `deepagents_cli.app._read_channel_values_from_checkpointer()`

### 10.3 不应依赖 assembled agent 才能查询 session

`SessionQuery` 应尽量仅依赖：

- shared checkpointer
- SQLite checkpoint 存储

而不是要求目标 agent 当前处于 compiled / running 状态。

原因是 session 查询本质上是对本地持久化运行态的读取，而不是对 live runtime instance 的操作。

## 11. 分阶段落地建议

### 阶段一：索引层

优先落地：

- `ListSessions`
- `GetLatestSession`
- `DeleteSession`

这是最小闭环，且能直接服务 thread selector / resume latest / session cleanup。

### 阶段二：单个 thread 摘要

补齐：

- `GetSession`

在这一步中统一 `message_count` 与 `checkpoint_count` 的不同语义。

### 阶段三：history 内容层

最后落地：

- `GetSessionMessages`

这一步需要：

- checkpoint snapshot pinning
- message normalization
- `page_token` 约定

## 12. 后续演进

如果后续需要“完整审计历史”能力，应单独设计：

- `SessionTranscriptQuery`
- 或 append-only `session_events` / `run_events` ledger

而不应继续把 checkpoint 查询接口扩展为 full transcript API。

原因是 checkpoint 的本质职责是：

- 恢复状态

而不是：

- 保证所有中间事件永不丢失
- 提供法证级回放

## 13. 结论

session 查询接口应被定义为 data plane 的本地运行态读取能力：

- 主键使用现有 `thread_id`
- 以 checkpoint 为唯一事实来源
- 先稳定支持 `resume view`
- 明确区分 `message_count` 与 `checkpoint_count`
- 使用独立的 `SessionQuery` service 暴露查询接口

这样设计能最大程度复用当前 runtime 和 CLI 已验证的实现路径，同时避免在 v1 协议中对 full transcript 做出 runtime 当前无法稳定兑现的承诺。

## 14. 当前落地结果

当前 Phase 5 已按本设计完成主链路落地：

- `SessionQuery` service 已实现 `ListSessions / GetSession / GetSessionMessages / GetLatestSession / DeleteSession`
- `message_count` 已与 latest checkpoint `channel_values.messages` 对齐
- `GetSessionMessages` 已实现 snapshot pinning 和分页 token 绑定
- `SessionSummary.agent_status` 已补齐 live runtime 状态覆盖
- `HealthResponse` 已补齐 `installed / assembled / running / ready` 观测字段，与 session 查询能力形成配套的 runtime 观测面
