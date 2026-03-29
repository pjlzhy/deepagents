# Skill Upload Snapshot Design

## 背景

当前 control plane 已经将 skill 作为目录快照存储到 registry 中，内部 canonical 结构为：

- `content`: 根 `SKILL.md`
- `files[]`: skill 目录中的其他文件，使用相对路径表示

这套内部结构已经足以表达多文件、嵌套目录的 skill，例如 `pcap-analyzer/` 这类包含 `scripts/`、`references/` 和更深层子目录的 skill。

当前缺口不在 runtime/control 的底层表达能力，而在 northbound authoring 链路：

- Skill UI 仍然依赖 `filesJson` 文本框录入附属文件
- UI 将 skill 视为“字段表单”，而不是“目录快照”
- 这不符合本地开发、测试、再上传平台的真实工作流

本设计将 skill 收敛为“上传型目录快照资源”，并以 Agent Skills Specification 为约束来源。

规范参考：

- https://agentskills.io/specification


## 目标

- 按 Agent Skills Specification 支持目录型 skill 上传
- 使用 `zip` 作为唯一新增/覆盖输入载体
- 将 `SKILL.md` frontmatter 作为 skill 规范元数据的唯一来源
- UI 不再承担 skill 文本文件编辑器角色，只负责上传、预览、展示和替换
- 保持 runtime 当前的 `content + files[]` 快照装配链路不变


## 非目标

- 不支持 skill 二进制文件
- 不支持在 UI 内直接编辑 `SKILL.md`、脚本或 references 文件
- 不做 skill 增量 patch；上传始终是全量替换
- 不引入 `scripts`、`references`、`assets` 等一等字段；它们仍然只是目录约定


## 规范对齐

### 目录结构

根据 Agent Skills Specification，skill 的最小单位是一个目录，至少包含：

- `SKILL.md`

可选包含：

- `scripts/`
- `references/`
- `assets/`
- 其他附加文件和目录

平台不对这些可选目录做 schema 分裂，统一视为 skill 目录快照中的普通文件路径。

### `SKILL.md`

`SKILL.md` 必须包含：

- YAML frontmatter
- Markdown body

### frontmatter 字段

按规范识别的标准字段：

- `name`
- `description`
- `license`
- `compatibility`
- `metadata`
- `allowed-tools`

其中：

- `name`、`description` 为必需字段
- `allowed-tools` 按规范仍属于 experimental 字段

### 名称约束

按规范要求，`name` 必须匹配 skill 父目录名。

平台在 zip 导入时也沿用这一约束：

- 如果 zip 中存在单个顶层包装目录，则该目录名必须与 frontmatter `name` 一致
- 如果 zip 根目录直接包含 `SKILL.md`，则以 frontmatter `name` 作为 skill 注册名


## 核心设计决策

### 1. Skill 改为 upload-only 资源

Phase 1 中，skill 不再通过网页表单逐字段编辑。

允许的修改方式只有两种：

- 上传 zip 新增 skill
- 对已有 skill 重新上传 zip，全量覆盖

不支持：

- 在 UI 中编辑 `SKILL.md`
- 在 UI 中编辑脚本或 references
- 在 UI 中手工修改 metadata

### 2. 规范元数据与平台元数据分离

`SKILL.md` frontmatter 是 skill 规范元数据的唯一来源，负责定义“这个 skill 是什么”。

规范元数据包括：

- `name`
- `description`
- `license`
- `compatibility`
- `metadata`
- `allowed-tools`

control plane 平台元数据单独维护，负责定义“这个 skill 在平台里的状态是什么”。

平台元数据至少包括：

- `created_at`
- `updated_at`
- `status`

说明：

- `status` 不是 Agent Skills spec 的标准字段
- Phase 1 中不在 `SKILL.md` 中扩展 `status`
- 上传成功后的 skill 使用平台默认 `status`
- 当前建议默认 `published`

### 3. 内部 canonical model 保持不变

尽管 northbound 改为 zip 上传，control/runtime 内部仍保持：

- `content = SKILL.md`
- `files[] = 其他文本文件`

这保证：

- control resolver / packager 无需改 skill 引用模型
- runtime registry 继续按现有逻辑还原 skill 目录
- Agent 运行时继续从本地 skill 目录读取脚本与 references

