export type ApiErrorResponse = {
  error: string;
};

export type NumberPageMeta = {
  page_size?: number;
  page_number?: number;
  total_size?: number;
  total_pages?: number;
};

export type CursorPageMeta = {
  next_page_token?: string;
};

export type HealthResponse = {
  status?: string;
  assembled_agent_count?: number;
  installed_agent_count?: number;
  running_agent_count?: number;
  uptime_seconds?: number;
  ready: boolean;
};

export type ModelConfigDTO = {
  name?: string;
  description?: string;
  provider?: string;
  model?: string;
  base_url?: string;
  api_key_env?: string;
  extra_params?: Record<string, string>;
  status?: string;
  created_at?: string;
  updated_at?: string;
};

export type ModelConfigUpsertRequestDTO = {
  description?: string;
  provider?: string;
  model?: string;
  base_url?: string;
  api_key_env?: string;
  extra_params?: Record<string, string>;
  status?: string;
};

export type ModelConfigListDTO = NumberPageMeta & {
  models: ModelConfigDTO[];
};

export type SkillFileDTO = {
  path?: string;
  content?: string;
};

export type SkillDTO = {
  name?: string;
  description?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  license?: unknown;
  compatibility?: unknown;
  metadata?: unknown;
  allowed_tools?: unknown;
  file_count?: number;
  snapshot_digest?: string;
};

export type SkillUpsertRequestDTO = {
  description?: string;
  tags?: string[];
  content?: string;
  files?: SkillFileDTO[];
  status?: string;
};

export type SkillFileManifestDTO = {
  path?: string;
  size?: number;
  sha256?: string;
};

export type SkillDetailDTO = SkillDTO & {
  skill_md?: string;
  frontmatter?: Record<string, unknown>;
  file_manifest: SkillFileManifestDTO[];
};

export type SkillListDTO = NumberPageMeta & {
  skills: SkillDTO[];
};

export type MCPConfigDTO = {
  name?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  transport?: string;
  description?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
};

export type MCPConfigUpsertRequestDTO = {
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  transport?: string;
  description?: string;
  status?: string;
};

export type MCPConfigListDTO = NumberPageMeta & {
  mcps: MCPConfigDTO[];
};

export type PromptSpecDTO = {
  system?: string;
};

export type ModelSpecDTO = {
  provider?: string;
  model?: string;
  base_url?: string;
  api_key_env?: string;
  extra_params?: Record<string, string>;
};

export type SubagentSpecDTO = {
  name?: string;
  description?: string;
  system_prompt?: string;
  model: ModelSpecDTO;
};

export type SandboxSpecDTO = {
  image?: string;
  resources?: Record<string, string>;
  init?: string[];
};

export type AgentSpecDTO = {
  name?: string;
  version?: string;
  description?: string;
  tags?: string[];
  model_ref?: string;
  prompt: PromptSpecDTO;
  skill_refs?: string[];
  mcp_refs?: string[];
  subagents?: SubagentSpecDTO[];
  sandbox: SandboxSpecDTO;
  interrupt_on?: string[];
  status?: string;
  created_at?: string;
  updated_at?: string;
};

export type AgentSpecUpsertRequestDTO = {
  version?: string;
  description?: string;
  tags?: string[];
  model_ref?: string;
  prompt: PromptSpecDTO;
  skill_refs?: string[];
  mcp_refs?: string[];
  subagents?: SubagentSpecDTO[];
  sandbox: SandboxSpecDTO;
  interrupt_on?: string[];
  status?: string;
};

export type AgentSpecListDTO = NumberPageMeta & {
  agents: AgentSpecDTO[];
};

export type SessionSummaryDTO = {
  thread_id?: string;
  agent_name?: string;
  latest_checkpoint_id?: string;
  message_count?: number;
  checkpoint_count?: number;
  initial_prompt?: string;
  history_mode?: string;
  agent_status?: string;
  updated_at?: string;
};

export type SessionListDTO = CursorPageMeta & {
  sessions: SessionSummaryDTO[];
};

export type SessionMessageDTO = {
  index?: number;
  checkpoint_id?: string;
  role?: string;
  text?: string;
  content?: string;
  tool_call_id?: string;
  tool_name?: string;
  is_error?: boolean;
  raw?: unknown;
  created_at?: string;
};

export type SessionMessagesDTO = CursorPageMeta & {
  messages: SessionMessageDTO[];
};

export type SessionMessagePageDTO = CursorPageMeta & {
  thread_id?: string;
  resolved_checkpoint_id?: string;
  actual_mode?: string;
  total_message_count?: number;
  messages: SessionMessageDTO[];
};

export type RunStreamRequestDTO = {
  message: string;
  thread_id?: string;
  metadata?: Record<string, string>;
};

export type RunStreamHandshake = {
  runSessionId: string;
};

export type HTTPActionRequestDTO = {
  name: string;
  description?: string;
  arguments?: unknown;
};

export type HTTPReviewConfigDTO = {
  action_name: string;
  allowed_decisions?: string[];
  args_schema?: unknown;
};

export type HTTPAgentEventDTO = {
  type: string;
  run_id?: string;
  agent_name?: string;
  timestamp?: string;
  thread_id?: string;
  text?: string;
  tool_name?: string;
  tool_call_id?: string;
  interrupt_id?: string;
  reason?: string;
  error_message?: string;
  payload?: unknown;
  action_requests?: HTTPActionRequestDTO[];
  review_configs?: HTTPReviewConfigDTO[];
};

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
  | 'error';

export type CancelRunRequestDTO = {
  reason?: string;
};

export type DecisionActionDTO = {
  name: string;
  arguments?: unknown;
};

export type HitlDecisionDTO = {
  type: 'approve' | 'reject' | 'edit';
  message?: string;
  edited_action?: DecisionActionDTO;
};

export type SubmitHitlDecisionsRequestDTO = {
  interrupt_id: string;
  decisions: HitlDecisionDTO[];
};
