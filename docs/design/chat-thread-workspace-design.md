# Chat Thread Workspace 设计

> 状态：Draft
> 最后更新：2026-04-01
> 范围：chat 文件上传、thread 工作目录、runtime 文件系统 contract
> 落地状态：设计中，尚未实现

## 1. 背景

当前 runtime 已经具备以下基础能力：

- agent 级 `runtime/` 目录
- `memory`、`skills`、`conversation_history`、`workspace` 等运行时资源目录
- runtime assemble 时为 agent 构建本地或 sandbox backend
- chat 会话通过 `thread_id` 进行 checkpoint 恢复

当前缺口不在“能不能保存文件”，而在“chat 文件上传后，agent 看到的文件世界是否自然一致”。

典型问题如下：

- 用户上传 `A.txt` 后，希望 agent 直接 `ls` 或 `cat A.txt` 就能找到它
- 不同 LLM 对 prompt 中“工作区在 `/workspace`”这类约定的遵从度不稳定
- shell 默认使用当前工作目录语义，而 file tool 当前更偏绝对路径语义
- 多 thread 上传后，需要明确文件是 agent 级共享还是 thread 级隔离

如果不先收敛这套 contract，上传功能虽然可以“落盘”，但 agent 的使用体验会不稳定。


## 2. 设计目标

- 用户上传文件后，agent 最自然的首选操作即可命中该文件
- tool 和 shell 围绕同一个 thread 工作目录建模
- `memory`、`skills`、`conversation_history` 仍然以文件形态存在
- `memory`、`skills`、`conversation_history` 不污染用户主工作区
- 多 thread 文件系统天然隔离
- runtime 负责文件系统 contract，不依赖 prompt compliance
- docker sandbox 下路径语义与 local 尽量一致


## 3. 非目标

- 不在本轮设计中彻底解决 local shell 可访问宿主机绝对路径的问题
- 不在本轮设计中做 memory 的跨 thread 自动合并
- 不在本轮设计中实现 directory upload 或 drag/drop 交互
- 不在本轮设计中改造 SDK 公共 `FilesystemMiddleware` 的默认行为


## 4. 核心决策

### 4.1 当前 thread 根目录就是 agent 的主工作区

主工作区不再暴露为 `/workspace/...`。

对于当前 thread：

- tool 的根目录语义就是 thread 工作根
- shell 的 `cwd` 也是同一个 thread 工作根

这意味着：

- tool `ls(".")` 等价于 shell `ls`
- tool `read_file("A.txt")` 等价于 shell `cat A.txt`
- tool `write_file("out/result.json")` 等价于 shell 在当前目录下写 `out/result.json`

这里不再追求 tool `/` 与 shell 真实 `/` 等价，而是明确追求：

- tool 根目录语义
- shell 当前工作目录语义

保持一致。

### 4.2 系统文件收敛到隐藏目录 `.runtime/`

每个 thread 工作根下保留一个隐藏系统目录：

```text
.runtime/
  memory/
    AGENTS.md
  skills/
    <skill>/
      SKILL.md
      ...
  conversation_history/
    ...
```

这样：

- 用户上传和 agent 生成的普通文件直接位于工作根
- system 区仍然能通过普通 file tool 访问
- `memory`、`skills`、`conversation_history` 仍然保持文件语义
- `ls` 的默认输出不会被 runtime 目录结构污染

### 4.3 `memory` 使用 thread snapshot

本设计明确接受：

- `memory` 在 thread 创建时从 agent canonical memory 初始化
- 之后该 thread 内 `.runtime/memory/AGENTS.md` 独立存在
- thread 内的 memory 编辑不自动回写其它 thread

这使得 memory 语义与 thread 工作区保持一致。

### 4.4 `skills` 使用 thread snapshot

本设计同样接受：

- thread 创建时把当前 agent skills snapshot materialize 到 `.runtime/skills/`
- 老 thread 使用其创建时的 skill snapshot
- 新 thread 获取最新的 skill snapshot

这样：

- skill 始终可通过 `read_file` 访问
- docker / local / 未来 k8s 都能使用同一套文件语义
- 不要求 runtime 在长生命周期 thread 中做 skill 热更新

### 4.5 runtime 不再直接走 SDK 的 `create_deep_agent` 默认文件栈

当前 SDK 的 [create_deep_agent](/Users/jpan/project/deepagents/libs/deepagents/deepagents/graph.py) 会隐式装配 `FilesystemMiddleware`。

但本设计需要的 contract 是：