### 4. 只支持文本文件

Phase 1 中 zip 只是上传容器，不代表 skill 开始支持任意二进制附件。

解包后的附属文件必须满足：

- 可按 UTF-8 文本读取

否则上传失败。


## Zip 上传语义

### 新增

`Create Skill` 语义为“上传一个 zip 并创建 skill”。

skill 名称不从 URL 或表单输入获得，而是从 `SKILL.md` frontmatter 的 `name` 字段解析。

### 覆盖

`Replace Skill` 语义为“上传一个 zip 并全量替换已有 skill 快照”。

替换时必须校验：

- zip 中 frontmatter `name` 与目标 skill 名一致

不允许通过 replace 完成 rename。

### 替换粒度

replace 为全量替换：

- 新 `SKILL.md` 覆盖旧 `content`
- 新文件集覆盖旧 `files[]`
- 旧快照中存在、但新包中缺失的文件会被移除

不做 merge，不保留陈旧文件。


## Zip 包结构规则

### 接受的输入形式

平台接受两种 zip 结构：

1. zip 根目录直接是 skill 内容

```text
SKILL.md
scripts/...
references/...
```

2. zip 最外层包一层同名目录

```text
pcap-analyzer/
  SKILL.md
  scripts/...
  references/...
```

服务端在导入时统一归一化为 skill 根目录快照。

### `SKILL.md` 约束

必须满足：

- 解包结果中存在且只存在一个 `SKILL.md`
- `SKILL.md` 位于 skill 根目录
- frontmatter 可解析

### 路径规则

写入 `files[]` 前必须完成归一化：

- 使用相对路径
- 分隔符统一为 `/`
- 禁止 `..` 路径逃逸
- 禁止重复目标路径
- `SKILL.md` 不进入 `files[]`


## Ignore 与 Reject 规则

### 默认忽略

导入时默认忽略以下文件或目录：

- `.DS_Store`
- `__pycache__/`
- `*.pyc`
- `.git/`
- `.idea/`
- `.venv/`

这些文件不会进入 registry snapshot，也不会触发失败。

### 直接拒绝

出现以下情况时直接拒绝上传：

- 缺少 `SKILL.md`
- 存在多个 `SKILL.md`
- frontmatter 缺失或解析失败
- `name` 为空
- `description` 为空
- top-level 包装目录名与 `name` 不一致
- 替换时 `name` 与目标 skill 名不一致
- 任一文件不是有效 UTF-8 文本
- 存在路径逃逸
- 存在重复路径
- 超过服务端配置的单文件大小、总解包大小或文件数限制


## Metadata 解析与展示

### Source of Truth

UI 和 northbound read API 中展示的 skill 规范元数据来自 `SKILL.md` frontmatter 解析结果，不来自手工填写表单。

### Phase 1 展示字段

Skill list / detail 页面展示以下 frontmatter 字段：

- `name`
- `description`
- `license`
- `compatibility`
- `metadata`
- `allowed-tools`

平台字段单独展示：

- `status`
- `created_at`
- `updated_at`

### 关于 tags

Agent Skills Specification 不定义标准 `tags` 字段。

因此：

- Phase 1 中 UI 不再把 `tags` 视为 skill 标准 metadata
- 如需表达分类标签，应通过 frontmatter `metadata` 扩展承载
- 现有 control-plane `tags_json` 视为 legacy 字段，不作为新 UI 的 authoring source


## Northbound API 设计

### 新增接口

建议新增 upload-oriented 接口：

- `POST /api/v1/skills/package`
  - `multipart/form-data`
  - 上传 zip 并创建 skill

- `PUT /api/v1/skills/{name}/package`
  - `multipart/form-data`
  - 上传 zip 并全量替换 skill

- `GET /api/v1/skills/{name}/package`
  - 下载当前 skill 快照 zip

### 继续保留接口

建议继续保留：

- `GET /api/v1/skills`
- `GET /api/v1/skills/{name}`
- `DELETE /api/v1/skills/{name}`

### 现有 JSON upsert 接口

当前 `PUT /api/v1/skills/{name}` 的 JSON upsert 形态不适合作为 UI 主链路。

