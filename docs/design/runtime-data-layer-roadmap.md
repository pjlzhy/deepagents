  # Runtime Data 层 Roadmap

  > 状态：Draft
  > 最后更新：2026-03-18

  ## 概述

  `libs/runtime` 中的 Runtime Data 层，本质上是 Agent OS 的 `Agent Engine`。

  它的职责是接收来自 control plane 的富 `AgentSpec`，将其装配为可运行的 graph，管理 run 级别的运行时资源，并通过 gRPC 暴露执行入口。

  control plane 负责 registry CRUD、资源打包和资源分发。data plane 不承担系统级资源仓库的职责。

  ## 当前状态

  当前实现已经具备 runtime 的基础骨架：

  - 已实现 `Run`、`SyncAgentSpec`、`Assemble`、`Health` 等 gRPC 服务
  - 已实现 protobuf 请求到内部 runtime spec 的转换
  - 已实现 `AgentSpec -> AgentTemplate -> graph` 的装配主链路
  - 已实现 agent 本地运行目录，包括 skills、memory、workspace 等
  - 已接入基于 SQLite 的 checkpoint 持久化
  - 已具备基础的流式执行、HITL 和 cancel 能力

  这说明 data 层已经可以作为执行引擎工作，但距离“完整闭环、可稳定演进的 runtime”还有一段距离。

  ## 待补齐内容

  当前剩余工作重点，不是架构方向调整，而是契约收敛和运行时闭环补齐。

  ### 1. 文档收敛

  当前代码路径已经默认采用“富 `AgentSpec`”模型，但设计文档和部分 proto 注释仍然保留了较多“资源逐项同步到 data plane 本地 registry”的旧描述。

  需要将文档、协议意图和现有实现边界统一起来，明确：

  - data plane 的输入是富 `AgentSpec`
  - control plane 负责资源 registry 和打包
  - data plane 不再承担系统级 skills / MCP registry 语义

  ### 2. 富 `AgentSpec` 的完整消费

  目前 proto 中已经定义了较丰富的字段，converter 也已经完成了解析，但 assembly 还没有完整消费这些字段。

  主要包括：

  - `prompt.memory`
  - `tools.builtins`
  - `tools.mcp`
  - 更完整的 `subagents` 元数据
  - `tools.mcp` 与 `mcp_servers` 的关系收敛

  目标是让 runtime 真正根据完整 spec 构建行为，而不是只消费当前已接入的一部分字段。

  ### 3. 统一 Run 生命周期

  当前对外 gRPC `Run` 路径和 manager 内部的 invoke 路径还没有完全统一。

  runtime 需要形成唯一的 run 生命周期入口，统一管理：

  - run setup
  - run teardown
  - cancel 行为
  - timeout 处理
  - error cleanup
  - run 级资源获取与释放

  ### 4. 补齐 run 级资源生命周期

  MCP 和 sandbox 目前还没有完全成为闭环的 runtime 资源。

  需要补齐的内容包括：

  - MCP client lifecycle 管理
  - assembly 阶段 MCP 装配与 run 阶段 MCP 持有关系的职责划分
  - 让 `SandboxSpec` 真正驱动 backend 选择
  - 明确 local、Docker、K8s 等执行后端的支持能力与语义

  ### 5. 补齐运行时元数据与可观测性

  当前 session metadata 和 health reporting 仍然偏基础，尚不足以支撑完整的 runtime 管理与诊断。

  需要补齐的内容包括：

  - thread 归属信息
  - 更新时间戳
  - assembled / running 状态
  - 基于 checkpoint 的 thread 查询
  - health / readiness 的准确状态输出

  ### 6. 测试覆盖补齐

  当前 runtime 这一层缺少足够直接的测试覆盖。

  在 data 层被视为稳定能力之前，需要为 assembly、execution、checkpoint、HITL、cleanup 等关键路径补齐回归保护。

  ## 时间表

  ### Phase 1：设计文档收敛 （已完成）

  **2026-03-18 至 2026-03-18**

  目标：

  - 冻结以富 `AgentSpec` 为中心的 runtime 边界
  - 统一 control plane / data plane 职责口径
  - 更新设计文档，使其与当前实现边界一致
  - 更新 proto 注释，去掉旧的资源逐项同步语义
  - 明确 `SyncSkill` 和 `SyncMcp` 是兼容接口还是后续弃用接口

  ### Phase 2：装配能力补齐

  **2026-03-19 至 2026-03-19**

  目标：

  - 完整接入 `prompt.memory`
  - 让 `tools.builtins` 真正参与 runtime assembly
  - 收敛 `tools.mcp` 与 `mcp_servers` 的语义关系
  - 补齐 subagent 相关装配逻辑

  ### Phase 3：执行路径统一

  **2026-03-20 至 2026-03-24**

  目标：

  - 让 gRPC `Run` 走统一的 manager 执行路径
  - 将 run setup / teardown 收敛到单一生命周期入口
  - 统一 cancel、timeout、error 场景下的清理逻辑

  ### Phase 4：资源生命周期补齐

  **2026-03-25 至 2026-03-27**

  目标：

  - 完成 MCP runtime lifecycle 管理
  - 收敛 graph 装配与 run 级 MCP 持有关系
  - 让 sandbox backend 选择真正受 `SandboxSpec` 驱动
  - 明确支持的执行 backend 及其语义边界

  ### Phase 5：元数据与健康状态补齐

  **2026-03-30 至 2026-04-01**

  目标：

  - 完善 thread 和 session metadata
  - 让 health 输出反映真实 assembled / running 状态
  - 完成基于 checkpoint 的 runtime 状态查询能力

  ### Phase 6：稳定性与验证

  **2026-04-02 至 2026-04-09**

  目标：

  - 为 converters、assembly、sessions、manager 增加单元测试
  - 为 `SyncAgentSpec -> Assemble -> Run` 增加集成测试
  - 验证 HITL、cancel、checkpoint resume、cleanup 等关键路径
  - 完成文档、协议与代码行为的最终收口

  ## 风险

  主要风险不在 runtime 骨架本身，而在收敛过程。

  - 如果文档继续描述旧的资源同步模型，后续实现即使方向正确，也会不断被误判为“偏离设计”
  - 如果 `tools.mcp` 与 `mcp_servers` 的语义长期不清晰，assembly 层会越来越难维护
  - 如果 run 生命周期入口不统一，后续每新增一个 runtime 能力，都会放大清理和一致性风险
  - 如果在扩展能力前不补齐测试覆盖，回归风险会快速上升

  ## 目标结果

  当本 roadmap 完成后，Runtime Data 层应当成为一个完整的 Agent Engine，具备以下特征：

  - 契约稳定
  - 装配完整
  - 生命周期一致
  - 状态可观测
  - 行为可回归验证

  届时，control plane 可以将 data plane 视为稳定的执行底座，而不是一个尚未完全闭环的 runtime 骨架。