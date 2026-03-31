import { httpClient } from '@/shared/api/httpClient';
import { postSSE, type SSEHandlers } from '@/shared/api/sseClient';
import type {
  AgentSpecDTO,
  AgentSpecListDTO,
  AgentSpecUpsertRequestDTO,
  CancelRunRequestDTO,
  HealthResponse,
  HTTPAgentEventDTO,
  MCPConfigListDTO,
  MCPConfigDTO,
  MCPConfigUpsertRequestDTO,
  ModelConfigListDTO,
  ModelConfigDTO,
  ModelConfigUpsertRequestDTO,
  RunStreamRequestDTO,
  SessionListDTO,
  SkillDetailDTO,
  SessionMessagePageDTO,
  SessionMessagesDTO,
  SessionSummaryDTO,
  SandboxConfigDTO,
  SandboxConfigListDTO,
  SandboxConfigUpsertRequestDTO,
  SkillDTO,
  SkillListDTO,
  SkillUpsertRequestDTO,
  SubmitHitlDecisionsRequestDTO,
  WorkspaceUploadResponseDTO,
} from '@/shared/types/api';

type NumberPageQuery = {
  pageSize: number;
  pageNumber: number;
};

type CursorPageQuery = {
  pageSize: number;
  pageToken?: string;
};

function resourceQuery(params: NumberPageQuery): Record<string, number> {
  return {
    page_size: params.pageSize,
    page_number: params.pageNumber,
  };
}

function sessionQuery(params: CursorPageQuery & { agentName?: string }): Record<string, string | number | undefined> {
  return {
    agent_name: params.agentName,
    page_size: params.pageSize,
    page_token: params.pageToken,
  };
}

