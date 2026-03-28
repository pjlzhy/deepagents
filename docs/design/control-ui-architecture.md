# Control UI Architecture and Roadmap

> 状态：Draft
> 最后更新：2026-03-27
> 目标范围：基于 `AionUi` renderer 风格重建 control UI
> 当前实现范围：single `default_target`

## 1. 背景

当前 `libs/control` 已经具备可用的 northbound HTTP / SSE 接口，覆盖：

- `models` CRUD
- `skills` CRUD
- `mcps` CRUD
- `agents` CRUD
- `ensure_runnable`
- `runs/stream`
- `run_sessions cancel / hitl_decisions`
- `sessions list / latest / detail / message_page / messages / delete`

此前的 `control-web` 已移除，当前需要重新设计一版 UI。

新的 UI 不再尝试直接复用 `AionUi` 的业务桥接协议，而是采用下面的策略：

- 复用 `AionUi` renderer 的视觉语言、布局方式、设置页组织方式和聊天页结构
- 不复用 `AionUi` 的 `AuthContext`、`ipcBridge`、本地 conversation 协议和 desktop-only 适配层
- 直接消费 control plane 现有 HTTP / SSE northbound API

一句话定义：

```text
control UI = AionUi renderer 风格 + control northbound client + Chat Workspace 主工作区
```

## 2. 设计目标

本设计希望解决以下问题：

- 为当前 control plane 提供一套完整、可扩展的 Web UI
- 保持与现有 northbound API 一一对应，避免 UI 先行发散
- 将 `session` 与 `run` 收敛到同一个聊天工作区中
- 让资源配置、运行、历史查询形成闭环
- 为后续增量迭代保留清晰的前端边界

## 3. 非目标

本轮 UI 不处理以下能力：

- `Auth` / `RBAC`
- multi-target
- `Deployment` / `RuntimeTarget` 北向管理
- `workspace` 概念
- 文件预览 / 沙箱文件浏览
- scheduler / cron
- extension / channel / marketplace
- 兼容 `AionUi` 原有 `ipcBridge` conversation 协议

## 4. 现实约束

### 4.1 当前 northbound contract 以 single `default_target` 为准

本轮 UI 不暴露 target 选择，也不引入 runtime target 管理入口。

所有主路径都围绕当前默认 southbound target 展开。

### 4.2 session 粒度已经收敛为 `agent_name + thread_id`

在 UI 层面：

- thread 列表必须按 `agent_name` 过滤
- thread 详情、消息、删除都必须显式带 `agent_name`
- UI 不能再以“仅凭 `thread_id` 访问会话”为主路径

### 4.3 `run` 是当前会话上的一次活跃执行，不应成为独立主页面

用户真正的工作场景是“在一个会话里继续聊天”。

因此 UI 主工作区必须是聊天窗口，历史消息、实时输出、HITL、取消操作都收敛在同一个页面中。

## 5. AionUi 可复用与不可复用边界

### 5.1 可复用的部分

可直接借鉴的不是业务协议，而是 renderer 的表现层组织方式：

- 顶层 `renderer` 入口与 provider 组织
- 主导航 + 内容区的 layout 思路
- 设置页侧栏的层级表达
- 列表页 + 抽屉表单的交互风格
- 聊天区 + 侧边 inspector 的信息组织方式
- `Arco Design + UnoCSS` 的组件和样式语义

### 5.2 不可直接复用的部分

以下内容需要重写，而不是适配：

- `AuthContext`
- `browser.ts`
- `ipcBridge.ts`
- 各类 `conversation.*`、`acpConversation.*`、`mode.*` bridge 调用
- 当前 `AionUi` 的本地 workspace / preview / extension / cron 页面

### 5.3 复用原则

遵循以下原则：

- 复用视觉，不复用协议
- 复用布局，不复用状态模型
- 复用组件风格，不复用页面业务逻辑

## 6. 总体信息架构

新的主导航建议收敛为三组：

- `Overview`
- `Registry`
- `Chat`

对应页面如下：

| 页面 | 路由建议 | 目标 |
|------|----------|------|
| Overview | `/overview` | 健康状态、资源概览、最近活动 |
| Models | `/registry/models` | model 资源 CRUD |
| Skills | `/registry/skills` | skill 资源 CRUD |
| MCPs | `/registry/mcps` | mcp 资源 CRUD |
| Agents | `/registry/agents` | agent 资源 CRUD |
| Agent Detail | `/registry/agents/:agentName` | agent spec 编辑、引用绑定、`ensure_runnable` |
| Chat Workspace | `/chat`、`/chat/:agentName`、`/chat/:agentName/:threadId` | 主聊天工作区，整合 session history + current run |
| History Index | `/history` | 辅助检索页，按 agent/thread 找到会话并跳转回聊天页 |

