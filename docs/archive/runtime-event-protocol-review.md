# Runtime Event Protocol Review

> 状态：Phase 1 / Phase 2 / Phase 3A / Phase 4 / timestamp 精度修复 已完成
> 最后更新：2026-03-27
> 当前遗留：无硬性协议阻塞项；后续按需推进上层 UI 增强

## 概述

本文档审查 `proto/runtime.proto` 中 `AgentExecutor.Run` 相关事件协议，重点关注以下问题：

- protobuf 事件模型是否与 runtime 内部真实语义一致
- runtime -> gRPC -> control -> HTTP/SSE -> web 链路是否语义自洽
- 当前协议是否已经具备稳定扩展能力

本文最初用于归档事件协议审查结论。当前已继续承担“审查结论 + 演进记录”的作用：

- Phase 1：HITL transport hardening 已落地
- Phase 2：HITL protobuf 模型收敛已落地
- Phase 3A：tool 事件的结构化 transport 承诺已落地
- Phase 4：文档与注释同步已落地

因此，文中关于 Phase 1 / Phase 2 的问题拆解保留为历史依据；当前协议主路径、关键 transport 边界和文档注释都已完成收口。

## 审查范围

本次 review 覆盖以下边界：

- `proto/runtime.proto` 中 `ClientMessage`、`AgentEvent` 以及相关 HITL / cancel / error / tool 事件定义
- `libs/runtime/agents-runtime` 中的 stream parser、protobuf converters、gRPC server、manager / runtime agent 执行链
- `libs/control` 中 gRPC mapper、run stream proxy、HTTP northbound 输出
- `libs/control-web` 中 run studio 对 southbound 事件的消费

重点审查的是“事件协议”而不是“业务功能列表”。`ResourceSync` 和 `SessionQuery` 不属于本文的主目标，只在与事件模型直接相关时提及。

## 审查方法

本次审查基于两部分：

### 1. 静态代码审查

逐层对照以下实现：

- `proto/runtime.proto`
- `agents_runtime/converters.py`
- `agents_runtime/streams.py`
- `agents_runtime/entry/server.py`
- `agents_runtime/agent.py`
- `control/pkg/runtimeclient/grpc_mapper.go`
- `control/pkg/streamproxy/default_proxy.go`
- `control/pkg/api/http_handler.go`
- `control-web/src/features/run-studio/*`

### 2. 现有测试验证

已运行并通过以下测试：

- `uv run --project libs/runtime/agents-runtime pytest tests/unit_tests/test_event_protocol.py`
- `uv run --project libs/runtime/agents-runtime pytest tests/integration_tests/test_manager_process_integration.py -k structured_tool_payloads`
- `go test ./pkg/runtimeclient ./pkg/api`
- `pnpm.cmd typecheck`
- `pnpm.cmd exec vitest run --config vitest.config.ts src/features/run-studio/state.test.ts src/features/run-studio/run-studio-page.test.tsx`

因此，本文结论已经从“主路径可用，但协议边界仍待收敛”更新为“主路径已经完成到 tool payload、timestamp precision 与文档注释同步层面”。

## 当前协议状态

### 已成立的事实

当前 `runtime.proto` 事件协议已经支撑以下主路径：

- control plane 可以通过 gRPC `Run` 发起执行
- runtime 可以稳定流出 `run_started`、`text_delta`、`tool_call_start`、`tool_result`、`hitl_request`、`run_ended`、`run_canceled`、`error`
- runtime 可以稳定填充 `ToolCallStart.args`，并在 `ToolResult.payload` 中保留 JSON-like 工具结果
- control 层可以将 southbound 事件映射为 northbound HTTP/SSE 事件，并透传 tool payload
- web 层可以消费当前事件流，完成基础 timeline 展示、approve / reject / edit 型 HITL 交互，以及 tool args / result 的 payload inspector 展示

### 当前真实结论

当前协议对“基础 run + 已收敛的 HITL 主路径 + 结构化 tool payload 主路径”已经可用，且核心文档/注释也已经同步。

当前剩余事项主要是上层可选增强，例如更丰富的 tool UI，而不是 southbound 协议或 transport 边界问题。

## 关键问题

以下问题按优先级排序。