- tool 使用当前 thread root 的相对路径
- shell 也围绕当前 thread root 的 `cwd`

这与 SDK 当前默认的文件路径模型并不完全一致。

因此 runtime 需要：

- 保留 SDK 中可复用的其它 middleware / graph 组装能力
- 但自行组装 runtime 专用文件 middleware
- 不再直接依赖 `create_deep_agent` 的默认文件系统入口


## 5. 物理目录结构

建议将 agent runtime layout 调整为：

```text
agents/{agent_name}/
  agent.yaml
  runtime/
    threads/
      <thread_id>/
        A.txt
        src/
        .runtime/
          memory/
            AGENTS.md
          skills/
            <skill>/
              SKILL.md
              ...
          conversation_history/
            history.md
```

说明：

- `threads/<thread_id>/` 就是当前 thread 的工作根
- 普通上传文件、agent 生成文件、临时工作文件都在这里
- `.runtime/` 是该 thread 的隐藏系统区

### 为什么不用 `runtime/workspace/<thread_id>/`

因为在 chat 上传场景里，最自然的交互是：

- 用户上传 `A.txt`
- agent `ls`
- agent 直接看到 `A.txt`

如果还保留显式 `workspace/` 这一层，就会要求模型先记住“当前真正工作区在 `/workspace`”，这会放大不同模型的行为差异。

### 为什么把 `.runtime/` 放在 thread 根里

因为这样每个 thread 是一个完整快照：

- 普通文件
- thread memory snapshot
- thread skill snapshot
- thread conversation history

删除 thread 时直接删整个目录即可。


## 6. Tool / Shell 路径 Contract

### 6.1 tool 只接受相对路径

runtime 专用文件 middleware 采用以下规则：

- 普通文件工具只接受相对路径
- 默认路径为 `.`
- 禁止绝对路径
- 禁止 `..`
- 禁止 `~`

示例：

- `ls(".")`
- `read_file("A.txt")`
- `write_file("out/result.json")`
- `edit_file(".runtime/memory/AGENTS.md", ...)`
- `read_file(".runtime/skills/web-research/SKILL.md")`

### 6.2 shell 使用当前 thread 工作根作为 `cwd`

shell 规则：

- `cwd = threads/<thread_id>/`
- 相对路径是推荐 contract
- local 下 shell 仍然可能访问宿主机绝对路径，但这不属于 tool contract

### 6.3 不再暴露 `/workspace` 风格的可见路径

在本设计中，不再将上传文件的标准路径表达为：

- `/workspace/A.txt`

而是直接表达为：

- `A.txt`

或在描述工作根时表达为：

- 当前 thread 工作目录下的 `A.txt`


## 7. Runtime Backend 设计

### 7.1 不使用 agent 级单例、可变状态的 thread binding backend

不建议继续保留这种模型：

- agent 持有一个 `_tool_backend`
- 每次 run / upload 前调用 `bind_thread(thread_id)`
- backend 内部保存当前 thread 的可变状态

这种模型的问题：

- 并发上传容易串线
- 一个 upload 和一个 run 会互相覆盖当前 thread
- 后续很难做并发控制和正确清理

### 7.2 使用 thread-bound backend 实例

推荐改成：

- `make_thread_backend(agent_name, thread_id)`

该 backend 是 thread-bound 的、不可变的 runtime object：

- root = `threads/<thread_id>/`
- shell cwd = `threads/<thread_id>/`
- tool file operations 也绑定到该 root

每次 run / upload / 文件 staging 都拿当前 thread 的 backend，不与其它 thread 共享运行时可变状态。


## 8. Runtime Graph 组装

runtime 需要自建 graph builder，例如：

- `build_runtime_agent_graph(...)`

其职责：

- 创建 model
- 创建 runtime 专用 filesystem middleware
- 创建 memory / skills / summarization middleware
- 创建 subagent middleware
- 编译 runnable graph

建议继续复用 SDK 中这些中间件或能力：

- `TodoListMiddleware`
- `PatchToolCallsMiddleware`
- `AnthropicPromptCachingMiddleware`
- `SubAgentMiddleware`
- `SummarizationToolMiddleware`

但文件系统部分应切换为 runtime 自己的专用实现。


## 9. Runtime 专用 Filesystem Middleware

建议新增一个 runtime 专用 filesystem middleware，而不是直接修改 SDK 公共 `FilesystemMiddleware` 的默认契约。

原因：