export const controlClient = {
  health: {
    get() {
      return httpClient.get<HealthResponse>('/api/v1/health');
    },
  },
  models: {
    list(params: NumberPageQuery) {
      return httpClient.get<ModelConfigListDTO>('/api/v1/models', resourceQuery(params));
    },
    get(name: string) {
      return httpClient.get<ModelConfigDTO>(`/api/v1/models/${encodeURIComponent(name)}`);
    },
    upsert(name: string, body: ModelConfigUpsertRequestDTO) {
      return httpClient.put<ModelConfigUpsertRequestDTO, ModelConfigDTO>(
        `/api/v1/models/${encodeURIComponent(name)}`,
        body,
      );
    },
    delete(name: string) {
      return httpClient.delete<void>(`/api/v1/models/${encodeURIComponent(name)}`);
    },
  },
  skills: {
    list(params: NumberPageQuery) {
      return httpClient.get<SkillListDTO>('/api/v1/skills', resourceQuery(params));
    },
    get(name: string) {
      return httpClient.get<SkillDetailDTO>(`/api/v1/skills/${encodeURIComponent(name)}`);
    },
    upsert(name: string, body: SkillUpsertRequestDTO) {
      return httpClient.put<SkillUpsertRequestDTO, SkillDTO>(
        `/api/v1/skills/${encodeURIComponent(name)}`,
        body,
      );
    },
    createPackage(file: File) {
      const form = new FormData();
      form.append('package', file);
      return httpClient.postForm<SkillDetailDTO>('/api/v1/skills/package', form);
    },
    replacePackage(name: string, file: File) {
      const form = new FormData();
      form.append('package', file);
      return httpClient.putForm<SkillDetailDTO>(`/api/v1/skills/${encodeURIComponent(name)}/package`, form);
    },
    downloadPackage(name: string) {
      return httpClient.getBlob(`/api/v1/skills/${encodeURIComponent(name)}/package`);
    },
    delete(name: string) {
      return httpClient.delete<void>(`/api/v1/skills/${encodeURIComponent(name)}`);
    },
  },
  mcps: {
    list(params: NumberPageQuery) {
      return httpClient.get<MCPConfigListDTO>('/api/v1/mcps', resourceQuery(params));
    },
    get(name: string) {
      return httpClient.get<MCPConfigDTO>(`/api/v1/mcps/${encodeURIComponent(name)}`);
    },
    upsert(name: string, body: MCPConfigUpsertRequestDTO) {
      return httpClient.put<MCPConfigUpsertRequestDTO, MCPConfigDTO>(
        `/api/v1/mcps/${encodeURIComponent(name)}`,
        body,
      );
    },
    delete(name: string) {
      return httpClient.delete<void>(`/api/v1/mcps/${encodeURIComponent(name)}`);
    },
  },
  sandboxes: {
    list(params: NumberPageQuery) {
      return httpClient.get<SandboxConfigListDTO>('/api/v1/sandboxes', resourceQuery(params));
    },
    get(name: string) {
      return httpClient.get<SandboxConfigDTO>(`/api/v1/sandboxes/${encodeURIComponent(name)}`);
    },
    upsert(name: string, body: SandboxConfigUpsertRequestDTO) {
      return httpClient.put<SandboxConfigUpsertRequestDTO, SandboxConfigDTO>(
        `/api/v1/sandboxes/${encodeURIComponent(name)}`,
        body,
      );
    },
    delete(name: string) {
      return httpClient.delete<void>(`/api/v1/sandboxes/${encodeURIComponent(name)}`);
    },
  },
  agents: {
    list(params: NumberPageQuery) {
      return httpClient.get<AgentSpecListDTO>('/api/v1/agents', resourceQuery(params));
    },
    get(agentName: string) {
      return httpClient.get<AgentSpecDTO>(`/api/v1/agents/${encodeURIComponent(agentName)}`);
    },
    ensureRunnable(agentName: string) {
      return httpClient.post<Record<string, never>, void>(
        `/api/v1/agents/${encodeURIComponent(agentName)}/ensure_runnable`,
        {},
      );
    },
    upsert(agentName: string, body: AgentSpecUpsertRequestDTO) {
      return httpClient.put<AgentSpecUpsertRequestDTO, AgentSpecDTO>(
        `/api/v1/agents/${encodeURIComponent(agentName)}`,
        body,
      );
    },
    delete(agentName: string) {
      return httpClient.delete<void>(`/api/v1/agents/${encodeURIComponent(agentName)}`);
    },
    uploadWorkspaceFiles(agentName: string, files: File[], threadId?: string) {
      const form = new FormData();
      for (const file of files) {
        form.append('files', file);
      }
      if (threadId) {
        form.append('thread_id', threadId);
      }
      return httpClient.postForm<WorkspaceUploadResponseDTO>(
        `/api/v1/agents/${encodeURIComponent(agentName)}/workspace/files`,
        form,
      );
    },
  },
  sessions: {
    list(params: CursorPageQuery & { agentName?: string }) {
      return httpClient.get<SessionListDTO>('/api/v1/sessions', sessionQuery(params));
    },
    getLatest(agentName?: string) {
      return httpClient.get<SessionSummaryDTO>('/api/v1/sessions/latest', {
        agent_name: agentName,
      });
    },
    get(agentName: string, threadId: string) {
      return httpClient.get<SessionSummaryDTO>(`/api/v1/sessions/${encodeURIComponent(threadId)}`, {
        agent_name: agentName,
      });
    },
    getMessagePage(
      agentName: string,
      threadId: string,
      params: CursorPageQuery & {
        mode?: string;
      },
    ) {
      return httpClient.get<SessionMessagePageDTO>(
        `/api/v1/sessions/${encodeURIComponent(threadId)}/message_page`,
        {
          agent_name: agentName,
          page_size: params.pageSize,
          page_token: params.pageToken,
          mode: params.mode,
        },
      );
    },
    getMessages(agentName: string, threadId: string, params: CursorPageQuery) {
      return httpClient.get<SessionMessagesDTO>(`/api/v1/sessions/${encodeURIComponent(threadId)}/messages`, {
        agent_name: agentName,
        page_size: params.pageSize,
        page_token: params.pageToken,
      });
    },
    delete(agentName: string, threadId: string) {
      return httpClient.delete<void>(`/api/v1/sessions/${encodeURIComponent(threadId)}`, {
        agent_name: agentName,
      });
    },
  },
  runs: {
    stream(
      agentName: string,
      request: RunStreamRequestDTO,
      handlers: SSEHandlers<HTTPAgentEventDTO | { session_id?: string } | { error?: string }>,
    ) {
      return postSSE<RunStreamRequestDTO, HTTPAgentEventDTO | { session_id?: string } | { error?: string }>(
        `/api/v1/agents/${encodeURIComponent(agentName)}/runs/stream`,
        request,
        handlers,
      );
    },
    cancel(runSessionId: string, request: CancelRunRequestDTO) {
      return httpClient.post<CancelRunRequestDTO, void>(`/api/v1/run_sessions/${encodeURIComponent(runSessionId)}/cancel`, request);
    },
    submitHitl(runSessionId: string, request: SubmitHitlDecisionsRequestDTO) {
      return httpClient.post<SubmitHitlDecisionsRequestDTO, void>(
        `/api/v1/run_sessions/${encodeURIComponent(runSessionId)}/hitl_decisions`,
        request,
      );
    },
  },
};
