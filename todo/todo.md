更新：2026-03-12（同步）

【当前状态】（以本节为准）

- ✅ Agent Factory：已抽到 runtime（`deepagents_runtime.agent_factory` 提供 `get_system_prompt()` / `create_agent()`；CLI `create_cli_agent()` 已委托 runtime）
- ✅ Session Service：已补 `get_thread_history()`（thread history hydration 已从 Textual 迁到 runtime `SessionStore`）
- ✅ Run Service：已实现统一 runtime 入口（`deepagents_runtime.inputs.InputEnvelope` + `deepagents_runtime.run_service.stream_run_events()`；支持 `normal/command/bash`；补齐 doc-required events：`run.*`/`message.*`/`tool.*`/`approval.*`/`bash.*`/`thread.*`/`usage.updated`）。CLI non-interactive + Textual（normal）+ Textual（bash/`!command`）已迁移
- ✅ Command Mode：Textual slash commands 已统一走 run service 的 `mode=command`（`InputEnvelope(mode="command")` + `stream_run_events()`）；UI 侧消费 `command.*`/`thread.*`/`message.*`
- ✅ Approval Service：runtime `ApprovalService` 提供 run_id + thread_id 维度的 durable approval state（pending requests + per-thread auto-approve），可支持 refresh/reconnect 场景
- ✅ Shell(`!command`)：Textual `!command` 已并入 run service 的 `mode=bash`（渲染 `bash.*` + `run.*`）
- ✅ Attachments：`mode=normal` 已支持 `InputEnvelope.attachments`（images -> `image_url` blocks；files -> 追加引用文本）；Textual images 已改为走 attachments（videos 暂时仍走 `user_message_content` override）
- ✅ `deepagents_runtime.models`：新增 client-neutral model helpers（`provider:model` parse、provider detection、default/recent persistence 到 `~/.deepagents/config.toml`）
- ✅ `deepagents_runtime.sandboxes`：新增 runtime sandbox lifecycle（provider resolver + setup script runner + default working dir mapping；CLI sandbox_factory 已委托 runtime + hooks 保持输出语义）
- 🧱 未开始：Phase 2/3/4（FastAPI server / browser client / parity closure）

对照文档：`libs/cli/doc/browser-cli-architecture.md`

【验证】（2026-03-12）

- ✅ `libs/runtime`：`ruff check` / `pytest`（unit）通过
- ✅ `libs/cli`：`ruff check` / `pytest`（unit）通过（并清理 `test_thread_selector` 的 unawaited coroutine warning）

【剩余缺口（按优先级）】

1) Phase 2：FastAPI server + APIs + SSE event stream
2) Phase 3：browser client
3) Phase 4：parity closure + cross-client regression tests

【备注】

- Windows：如果 `uv run` / `uv` cache / `.ruff_cache` 遇到 `os error 5 / Access is denied`，优先用各包的 `.venv/Scripts/pytest.exe` / `ruff.exe` 跑验证。