> 注：
>
> - 问题 1 / 2 / 3 / 4 / 5 / 6 已分别在 Phase 1 / Phase 2 / Phase 3A / timestamp 精度修复 / Phase 3A / Phase 4 完成
> - 它们仍保留在本文中，作为协议如何收敛到当前状态的历史背景
> - 当前已经没有明确未完成的协议阻塞项
### 1. 高优先级（已在 Phase 1 解决）：`interrupt_id` 在 server 侧没有被真正用于匹配 HITL 响应

当前状态（2026-03-27）：

- runtime gRPC server 已通过 `_HITLDecisionCoordinator` 显式注册 pending interrupt
- `HITLDecision.interrupt_id` 现在会做 unknown / closed / duplicate 校验
- decision 数量会和当前 interrupt 的 action count 做 transport 级校验

这个问题保留在本文中，仅作为为什么要做 Phase 1 hardening 的历史背景。

### 2. 高优先级（已在 Phase 2 解决）：当前 HITL protobuf 模型只是兼容层，不是底层真实语义

当前状态（2026-03-27）：

- `ActionRequest` 已对齐到 `{ name, args, description }`
- `HITLRequest` 已显式包含 `review_configs`
- `Decision` 已显式表达 `approve | reject | edit`
- `edited_action` 已有正式 transport 字段
- `tool_call_id` 不再承担命中匹配键语义

因此，HITL protobuf 模型已经从“历史兼容层”收敛为“真实语义优先”的协议模型。

### 3. 中优先级（已在 Phase 3A 解决）：`ToolCallStart.args` 已在 proto 暴露，但当前实现没有稳定填充

当前状态（2026-03-27）：

- runtime parser 现在会为 `tool_call_buffers` 保存 `name / id / args / args_text / started`
- `tool_call` 带完整结构化参数时，会直接发出带 `args` 的 `tool_call_start`
- `tool_call_chunk` 会按 `index/id` 聚合，在第一次成功解析为稳定对象时发出一次 `tool_call_start`
- 如果直到 tool 真正执行前都拿不到可解析参数，runtime 仍会补发一次 `tool_call_start`，但 `args` 保持 unset

因此，`ToolCallStart.args` 已从“公开承诺但常为空”的状态，收敛为“有则可靠、没有则缺失”的稳定语义。

### 4. 中优先级（已修复）：时间戳在 protobuf 边界被截断到秒级

当前状态（2026-03-27）：

- runtime 已不再使用 `Timestamp.FromSeconds(int(event.timestamp))`
- `RuntimeEvent.timestamp` 现在会被拆分为 `seconds + nanos` 写入 protobuf `Timestamp`
- control gRPC mapper、HTTP 层的 `RFC3339Nano` 输出能力已经能够保留这部分亚秒精度
- runtime 单测已覆盖 protobuf roundtrip 的亚秒精度保留，control HTTP 测试已覆盖 northbound 时间戳字符串输出

因此，这个问题已经从“明确的 transport 观测缺陷”收敛为“已完成修复”。

### 5. 中优先级（已在 Phase 3A 解决）：`ToolResult` 目前是字符串化 transport，结构化工具结果会丢信息

当前状态（2026-03-27）：

- `ToolResult` 已新增 `google.protobuf.Value payload`
- runtime 在解析 `ToolMessage` 时，会优先从 `artifact` 提取结构化结果；若没有 `artifact`，则对 JSON-like `content` 做结构化保留
- `content` 继续作为向后兼容的文本投影保留
- control 已将 `tool_result.payload` 透传到 northbound `payload`
- web Run Studio 已可以在 payload inspector 中直接查看结构化 tool result

因此，`ToolResult` 已不再是“只能字符串化 transport”的协议模型。

### 6. 低优先级（已在 Phase 4 解决）：`runtime.proto` 注释存在乱码，协议可读性已经受损

当前状态（2026-03-27）：

- `runtime.proto` 顶部与主要分段的乱码注释已清理
- `ToolCallStart`、`ToolResult`、HITL 相关字段注释已同步到当前协议语义
- control / web 对 HITL 和 tool payload 的字段口径已与设计文档对齐

该问题已完成收口，后续只需在协议继续演进时同步维护。

## 风险判断

### 已确认的风险

- 当前没有明确的 southbound 协议阻塞风险

### 推导出的扩展性风险

以下内容是基于实现方式做出的工程判断，不是当前测试已证实的线上故障：

