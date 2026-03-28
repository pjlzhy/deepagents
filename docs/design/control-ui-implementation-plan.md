# Control UI Frontend Implementation Plan

> 状态：Draft
> 最后更新：2026-03-27
> 依赖文档：`docs/design/control-ui-architecture.md`
> 目标：给 control 新 UI 提供可直接开工的前端实现草案

## 1. 背景

`control-ui-architecture.md` 已经定义了 UI 的目标边界：

- 基于 `AionUi` renderer 风格重建 control UI
- 主工作区收敛为 `Chat Workspace`
- `Session` 与 `Run` 在体验层合并，在数据层分离
- 当前范围严格对齐 single `default_target`

本文件继续向前推进一层，回答以下问题：

- 前端项目应该如何分目录
- 路由如何定义
- control HTTP / SSE client 如何分层
- 前端核心类型应该如何起草
- 第一轮实现的任务切分应该如何安排

## 2. 技术栈建议

建议优先复用 `AionUi` 已经验证过的 renderer 技术栈，而不是重新引入另一套前端基础设施。

推荐基线：

- `React 19`
- `TypeScript 5`
- `Vite 6`
- `react-router-dom 7`
- `@arco-design/web-react`
- `UnoCSS`
- `SWR`
- `zod`
- `Vitest`

约束：

- 不默认引入全局 store 库
- 不默认引入重型状态机框架
- `ConversationStateMachine` 和 `RunStateMachine` 优先以 `useReducer + typed action` 或纯函数 reducer 实现

原因：

- `AionUi` 当前已经使用 `React 19 + Router 7 + Arco + UnoCSS + SWR + Vitest`
- 继续沿用这组基础设施，最利于复用 renderer 风格和局部组件习惯
- 当前 control UI 还没有复杂到需要 Redux / Zustand / XState

## 3. Router 设计

### 3.1 Router 选择

建议使用 `BrowserRouter`，而不是直接照搬 `AionUi` 的 `HashRouter`。

原因：

- `AionUi` 使用 `HashRouter` 是为了兼容 Electron renderer 和特定桌面环境
- control UI 是标准 Web 应用，应优先使用更自然的 URL 语义
- 如果后续 control server 需要挂载在子路径，可以通过 `basename` 处理

### 3.2 Route Tree

建议路由树如下：

```text
/
  -> /overview

/overview

/registry
  /registry/models
  /registry/skills
  /registry/mcps
  /registry/agents
  /registry/agents/:agentName

/chat
/chat/:agentName
/chat/:agentName/:threadId

/history

*
  -> /overview
```

### 3.3 Route 文件建议

建议组织方式：

```text
src/app/router/
  index.tsx
  routeTree.tsx
  guards.ts
  links.ts
```

职责：

- `index.tsx`：导出 router 实例
- `routeTree.tsx`：集中声明 route object
- `guards.ts`：保留未来 auth / feature flag 守卫能力
- `links.ts`：统一生成页面跳转链接，避免字符串散落

### 3.4 Route Params 与 Query

建议路由参数和查询参数边界如下：

- path params 只用于表达资源定位
- query params 只用于表达筛选、分页、局部 UI 开关

例如：

- `/registry/models?page_number=2&page_size=20`
- `/history?agent_name=planner&page_size=20&page_token=...`
- `/chat/planner/abc123?inspector=tools`

## 4. 页面与 Feature 对应关系

建议页面壳和业务 feature 明确分离。

| 页面 | 页面职责 | 对应 feature |
|------|----------|--------------|
| `overview` | 组合卡片和快捷入口 | `features/overview` |
| `registry-models` | 组装 model 列表与表单 | `features/models` |
| `registry-skills` | 组装 skill 列表与表单 | `features/skills` |
| `registry-mcps` | 组装 mcp 列表与表单 | `features/mcps` |
| `registry-agents` | agent 列表页 | `features/agents` |
| `agent-detail` | agent 配置页 | `features/agents` |
| `chat-workspace` | 主聊天工作区 | `features/chat` |
| `history-index` | 会话检索与跳转 | `features/history` |

## 5. 目录结构建议

建议目录如下：