关键约束：

- 不再存在独立的 `Run Console` 导航页
- `History` 是索引页，不是另一套主工作流
- `Chat Workspace` 是唯一主工作区

## 7. 页面设计

### 7.1 Overview

`Overview` 保持克制，只承担三个职责：

- 告诉用户服务是否健康
- 告诉用户当前有哪些资源
- 提供恢复工作的快捷入口

建议区块：

- Health Card
- Resource Counts
- Latest Sessions
- Quick Actions
- Recent Activity

### 7.2 Registry

`Models / Skills / MCPs / Agents` 共享一套列表页骨架：

- 顶部 `PageHeader`
- 列表筛选与分页工具栏
- 主体资源表格或卡片列表
- 右侧抽屉创建 / 编辑表单

统一交互：

- 列表页承担查询、分页、进入详情
- 创建和编辑优先走抽屉，而不是独立页面
- 删除统一使用确认弹层

### 7.3 Agent Detail

`Agent Detail` 是最复杂的配置页，建议使用双栏设置页风格：

- 左栏：基础信息、行为配置、说明字段
- 右栏：`model_ref`、`skill_refs`、`mcp_refs`、校验状态、`ensure_runnable`

推荐能力：

- 结构化表单为默认模式
- 提供受控的 `raw json` 预览或高级编辑入口
- `Open Chat` 作为显式快捷操作

### 7.4 Chat Workspace

`Chat Workspace` 是整套 UI 的核心页面。

建议使用三栏布局：

```text
+--------------------------------------------------------------------------------------+
| Top Header                                                                           |
+----------------------+-------------------------------------------+-------------------+
| Left Sidebar         | Main Chat Timeline                        | Right Inspector   |
|----------------------|-------------------------------------------|-------------------|
| Agent Selector       | Conversation Header                       | Run Status Card   |
| New Conversation     | Message Timeline                          | Pending HITL      |
| Thread Search        | Composer                                  | Tool Timeline     |
| Thread List          |                                           | Session Meta      |
+----------------------+-------------------------------------------+-------------------+
```

语义收敛如下：

- 左栏负责定位当前聊天上下文
- 中栏负责统一展示历史消息与当前流式输出
- 右栏负责当前运行状态、HITL 和调试信息

### 7.5 History Index

`History Index` 不是聊天页的替代品，而是检索页。

建议功能：

- 按 `agent_name` 过滤
- 按 thread 关键字过滤
- 查看最新会话
- 跳转到 `Chat Workspace`
- 删除会话

## 8. Chat Workspace 组件树

建议采用下面的组件树：

```text
ChatWorkspacePage
  ChatWorkspaceShell
    ChatHeaderBar
    ChatWorkspaceBody
      ThreadSidebar
        AgentSelector
        NewConversationButton
        ThreadSearchBox
        ThreadList
          ThreadListItem
      ChatMainPane
        ConversationHeader
        MessageTimeline
          TimelineDayDivider
          UserMessageItem
          AssistantMessageItem
          AssistantDraftItem
          ToolEventItem
          HitlRequestItem
          SystemEventItem
        ComposerBar
          ComposerTextarea
          ComposerActions
      ChatInspector
        RunStatusCard
        PendingHitlPanel
        ToolTimelinePanel
        SessionMetaCard
        DebugEventPanel
```

职责边界：

- `ThreadSidebar` 只负责 agent/thread 选择与导航，不直接处理 run stream
- `MessageTimeline` 只渲染统一的 timeline items，不解析原始 runtime event
- `ComposerBar` 只负责输入与发送动作，不负责消息归并
- `ChatInspector` 只负责辅助信息与当前执行控制

## 9. 状态模型

建议将聊天页状态拆成四层。

### 9.1 Route State

由路由表达的状态：

- `selectedAgentName`
- `selectedThreadId`

建议路由：

- `/chat`
- `/chat/:agentName`
- `/chat/:agentName/:threadId`

### 9.2 Server State

由后端拉取的数据：

- agent list
- thread list
- session summary
- history messages
- latest session
- registry resources

这些状态建议由 query 层维护。

### 9.3 Runtime Ephemeral State

仅属于当前聊天页运行期：

- current run status
- active session id
- active run id
- current assistant draft
- pending tool calls
- pending hitl requests
- canceling flag
- stream connection state

### 9.4 UI State

纯前端局部状态：

- inspector 折叠状态
- composer 输入内容
- thread 搜索关键字
- debug 面板开关
- timeline 是否自动跟底

## 10. 状态机草案

建议拆成两个协作状态机，而不是一个巨型状态机。