- 如果未来引入极高频、极长时间跨度的事件分析需求，`RuntimeEvent.timestamp` 仍以 Python `float` 表达这一内部实现细节，可能成为进一步提升精度时需要重新评估的点
- 如果后续要做更丰富的 tool UI 卡片化能力，需要继续在 web 层做展示增强，但这已不再是协议阻塞项

## 建议演进方向

### Phase 1：先补 transport 边界校验

这一阶段不要求立刻重构整个协议，但应先把明显的边界漏洞收紧：

- server 收到 `HITLDecision` 时，必须校验 `interrupt_id`
- 应明确当前 run 内有哪些 pending interrupt
- 应校验 decision 数量与当前 interrupt 的 action count 是否一致
- 对不匹配的 decision，应尽早返回 transport 级错误，而不是把错误留给图执行层

目标不是“支持新能力”，而是先让现有协议的声明和实现一致。

### Phase 2：正式收敛 HITL protobuf 模型

这一阶段建议停止把当前 `ToolDecision` 当作长期协议。

建议方向：

- `ActionRequest` 与底层 LangChain 语义对齐，至少补 `description`
- `HITLRequest` 显式表达 `review_configs`
- `Decision` 改为显式 `type` 判别，而不是 `approved: bool`
- 为 `edit` 提供正式字段，如 `edited_action`
- 明确 `tool_call_id` 是否仍保留

如果保留 `tool_call_id`，它也应被重新定义为“展示和关联辅助信息”，而不是 transport 命中键。

### Phase 3：收敛 tool 事件的 transport 承诺

这里已经不再保留双分叉状态，当前明确选择：

- 方案 A：承认 `ToolCallStart.args` 和结构化 `ToolResult` 是公共协议能力

原因很直接：

- `runtime.proto` 已经对 `ToolCallStart.args` 做了公开承诺
- control / web 当前已经具备通用 `payload` 通道，不需要重新发明 northbound contract
- Phase 2 已经把 HITL 模型提升到“真实语义优先”，Phase 3 继续承认 tool 事件的结构化语义，整体方向是一致的
- 如果此时退回方案 B，等于把 proto、control、web 的后续可观测性能力主动收缩，后面再重做会产生第二次迁移

当前需要明确的，不再是“选 A 还是 B”，而是“方案 A 具体如何实现，边界如何定义”。

#### Phase 3A 当前落地结果（2026-03-27）

- `runtime.proto` 已为 `ToolResult` 增加 `payload`
- runtime 已补齐 `tool_call/tool_call_chunk` 的参数聚合与一次性 `tool_call_start` 发射语义
- runtime 已补齐 `ToolResult.payload` 保真，并保留 `content` 文本投影
- control 已将 `tool_call_start.args` / `tool_result.payload` 透传到 northbound `payload`
- web Run Studio 已默认优先展示 tool args / structured result，而不是整个 event envelope
- runtime 单测、进程内 gRPC 集成、control 测试、control-web 测试均已覆盖该主路径
- runtime 与 control 侧也已覆盖 timestamp 精度修复后的主路径

以下 3A-1 ~ 3A-8 保留为设计与实施记录，现均已完成。

#### Phase 3A-1：目标定义

方案 A 的目标不是让 tool 事件变成复杂的实时 debug 协议，而是补齐当前已经对外承诺但未稳定兑现的最小能力：

- `ToolCallStart.args` 被视为正式公共字段，runtime 必须尽可能稳定填充
- `ToolResult` 保留当前面向人类阅读的文本视图，同时额外保留机器可读的结构化结果
- control / web 不引入新的 northbound 分叉模型，而是复用现有通用 `payload` 通道

这意味着 Phase 3A 解决的是“结构化信息保真”，不是“再设计一套新的 tool event taxonomy”。

#### Phase 3A-2：协议收敛结论

方案 A 下，tool 事件协议建议明确为以下语义：

1. `ToolCallStart`

- `tool_name`
- `tool_call_id`
- `args`

其中：

- `args` 的语义是“当前 runtime 已成功解析出的稳定参数对象”
- `args` 不是 token 级增量流，也不承诺反映模型输出中的每个 chunk
- 如果 runtime 尚未拿到可解析的结构化参数，则该字段应保持 unset，而不是发送空 struct

这里的关键点是：对上层承诺“有则可靠，没有则缺失”，而不是“永远给个空对象，让调用方猜到底是无参数还是解析失败”。

2. `ToolResult`

- 保留现有 `content` 字段，作为向后兼容的人类可读文本投影
- 保留现有 `is_error`
- 新增一个可选的结构化原始结果字段，建议使用 `google.protobuf.Value payload`