```text
src/
  app/
    layout/
      AppShell.tsx
      PrimaryNav.tsx
      PageHeader.tsx
    providers/
      AppProviders.tsx
      ThemeProvider.tsx
      SWRProvider.tsx
    router/
      index.tsx
      routeTree.tsx
      links.ts
    theme/
      tokens.ts
      arco.ts
      uno.css

  pages/
    overview/
      index.tsx
    registry-models/
      index.tsx
    registry-skills/
      index.tsx
    registry-mcps/
      index.tsx
    registry-agents/
      index.tsx
    agent-detail/
      index.tsx
    chat-workspace/
      index.tsx
    history-index/
      index.tsx

  features/
    overview/
      components/
      hooks/
    models/
      api/
      components/
      hooks/
      types.ts
    skills/
      api/
      components/
      hooks/
      types.ts
    mcps/
      api/
      components/
      hooks/
      types.ts
    agents/
      api/
      components/
      hooks/
      types.ts
    chat/
      api/
      components/
      hooks/
      model/
      types.ts
    history/
      api/
      components/
      hooks/
      types.ts

  shared/
    api/
      httpClient.ts
      sseClient.ts
      errors.ts
      codecs.ts
    stream/
      runtimeEventParser.ts
      eventTypes.ts
    types/
      common.ts
      pagination.ts
      sessions.ts
      resources.ts
      runtime.ts
    ui/
      StatusBadge.tsx
      EmptyState.tsx
      ConfirmActionModal.tsx
      DrawerForm.tsx
    utils/
      time.ts
      strings.ts
      routing.ts

  test/
    mocks/
    fixtures/
```

关键原则：

- `pages/` 不直接发请求
- `features/*/api` 只调用 `shared/api/*`
- `shared/types/*` 放协议 DTO
- `features/*/types.ts` 放 feature 内部 view model

## 6. App Shell 建议

建议将顶层布局固定为：

- 左侧主导航
- 顶部轻量 header
- 中间内容区

推荐布局组件：

- `AppShell`
- `PrimaryNav`
- `PageHeader`
- `ContentContainer`

说明：

- 聊天页内部再做自己的三栏布局
- `Registry` 页面沿用“内容区 + 抽屉表单”
- `Overview` 和 `History` 使用统一页面容器

## 7. Control Client 分层

建议将 northbound client 分为四层。

### 7.1 `httpClient`

底层 fetch 封装，负责：

- 基础 URL 拼接
- JSON encode / decode
- 错误状态码归一化
- 统一请求超时
- 统一 header 处理

建议接口：

```ts
export interface HttpClient {
  get<T>(path: string, init?: RequestInit): Promise<T>
  put<TReq, TRes>(path: string, body: TReq, init?: RequestInit): Promise<TRes>
  post<TReq, TRes>(path: string, body: TReq, init?: RequestInit): Promise<TRes>
  delete<T>(path: string, init?: RequestInit): Promise<T>
}
```

### 7.2 `sseClient`

负责：

- 发起 `runs/stream`
- 读取响应 header
- 拿到 `X-Deepagents-Run-Session-ID`
- 逐条解析 SSE envelope
- 提供 `onEvent / onError / onClose` 回调

说明：

- `cancel` 与 `hitl_decisions` 不走 SSE，而是普通 HTTP POST
- `run_session_id` 必须从 stream 响应头提取并保存，供后续 `cancel` / `hitl_decisions` 使用

### 7.3 Resource Clients

建议分资源封装：

- `modelsClient`
- `skillsClient`
- `mcpsClient`
- `agentsClient`
- `sessionsClient`
- `runsClient`

### 7.4 Feature Hooks

建议页面只依赖 hooks，不直接依赖低层 client。

例如：

- `useModelsPage()`
- `useSkillsPage()`
- `useAgentDetail(agentName)`
- `useThreadList(agentName)`
- `useConversationHistory(agentName, threadId)`
- `useRunStream(agentName)`
- `useHitlActions(runSessionId)`

## 8. HTTP DTO 草案

以下类型建议按当前 control northbound JSON 口径定义。

### 8.1 Common