- SDK 是公共接口，现有用户已经依赖绝对路径 contract
- runtime 需要的是 thread-rooted 的 chat 交互模型
- 这两套语义不适合硬合并

runtime 专用 filesystem middleware 应具备：

- 相对路径输入 contract
- 与当前 thread backend 配套
- 与 shell cwd 一致的根语义
- `ls`、`read_file`、`write_file`、`edit_file`、`glob`、`grep`、`execute`


## 10. Upload 流程

### 10.1 输入

northbound upload API 输入：

- `agent_name`
- 可选 `thread_id`
- `files[]`

### 10.2 行为

如果未提供 `thread_id`：

- runtime 生成一个新的 `thread_id`
- 初始化 `threads/<thread_id>/`
- 初始化 `.runtime/memory`
- 初始化 `.runtime/skills`
- 初始化 `.runtime/conversation_history`

然后将上传文件直接写入：

- `threads/<thread_id>/`

### 10.3 返回值

建议 upload API 返回：

- `thread_id`
- 每个文件的相对路径，如：
  - `A.txt`
  - `docs/spec.pdf`

不要再返回 `/workspace/A.txt` 这类路径。


## 11. Summarization History

summarization offload 路径统一收口到：

- `.runtime/conversation_history/...`

这意味着：

- 当前 thread 的摘要历史是 thread-local
- 默认不和其它 thread 共享
- tool 可以按需通过相对路径访问


## 12. Session 生命周期与清理

### 12.1 删除 session

删除 session 时，除了删 checkpoint，还应删除：

- `threads/<thread_id>/`

这会同时清理：

- 上传文件
- thread memory snapshot
- thread skill snapshot
- thread conversation history

### 12.2 删除 agent

删除 agent 时删除整个：

- `agents/{agent_name}/runtime/threads/`

以及其余 agent runtime 目录。


## 13. Docker 语义

本设计对 docker 更友好。

可以直接将：

- `threads/<thread_id>/`

挂载到容器中的：

- `/workspace`

容器内 contract：

- cwd = `/workspace`
- 上传文件在 `/workspace/A.txt`
- memory 在 `/workspace/.runtime/memory/AGENTS.md`
- skills 在 `/workspace/.runtime/skills/...`
- history 在 `/workspace/.runtime/conversation_history/...`

这与 local 的 thread-root contract 一致。


## 14. 与现方案的关键差异

### 不采用的方案

- tool 暴露显式 `/workspace`、`/memory`、`/skills`、`/conversation_history` 四个并列前缀
- `ls /` 返回这些前缀目录
- 通过 prompt 告诉模型“上传文件在 `/workspace/...`”

不采用原因：

- 上传文件不在 agent 的默认工作目录心智模型中
- 需要模型额外记住 `/workspace` 这一层
- tool 与 shell 的日常使用习惯仍然分裂

### 采用的方案

- 当前 thread 根目录就是主工作区
- 系统文件在隐藏目录 `.runtime/`
- tool 与 shell 围绕同一个 cwd-root 建模


## 15. 实施顺序

建议按以下顺序落地：

1. 调整 runtime 物理目录结构为 `runtime/threads/<thread_id>/`
2. 去掉显式 `/workspace` 的可见路径设计
3. 引入 thread-bound backend，不再使用 agent 级 mutable bind-thread backend
4. 新增 runtime 专用 filesystem middleware，改成相对路径 contract
5. runtime 自建 graph，不再直接走 SDK 默认 `create_deep_agent` 文件栈
6. upload API 返回相对路径
7. 删除 session 时补充 thread 目录清理
8. 最后补齐 unit / integration tests


## 16. Open Questions

当前建议如下，后续可根据实现再细化：

- memory canonical source 是否仍保留 agent 级定义：保留
- thread 创建时 memory/skills 是否全量 snapshot：是
- 老 thread 是否在 agent skill 更新后热更新：否
- upload 是否允许覆盖同名文件：待定，建议显式定义
- chat UI 是否展示相对路径标签：是


## 17. 总结

本设计的核心不是“多一个上传接口”，而是定义一套稳定的 thread 工作目录 contract：

- thread 根目录就是主工作区
- `.runtime/` 是隐藏系统区
- tool 和 shell 围绕同一个 cwd-root 工作
- `memory` 和 `skills` 都以 thread snapshot 文件存在
- runtime 自己掌控 graph 文件栈，不再依赖 SDK 默认文件中间件

这套模型最符合 chat 上传场景，也最适合 docker sandbox 的长期演进。