选择 `Value` 而不是 `Struct`，是因为 tool result 在真实世界中可能是：

- object
- array
- string
- number / boolean / null

如果只给 `Struct`，仍然会把非对象结果排除在外，协议还是不完整。

因此，Phase 3A 的 protobuf 收敛建议是：

```proto
message ToolResult {
  string tool_call_id = 1;
  string content      = 2;
  bool   is_error     = 3;
  google.protobuf.Value payload = 4;
}
```

这里的语义约束建议明确为：

- `content` 是稳定保留的兼容文本字段
- `payload` 是原始 JSON-like 结果
- 当原始结果本身就是字符串时，`content` 与 `payload` 可以语义重复
- 当原始结果无法安全转为 JSON-like 值时，允许只填 `content`

这样做的好处是：

- 旧客户端不需要立刻升级
- 新客户端可以拿到原始结构化结果
- transport 层不再强制把一切 tool result 都降级成字符串

#### Phase 3A-3：runtime 实现方案

runtime 侧需要完成两件事。

1. `ToolCallStart.args` 稳定提取

当前 `streams.py` 中的 `tool_call_buffers` 只保存：

- `name`
- `id`

方案 A 需要将其扩展为至少包含：

- `name`
- `id`
- `args`
- `args_text` 或等价的 chunk buffer
- `started`

推荐行为如下：

- 如果 `content_block.type == "tool_call"` 且已经带有结构化 `args`，直接缓存并发出一次 `tool_call_start`
- 如果 `content_block.type == "tool_call_chunk"`，则按 `index/id` 聚合参数片段
- 当参数片段第一次被成功解析为稳定对象时，发出一次 `tool_call_start`
- 同一个 `tool_call_id` 只能发出一次 `tool_call_start`
- 如果直到 tool 真正执行前都拿不到可解析参数，也仍然可以发出 `tool_call_start`，但 `args` 字段保持 unset

这里最重要的语义收敛是：

- `tool_call_start` 是“一次性开始事件”
- 不是“每收到一个 chunk 就重复发一次”

2. `ToolResult.payload` 原样保留

当前 `_parse_tool_message()` 会把非字符串内容直接 `str(...)`。方案 A 需要改成：

- 先判断结果是否是 JSON-like 值
- 如果是，则在 runtime event 中保留原始 `payload`
- 同时生成 `content` 文本投影
- 如果不是，则退化为仅保留 `content`

推荐文本投影规则：

- 原始字符串：`content = 原字符串`
- 原始 JSON-like object/array：`content = 紧凑 JSON 字符串`
- 原始 number/bool/null：`content = 对应字符串形式`
- 非 JSON-like 对象：`content = str(value)`，`payload` 缺失

这样可以同时满足：

- CLI / timeline 继续显示文本
- 审计 / 调试 / 机器处理拿到原始结果

#### Phase 3A-4：control 实现方案

control 层当前已经有一个通用的 `AgentEvent.Payload`，问题在于 tool 事件路径上还没有真正用起来。

方案 A 下，control 的实现应尽量保持“最小 northbound churn”：

1. gRPC mapper

- `tool_call_start`：把 protobuf `args` 映射到 `AgentEvent.Payload`
- `tool_result`：把 protobuf `payload` 映射到 `AgentEvent.Payload`
- `tool_result.text` 继续来自 `content`

2. HTTP/SSE

- 不新增 `tool_args`、`tool_payload` 之类的新顶层字段
- 继续使用现有 `payload` 通用字段
- `tool_name`、`tool_call_id`、`text` 继续保留

这个做法的好处是：

- northbound contract 的增量最小
- web 不需要为每种 tool 事件单独追新字段
- 未来如果再有结构化事件，也可以继续复用 `payload`

#### Phase 3A-5：web 实现方案

web 侧不需要在 Phase 3A 一次性做复杂的新界面，但需要把“结构化信息已经存在”这个事实真正消费起来。

最低要求：

- `tool_call_start` 的 payload inspector 可以看到 args
- `tool_result` 的 payload inspector 可以看到结构化结果
- timeline 继续保留当前紧凑展示，不因为 payload 增加而改变主视图密度

可选增强，但不是本阶段必须项：

- 对 object/array 结果做 JSON pretty view
- 对文件写入、shell execute 等常见工具做更友好的摘要卡片
- 在 HITL / tool timeline 之间建立更明确的关联跳转