```ts
export interface ApiErrorResponse {
  error: string
}

export interface NumberPageMeta {
  page_size?: number
  page_number?: number
  total_size?: number
  total_pages?: number
}

export interface CursorPageMeta {
  next_page_token?: string
}
```

### 8.2 Model

```ts
export interface ModelConfigDTO {
  name?: string
  description?: string
  provider?: string
  model?: string
  base_url?: string
  api_key_env?: string
  extra_params?: Record<string, string>
  status?: string
  created_at?: string
  updated_at?: string
}

export interface ModelConfigListDTO extends NumberPageMeta {
  models: ModelConfigDTO[]
}
```

### 8.3 Skill

```ts
export interface SkillFileDTO {
  path?: string
  content?: string
}

export interface SkillDTO {
  name?: string
  description?: string
  tags?: string[]
  content?: string
  files?: SkillFileDTO[]
  status?: string
  created_at?: string
  updated_at?: string
}

export interface SkillListDTO extends NumberPageMeta {
  skills: SkillDTO[]
}
```

### 8.4 MCP

```ts
export interface MCPConfigDTO {
  name?: string
  command?: string
  args?: string[]
  env?: Record<string, string>
  transport?: string
  description?: string
  status?: string
  created_at?: string
  updated_at?: string
}

export interface MCPConfigListDTO extends NumberPageMeta {
  mcps: MCPConfigDTO[]
}
```

### 8.5 Agent

```ts
export interface PromptSpecDTO {
  system?: string
}

export interface ModelSpecDTO {
  provider?: string
  model?: string
  base_url?: string
  api_key_env?: string
  extra_params?: Record<string, string>
}

export interface SubagentSpecDTO {
  name?: string
  description?: string
  system_prompt?: string
  model: ModelSpecDTO
}

export interface SandboxSpecDTO {
  image?: string
  resources?: Record<string, string>
  init?: string[]
}

export interface AgentSpecDTO {
  name?: string
  version?: string
  description?: string
  tags?: string[]
  model_ref?: string
  prompt: PromptSpecDTO
  skill_refs?: string[]
  mcp_refs?: string[]
  subagents?: SubagentSpecDTO[]
  sandbox: SandboxSpecDTO
  interrupt_on?: string[]
  status?: string
  created_at?: string
  updated_at?: string
}

export interface AgentSpecListDTO extends NumberPageMeta {
  agents: AgentSpecDTO[]
}
```

## 9. Session DTO 草案

```ts
export interface SessionSummaryDTO {
  thread_id?: string
  agent_name?: string
  latest_checkpoint_id?: string
  message_count?: number
  checkpoint_count?: number
  initial_prompt?: string
  history_mode?: string
  agent_status?: string
  updated_at?: string
}

export interface SessionListDTO {
  sessions: SessionSummaryDTO[]
  next_page_token?: string
}

export interface SessionMessageDTO {
  index?: number
  checkpoint_id?: string
  role?: string
  text?: string
  content?: string
  tool_call_id?: string
  tool_name?: string
  is_error?: boolean
  raw?: unknown
  created_at?: string
}

export interface SessionMessagePageDTO {
  thread_id?: string
  resolved_checkpoint_id?: string
  actual_mode?: string
  total_message_count?: number
  messages: SessionMessageDTO[]
  next_page_token?: string
}

export interface SessionMessagesDTO {
  messages: SessionMessageDTO[]
  next_page_token?: string
}
```

说明：

- registry 资源使用 `page_size + page_number`
- sessions 列表与消息分页使用 `page_size + page_token`
- 前端 client 必须显式区分 number-based paging 和 cursor-based paging

## 10. Run Stream DTO 草案

`runs/stream` 请求体：

```ts
export interface RunStreamRequestDTO {
  message: string
  thread_id?: string
  metadata?: Record<string, string>
}
```

SSE 响应头：

```ts
export interface RunStreamHandshake {
  run_session_id: string
}
```

`run_session_id` 来源：

- HTTP 响应头 `X-Deepagents-Run-Session-ID`

SSE data payload 建议按当前 `httpAgentEvent` 定义：