### 10.1 ConversationStateMachine

职责：确定当前页面落在哪个会话上下文中。

状态：

- `no_agent`
- `agent_selected_no_thread`
- `loading_history`
- `conversation_ready`
- `conversation_error`

迁移：

```text
no_agent
  -- SELECT_AGENT -->
agent_selected_no_thread

agent_selected_no_thread
  -- OPEN_THREAD(thread_id) -->
loading_history
  -- SEND_FIRST_MESSAGE -->
conversation_ready

loading_history
  -- HISTORY_LOADED -->
conversation_ready
  -- HISTORY_FAILED -->
conversation_error

conversation_ready
  -- SWITCH_AGENT -->
agent_selected_no_thread
  -- OPEN_THREAD -->
loading_history

conversation_error
  -- RETRY -->
loading_history
```

### 10.2 RunStateMachine

职责：确定当前会话上是否存在活跃执行。

状态：

- `idle`
- `starting`
- `streaming`
- `waiting_hitl`
- `canceling`
- `completed`
- `canceled`
- `failed`

迁移：

```text
idle
  -- START_RUN -->
starting

starting
  -- EVENT_RUN_STARTED -->
streaming
  -- EVENT_ERROR -->
failed

streaming
  -- EVENT_TEXT_DELTA -->
streaming
  -- EVENT_TOOL_CALL_START -->
streaming
  -- EVENT_HITL_REQUEST -->
waiting_hitl
  -- USER_CANCEL -->
canceling
  -- EVENT_RUN_ENDED -->
completed
  -- EVENT_RUN_CANCELED -->
canceled
  -- EVENT_ERROR -->
failed

waiting_hitl
  -- SUBMIT_HITL_DECISION -->
streaming
  -- USER_CANCEL -->
canceling
  -- EVENT_ERROR -->
failed

canceling
  -- EVENT_RUN_CANCELED -->
canceled
  -- EVENT_RUN_ENDED -->
completed
  -- EVENT_ERROR -->
failed
```

协作规则：

- 只有当 `ConversationStateMachine = conversation_ready` 或“新对话可发送态”时，才能触发 `START_RUN`
- 切换 agent 或 thread 时，如果 run 尚未收敛到终态，必须先做交互确认
- run 完成后，应刷新 session summary 和 history query

## 11. Timeline 数据模型

聊天页不应直接消费 proto 事件，而应先转换为统一 timeline item。

建议的数据模型：

```ts
type TimelineItem =
  | { kind: 'user_message'; id: string; messageId: string; text: string; createdAt: string }
  | { kind: 'assistant_message'; id: string; messageId: string; text: string; createdAt: string }
  | { kind: 'assistant_draft'; id: string; text: string }
  | {
      kind: 'tool_event'
      id: string
      toolCallId: string
      phase: 'start' | 'done' | 'result'
      title: string
      payload?: unknown
    }
  | {
      kind: 'hitl_request'
      id: string
      interruptId: string
      toolCallId: string
      title: string
      approved?: boolean
    }
  | {
      kind: 'system_event'
      id: string
      event: 'run_started' | 'run_ended' | 'run_canceled' | 'error'
      message: string
    }
```

设计原则：

- 历史消息与实时输出混排
- `text_delta` 聚合为单条草稿消息
- `text_done` 将草稿固化为正式 assistant message
- tool 事件与 HITL 作为独立的 timeline item

## 12. Runtime Event Parser

建议独立 `runtimeEventParser`，统一把 runtime 协议转为 UI 状态补丁。

最小职责：

- 处理 `run_started`
- 聚合 `text_delta`
- 固化 `text_done`
- 跟踪 `tool_call_start / tool_call_done / tool_result`
- 跟踪 `hitl_request`
- 处理 `run_ended / run_canceled / error`
- 输出统一的 timeline items、draft state 和 run status

parser 内部建议维护：

- `draftText`
- `timelineItems`
- `toolCallIndex`
- `pendingHitlMap`
- `currentRunStatus`
- `lastError`

## 13. 前端分层与目录建议

建议目录结构如下：

```text
src/
  app/
    layout/
    providers/
    router/
    theme/
  pages/
    overview/
    registry-models/
    registry-skills/
    registry-mcps/
    registry-agents/
    agent-detail/
    chat-workspace/
    history-index/
  features/
    models/
    skills/
    mcps/
    agents/
    chat/
      components/
      hooks/
      model/
      api/
    history/
  shared/
    api/
      controlClient/
    stream/
      runtimeEventParser/
    types/
    ui/
    utils/
```

分层原则：

