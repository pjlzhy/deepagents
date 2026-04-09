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

export type HealthAgentResponse = {
  name?: string;
  version?: string;
  description?: string;
  tags?: string[];
  status?: string;
  active_thread_count?: number;
  active_thread_ids?: string[];
  last_invoked_at?: string;
};

export type HealthResponse = {
  status?: string;
  assembled_agent_count?: number;
  installed_agent_count?: number;
  running_agent_count?: number;
  running_thread_count?: number;
  uptime_seconds?: number;
  ready: boolean;
  agents?: HealthAgentResponse[];
};

export type ModelConfigDTO = {
  name?: string;
  description?: string;
  provider?: string;
  model?: string;
  base_url?: string;
  api_key?: string;
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
  api_key?: string;
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

export type SandboxExecutionPolicyDTO = {
  command_timeout_seconds?: number;
  setup_timeout_seconds?: number;
  startup_timeout_seconds?: number;
  max_output_bytes?: number;
};

export type SandboxEnvVarDTO = {
  name?: string;
  value?: string;
};

export type ImageReferenceDTO = {
  reference?: string;
  pull_policy?: string;
};

export type DockerResourceSpecDTO = {
  cpu?: string;
  memory?: string;
  shm_size?: string;
  pids_limit?: number;
};

export type DockerSandboxSpecDTO = {
  image: ImageReferenceDTO;
  resources: DockerResourceSpecDTO;
};

export type KubernetesResourceRequirementsDTO = {
  requests?: Record<string, string>;
  limits?: Record<string, string>;
};

export type KubernetesSandboxSpecDTO = {
  image: ImageReferenceDTO;
  resources: KubernetesResourceRequirementsDTO;
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
  model_ref?: string;
  skill_refs?: string[];
};

export type SandboxSpecDTO = {
  image?: string;
  resources?: Record<string, string>;
  init?: string[];
  execution?: SandboxExecutionPolicyDTO;
  env?: SandboxEnvVarDTO[];
  setup_commands?: string[];
  local?: Record<string, never>;
  docker?: DockerSandboxSpecDTO;
  kubernetes?: KubernetesSandboxSpecDTO;
};

export type SandboxConfigDTO = {
  name?: string;
  description?: string;
  spec: SandboxSpecDTO;
  status?: string;
  created_at?: string;
  updated_at?: string;
};

export type SandboxConfigUpsertRequestDTO = {
  description?: string;
  spec: SandboxSpecDTO;
  status?: string;
};

export type SandboxConfigListDTO = NumberPageMeta & {
  sandboxes: SandboxConfigDTO[];
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
  sandbox_ref?: string;
  subagents?: SubagentSpecDTO[];
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
  sandbox_ref?: string;
  subagents?: SubagentSpecDTO[];
  interrupt_on?: string[];
  status?: string;
};

export type AgentSpecListDTO = NumberPageMeta & {
  agents: AgentSpecDTO[];
};

export type AgentGraphNodeDTO = {
  id: string | number;
  type?: string;
  data?: unknown;
  metadata?: Record<string, unknown>;
};

export type AgentGraphEdgeDTO = {
  source: string | number;
  target: string | number;
  data?: unknown;
  conditional?: boolean;
};

export type AgentGraphDTO = {
  nodes: AgentGraphNodeDTO[];
  edges: AgentGraphEdgeDTO[];
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

export type WorkspaceUploadFileResultDTO = {
  path?: string;
  error?: string;
};

export type WorkspaceUploadResponseDTO = {
  thread_id?: string;
  files: WorkspaceUploadFileResultDTO[];
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

export type HTTPTelemetryEventDTO = {
  run_id?: string;
  agent_name?: string;
  timestamp?: string;
  event_id?: string;
  attempt?: number;
  seq?: number;
  namespace?: string[];
  stream_mode?: string;
  event_type?: string;
  node_name?: string;
  task_id?: string;
  model_call_id?: string;
  tool_call_id?: string;
  interrupt_id?: string;
  message_id?: string;
  metadata?: unknown;
  payload?: unknown;
  public_event?: HTTPAgentEventDTO;
};

export type HTTPTelemetryRunDTO = {
  run_id?: string;
  agent_name?: string;
  thread_id?: string;
  runtime_target?: string;
  status?: string;
  request_metadata?: unknown;
  trace_context?: unknown;
  graph_snapshot_id?: string;
  reasoning_summary?: string;
  node_step_count?: number;
  model_step_count?: number;
  tool_step_count?: number;
  hitl_wait_count?: number;
  error_count?: number;
  event_count?: number;
  started_at?: string;
  finished_at?: string;
  last_event_at?: string;
  created_at?: string;
  updated_at?: string;
};

export type HTTPTelemetryStepDTO = {
  step_id?: string;
  run_id?: string;
  parent_step_id?: string;
  kind?: 'run' | 'node' | 'model' | 'tool' | 'hitl' | string;
  title?: string;
  namespace?: string[];
  status?: 'running' | 'completed' | 'failed' | 'interrupted' | 'observed' | string;
  started_at?: string;
  finished_at?: string;
  depth?: number;
  step?: number;
  input?: unknown;
  output?: unknown;
  error?: string;
  triggers?: string[];
  reasoning?: string[];
  messages?: string[];
  updates?: unknown[];
  custom?: unknown[];
  related_event_ids?: string[];
  order?: number;
  synthetic?: boolean;
};

export type TelemetryRunsListDTO = {
  runs: HTTPTelemetryRunDTO[];
  page_size?: number;
  page_number?: number;
  total_size?: number;
  total_pages?: number;
};

export type TelemetryEventsListDTO = {
  events: HTTPTelemetryEventDTO[];
  page_size?: number;
  page_number?: number;
  total_size?: number;
  total_pages?: number;
};

export type TelemetryStepsListDTO = {
  steps: HTTPTelemetryStepDTO[];
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

export type TelemetryEventType =
  | 'run_started'
  | 'text'
  | 'reasoning'
  | 'tool_call_chunk'
  | 'tool_call'
  | 'tool_call_start'
  | 'tool_call_done'
  | 'tool_result'
  | 'state_update'
  | 'update_metadata'
  | 'interrupt'
  | 'task'
  | 'task_result'
  | 'checkpoint'
  | 'custom'
  | 'text_done'
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

// ---------------------------------------------------------------------------
// Workspace file operations
// ---------------------------------------------------------------------------

export type WorkspaceFileInfoDTO = {
  path?: string;
  is_dir?: boolean;
  size?: number;
  modified_at?: string;
};

export type WorkspaceListResponseDTO = {
  thread_id?: string;
  files: WorkspaceFileInfoDTO[];
};

// ---------------------------------------------------------------------------
// Thread artifacts
// ---------------------------------------------------------------------------

export type ThreadArtifactDTO = {
  id?: string;
  type?: string;
  path?: string;
  title?: string;
  content_type?: string;
  language?: string;
  created_by_tool?: string;
  created_at?: string;
  modified_at?: string;
  size?: number;
};

export type ListArtifactsResponseDTO = {
  thread_id?: string;
  artifacts: ThreadArtifactDTO[];
};