```ts
export interface HTTPActionRequestDTO {
  name: string
  description?: string
  arguments?: unknown
}

export interface HTTPReviewConfigDTO {
  action_name: string
  allowed_decisions?: string[]
  args_schema?: unknown
}

export interface HTTPAgentEventDTO {
  type: string
  run_id?: string
  agent_name?: string
  timestamp?: string
  thread_id?: string
  text?: string
  tool_name?: string
  tool_call_id?: string
  interrupt_id?: string
  reason?: string
  error_message?: string
  payload?: unknown
  action_requests?: HTTPActionRequestDTO[]
  review_configs?: HTTPReviewConfigDTO[]
}
```

当前事件类型建议收敛为：

```ts
export type RuntimeEventType =
  | 'run_started'
  | 'text_delta'
  | 'text_done'
  | 'tool_call_start'
  | 'tool_call_done'
  | 'tool_result'
  | 'hitl_request'
  | 'run_ended'
  | 'run_canceled'
  | 'error'
```

## 11. HITL DTO 草案

当前 control northbound 的 HITL 决策已经不是旧的 `approved: boolean` 结构。

建议按现在的请求体定义：

```ts
export interface DecisionActionDTO {
  name: string
  arguments?: unknown
}

export interface HitlDecisionDTO {
  type: 'approve' | 'reject' | 'edit'
  message?: string
  edited_action?: DecisionActionDTO
}

export interface SubmitHitlDecisionsRequestDTO {
  interrupt_id: string
  decisions: HitlDecisionDTO[]
}
```

说明：

- `interrupt_id` 必填
- `edit` 决策必须附带 `edited_action`
- `tool_call_id` 不在 northbound request body 中单独提交，而是由 interrupt 上下文承载

## 12. UI View Model 草案

协议 DTO 不应直接塞进组件，建议定义一层 UI view model。

### 12.1 Thread

```ts
export interface ThreadListItemVM {
  threadId: string
  agentName: string
  title: string
  updatedAt?: string
  messageCount?: number
  latestCheckpointId?: string
}
```

### 12.2 Run Status

```ts
export type RunStatusVM =
  | 'idle'
  | 'starting'
  | 'streaming'
  | 'waiting_hitl'
  | 'canceling'
  | 'completed'
  | 'canceled'
  | 'failed'
```

### 12.3 Timeline

```ts
export type TimelineItemVM =
  | {
      kind: 'user_message'
      id: string
      messageId: string
      text: string
      createdAt?: string
    }
  | {
      kind: 'assistant_message'
      id: string
      messageId: string
      text: string
      createdAt?: string
    }
  | {
      kind: 'assistant_draft'
      id: string
      text: string
    }
  | {
      kind: 'tool_event'
      id: string
      toolCallId: string
      toolName?: string
      phase: 'start' | 'done' | 'result'
      payload?: unknown
    }
  | {
      kind: 'hitl_request'
      id: string
      interruptId: string
      title: string
      actionRequests?: HTTPActionRequestDTO[]
      reviewConfigs?: HTTPReviewConfigDTO[]
    }
  | {
      kind: 'system_event'
      id: string
      event: 'run_started' | 'run_ended' | 'run_canceled' | 'error'
      message?: string
    }
```

### 12.4 Chat Workspace State

```ts
export interface ChatWorkspaceState {
  selectedAgentName?: string
  selectedThreadId?: string
  runSessionId?: string
  runId?: string
  runStatus: RunStatusVM
  timeline: TimelineItemVM[]
  pendingInterruptIds: string[]
  streamConnected: boolean
  composerValue: string
}
```

## 13. Hook 设计建议

建议将聊天页的 hooks 拆成下面几层。

### 13.1 Query Hooks

- `useAgentOptions()`
- `useThreadList(agentName)`
- `useLatestSession(agentName)`
- `useSessionSummary(agentName, threadId)`
- `useSessionMessages(agentName, threadId, query)`

### 13.2 Mutation Hooks

- `useUpsertModel()`
- `useUpsertSkill()`
- `useUpsertMCP()`
- `useUpsertAgent()`
- `useEnsureRunnable(agentName)`
- `useDeleteSession(agentName, threadId)`
- `useCancelRun(runSessionId)`
- `useSubmitHitlDecisions(runSessionId)`

### 13.3 Chat Hooks