#### Phase 3A-6：兼容性与迁移策略

方案 A 的兼容性边界建议如下：

1. 向下兼容

- `ToolCallStart.tool_name`
- `ToolCallStart.tool_call_id`
- `ToolResult.content`
- `ToolResult.is_error`

这些已有字段必须继续保留。

2. 新能力采用 optional additive 方式

- `ToolCallStart.args` 继续保留，但改为真正有语义
- `ToolResult.payload` 作为新增 optional 字段
- control / web 允许忽略 `payload`

3. 不做的事情

- 不在 Phase 3A 改动 `ToolCallDone`
- 不在 Phase 3A 引入 `tool_call_delta`
- 不在 Phase 3A 让 northbound 事件类型继续分裂

这保证了本阶段是“补齐承诺”，而不是“继续扩大协议表面面积”。

#### Phase 3A-7：测试矩阵

方案 A 至少应补以下测试：

1. runtime parser

- `tool_call` 带完整结构化 args 时，`ToolCallStart.args` 正确写出
- `tool_call_chunk` 经聚合后，可以只发出一次 `tool_call_start`
- 无法解析 args 时，`ToolCallStart` 仍可发出，但 `args` 缺失
- `ToolMessage.content` 为 object/array/string/scalar 时，`ToolResult.payload` 与 `content` 语义正确

2. runtime protobuf roundtrip

- `ToolCallStart.args` 通过 protobuf 后保持不变
- `ToolResult.payload` 通过 protobuf 后保持不变

3. control mapper / HTTP

- `tool_call_start.payload` 能透传到 northbound
- `tool_result.payload` 能透传到 northbound
- 旧字段 `text/tool_name/tool_call_id` 保持不变

4. 进程内集成测试

- 至少覆盖一个带结构化 tool args 和结构化 tool result 的 run 主路径

#### Phase 3A-8：落地顺序

建议按以下顺序落地：

1. 先在 `runtime.proto` 中为 `ToolResult` 增加 `payload`
2. 再改 runtime parser，使 `ToolCallStart.args` 和 `ToolResult.payload` 真正可产出
3. 再改 control mapper / HTTP，停止丢弃 tool 事件 payload
4. 最后改 web inspector 展示与相关测试

这个顺序的好处是：

- 先把 southbound 真值建立起来
- 再逐层把信息往 northbound 打通
- 每一层都可以独立验证，不需要等 UI 才知道协议是否生效

### Phase 4：同步修正文档与注释

本阶段已完成以下收口：

- `runtime.proto` 注释乱码已清理，关键分段和字段语义已回填
- control / web 对 HITL、tool payload 的字段口径已与当前实现同步
- 本文档中的事件模型说明、测试结果和当前结论已更新到 Phase 3A 之后的真实状态
- timestamp 精度修复完成后，相关遗留描述也已同步回填

这一步的目的，是避免实现已经变化，而设计文档仍停留在旧语义，继续制造“看起来偏离设计”的误判。

## 当前结论

截至 2026-03-27，可以给出如下判断：

- `runtime.proto` 事件协议已经足以支撑当前 data layer 的基础执行主路径
- HITL 协议建模、runtime server 边界校验、tool payload 保真、timestamp 精度和 northbound 消费链路都已经完成收敛
- 当前已经没有明确的 southbound 协议遗留项需要继续阻塞后续阶段
- 后续工作可以聚焦在上层展示增强，而不是协议补洞

换句话说，当前状态更接近：

- “协议主路径已经收敛完成”

而不是：

- “协议仍停留在需要继续补 transport 欠账的阶段”

## 后续动作建议

建议后续按以下顺序推进：

1. 视产品需求决定是否继续做 tool result 的卡片化/摘要化 UI
2. 如果未来新增 runtime event 类型，继续坚持“southbound 真值 -> control 透传 -> web 最小消费 -> 文档同步”这条收敛路径
3. 只有在未来确实出现更高精度观测诉求时，再评估是否需要把 `RuntimeEvent.timestamp` 从 `float` 升级为更强的内部表达

这个顺序的好处是：

- 当前 southbound 协议已经稳定，可以避免再次扩散为跨层协议漂移
- 后续 UI 增强可以作为上层能力建设，与协议稳定性分离推进
- 更高精度的内部时间表达只有在确有需求时才值得引入，避免过度设计