- `app/` 只放全局 layout、router、provider、theme
- `pages/` 只做页面组装
- `features/` 负责业务组件和 hooks
- `shared/api/controlClient/` 作为 control northbound anti-corruption layer
- `shared/stream/runtimeEventParser/` 负责协议适配

## 14. 页面与接口映射

| 页面 | 接口 |
|------|------|
| Overview | `GET /api/v1/health`，以及资源列表的轻量聚合查询 |
| Models | `GET/PUT/DELETE /api/v1/models` |
| Skills | `GET/PUT/DELETE /api/v1/skills` |
| MCPs | `GET/PUT/DELETE /api/v1/mcps` |
| Agents | `GET/PUT/DELETE /api/v1/agents` |
| Agent Detail | `GET/PUT /api/v1/agents/{name}`，`POST /api/v1/agents/{agent}/ensure_runnable` |
| Chat Workspace | `POST /api/v1/agents/{agent}/runs/stream`，`POST /api/v1/run_sessions/{session_id}/cancel`，`POST /api/v1/run_sessions/{session_id}/hitl_decisions`，以及 `sessions` 查询接口 |
| History Index | `GET /api/v1/sessions`，`GET /api/v1/sessions/latest`，`DELETE /api/v1/sessions/{thread_id}` |

## 15. 线性 Roadmap

按单名前端工程师串行推进，建议时间表如下。

### Phase 1: UI Skeleton

目标：

- 初始化前端工程
- 落地 `AppShell`
- 确立 AionUi renderer 风格的 design tokens
- 接入 `Arco Design + UnoCSS`
- 建立 `controlClient` 基础层

交付：

- 可运行的壳层
- 主导航与路由
- 统一 API client 和错误处理框架

### Phase 2: Registry 基础资源页

目标：

- 完成 `Models / Skills / MCPs` 页面
- 统一分页、列表、抽屉表单和 CRUD 闭环

交付：

- 三类资源管理页可用
- 基础表单校验与错误提示可用

### Phase 3: Agent 管理与配置页

目标：

- 完成 `Agents` 列表页
- 完成 `Agent Detail`
- 落地 `model_ref / skill_refs / mcp_refs` 选择器
- 接通 `ensure_runnable`

交付：

- agent 资源可完整配置
- 从 agent detail 快速进入聊天页

### Phase 4: Chat Workspace 主路径

目标：

- 落地三栏聊天页
- 接通 agent/thread 选择
- 接通历史消息查询
- 接通 `runs/stream`
- 实现 `cancel`
- 实现 `HITL`

交付：

- 用户可以在一个聊天页内完成“选 agent -> 选 thread -> 看历史 -> 继续聊 -> 处理中断审批”

### Phase 5: History 补强

目标：

- 完成 `History Index`
- 接通 `latest session`
- 支持 thread 检索与删除
- 补齐 message page / messages 视图

交付：

- 会话检索与恢复闭环

### Phase 6: 联调与体验收口

目标：

- 异常态和空态收口
- loading / skeleton / retry 统一
- timeline 自动滚动策略
- 移动端与窄屏收缩
- 前端测试与文档补齐

交付：

- 可持续迭代的 UI 基线

## 16. 风险与权衡

- 最大风险不是视觉，而是 `SSE + runtime event` 的状态收敛
- `sessions` 分页模型与 registry 资源分页模型不同，client 层必须统一封装
- 如果未来恢复 multi-target，这一版路由与缓存 key 需要预留扩展点，但当前不应在 UI 中暴露
- `Chat Workspace` 内部若不提前建立状态机和 parser，后续一旦加入更多事件类型会迅速失控

## 17. 建议的下一步

如果开始实现，建议按以下顺序推进：

1. 先搭 `AppShell + Router + Theme`
2. 再搭 `controlClient`
3. 再完成 `Models / Skills / MCPs`
4. 再完成 `Agents + Agent Detail`
5. 再搭 `Chat Workspace` 静态壳
6. 再实现 `ConversationStateMachine + RunStateMachine`
7. 再实现 `runtimeEventParser`
8. 最后接入 stream、cancel、HITL 和 history

## 18. 参考

- `AionUi` renderer 入口：`libs/AionUi/src/renderer/main.tsx`
- `AionUi` 路由骨架：`libs/AionUi/src/renderer/components/layout/Router.tsx`
- `AionUi` 设置页侧栏：`libs/AionUi/src/renderer/pages/settings/components/SettingsSider.tsx`
- `AionUi` 认证上下文：`libs/AionUi/src/renderer/hooks/context/AuthContext.tsx`
- `AionUi` IPC 桥：`libs/AionUi/src/common/adapter/ipcBridge.ts`
- control HTTP 路由：`libs/control/pkg/api/http_handler.go`
- runtime 协议：`proto/runtime.proto`