- `useConversationMachine()`
- `useRunMachine()`
- `useRunStream()`
- `useRuntimeEventParser()`
- `useComposerSubmit()`

## 14. `runtimeEventParser` 接口建议

建议保持纯函数接口，降低和 React 的耦合。

例如：

```ts
export interface RuntimeParserState {
  runStatus: RunStatusVM
  draftText: string
  timeline: TimelineItemVM[]
  pendingInterruptIds: string[]
}

export function reduceRuntimeEvent(
  state: RuntimeParserState,
  event: HTTPAgentEventDTO,
): RuntimeParserState
```

优点：

- 易测
- 与 `useRunStream` 解耦
- 未来增加事件类型时影响面最小

## 15. `links.ts` 建议

建议统一收敛链接生成函数。

```ts
export const links = {
  overview: () => '/overview',
  models: () => '/registry/models',
  skills: () => '/registry/skills',
  mcps: () => '/registry/mcps',
  agents: () => '/registry/agents',
  agentDetail: (agentName: string) => `/registry/agents/${encodeURIComponent(agentName)}`,
  chatRoot: () => '/chat',
  chatAgent: (agentName: string) => `/chat/${encodeURIComponent(agentName)}`,
  chatThread: (agentName: string, threadId: string) =>
    `/chat/${encodeURIComponent(agentName)}/${encodeURIComponent(threadId)}`,
  history: () => '/history',
}
```

这样可以避免：

- 页面中硬编码字符串路由
- agent name / thread id 没有编码
- 后续改路由时全局替换

## 16. 实现顺序建议

建议按下面的包级顺序推进。

### Step 1

- 初始化 `app/`
- 落地 `BrowserRouter`
- 落地 `AppShell`
- 落地 design tokens

### Step 2

- 落地 `shared/api/httpClient.ts`
- 落地 `shared/api/sseClient.ts`
- 落地 `shared/types/*`

### Step 3

- 完成 `models / skills / mcps` 页面
- 验证 number-based paging

### Step 4

- 完成 `agents` 页面与 `agent-detail`
- 接通引用选择器和 `ensure_runnable`

### Step 5

- 落地 `chat-workspace` 静态三栏结构
- 落地 `links.ts`
- 落地 `chat` feature types

### Step 6

- 接 `sessions` 查询
- 跑通 thread 列表、latest session、history messages

### Step 7

- 实现 `runtimeEventParser`
- 接 `runs/stream`
- 保存 `run_session_id`

### Step 8

- 接 `cancel`
- 接 `hitl_decisions`
- 补 `history-index`

### Step 9

- 收口错误态、空态、loading
- 加单测和进程内联调测试

## 17. 测试建议

建议从一开始就分三层测试。

### 17.1 Pure Function 单测

覆盖：

- `runtimeEventParser`
- `ConversationStateMachine`
- `RunStateMachine`
- `links.ts`

### 17.2 Hook / Component 单测

覆盖：

- `ThreadList`
- `MessageTimeline`
- `ComposerBar`
- `PendingHitlPanel`

### 17.3 API Contract Mock 测试

建议使用 mock fetch / mock SSE 验证：

- `runs/stream` header 中是否能正确提取 `X-Deepagents-Run-Session-ID`
- SSE event 是否能正确映射为 timeline
- `cancel` / `hitl_decisions` 是否使用正确的 `run_session_id`

## 18. 风险与注意事项

- `sessions` 与 registry 分页模型不同，不建议强行抽成一个“万能分页 hook”
- 聊天页如果让组件直接消费 `HTTPAgentEventDTO`，后续很容易失控
- `BrowserRouter` 需要 control server 在部署时正确处理 SPA fallback
- 新建对话场景中，`thread_id` 在首条消息发送前可能不存在，前端必须接受“先发送、后绑定”的流程

## 19. 参考

- `docs/design/control-ui-architecture.md`
- `libs/control/pkg/api/http_handler.go`
- `proto/runtime.proto`
- `libs/AionUi/package.json`
- `libs/AionUi/src/renderer/main.tsx`
- `libs/AionUi/src/renderer/components/layout/Router.tsx`
- `libs/AionUi/src/renderer/pages/settings/components/SettingsSider.tsx`