Phase 1 建议：

- UI 不再使用该接口
- 服务端可暂时保留为兼容/内部接口
- 后续视实现情况决定是否废弃


## Read API 语义调整

### List API

`GET /api/v1/skills` 返回 skill summary，而不是完整快照内容。

建议字段：

- `name`
- `description`
- `status`
- `updated_at`
- `license`
- `compatibility`
- `file_count`
- `snapshot_digest`

不返回：

- `SKILL.md` 正文
- `files[]` 正文

### Detail API

`GET /api/v1/skills/{name}` 返回 skill detail，只读展示用。

建议字段：

- summary 字段
- `skill_md`
- `frontmatter`
- `file_manifest[]`
  - `path`
  - `size`
  - `sha256`

仍不返回完整 `files[]` 正文。

说明：

- UI 不负责在线编辑脚本正文
- 完整快照通过 package download 获取
- control runtime packing 仍直接使用内部存储的完整 `content + files[]`


## UI 设计

### Skills 列表页

列表页动作收敛为：

- `Upload Skill`
- `View`
- `Replace`
- `Download`
- `Delete`

不再提供：

- `Edit Skill` 表单

### Upload / Replace Drawer

抽屉只负责：

- 选择 zip 文件
- 本地上传
- 服务端解析预览
- 用户确认提交

抽屉内不提供代码编辑能力。

### 预览内容

上传后、提交前展示：

- 解析出的 frontmatter
- `SKILL.md` 预览
- 文件树快照
- 文件数
- warnings（若有）

### Skill Detail

详情页/抽屉只读展示：

- skill metadata
- `SKILL.md` 预览
- 文件树
- package download
- replace snapshot


## Control Plane 内部影响

### 存储

Phase 1 不强制修改当前 skill 表的 canonical 存储方式。

当前结构仍可继续使用：

- `content TEXT`
- `files_json TEXT`

原因：

- 当前只支持文本文件
- runtime 打包与落盘链路已经兼容该结构

### 元数据派生

上传或替换时，服务端解析 `SKILL.md` frontmatter，并派生：

- `name`
- `description`

以及 detail/list 所需的其他规范字段。

Phase 1 中可采用“上传时解析 + 读取时按需再解析”的方式，避免立即推动 skill 表 schema 重构。

### Packager / Runtime

skill 引用解析与 runtime 装配逻辑保持不变：

- control resolver 继续解析 skill refs
- control packager 继续输出 `content + files[]`
- runtime registry 继续将快照还原为本地目录


## 运行时影响

对 runtime 的唯一约束是：

- 解包后写入 registry 的 `files[]` 仍然全部是 UTF-8 文本文件

因此 Phase 1 中 runtime 无需引入二进制 skill file 支持。


## 迁移策略

### UI 迁移

- 移除 Skill Editor 中的 `content` / `filesJson` 手工编辑入口
- 切换到 upload/replace drawer

### API 迁移

- 新 UI 仅使用 package upload/download 接口
- 现有 JSON upsert 接口暂时保留，不作为主路径

### 数据兼容

已存在的 skill 记录继续兼容：

- 仍可读取 `content`
- 仍可读取 `files_json`

新的 read API 只是在 northbound 展示语义上改为 manifest-first，而不是改变内部 canonical shape。


## 待实现项

### 后端

- zip 上传解析
- `SKILL.md` frontmatter 校验
- 文本文件 UTF-8 校验
- ignore / reject 规则
- package upload / download 接口
- summary/detail 响应裁剪

### 前端

- skills 列表页按钮与文案调整
- upload/replace drawer
- skill detail 只读展示
- 文件树组件
- package 下载入口


## 开放问题

### 1. `status` 默认值

当前建议为：

- upload 成功后默认 `published`

如未来需要审核流，可在 control plane 内部扩展，不进入 `SKILL.md` spec metadata。

### 2. detail API 是否返回 `SKILL.md` 正文

当前建议为：

- 返回 `SKILL.md`
- 不返回附属文件正文

这是为了兼顾只读预览与 payload 控制。

### 3. 是否支持 `.skillignore`

Phase 1 不支持。

先使用平台内置 ignore 规则，后续如出现真实需求，再引入自定义忽略文件。
