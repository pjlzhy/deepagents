import { Message } from '@arco-design/web-react';
import useSWR from 'swr';
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { links } from '@/app/links';
import {
  appendUserMessage,
  createConversationTimeline,
  createRuntimeStateFromHistory,
  markInterruptResolved,
  markRunCanceling,
  reduceRuntimeEvent,
  telemetryEventToRuntimeEvent,
  type PendingInterruptVM,
  type RunStatusVM,
} from '@/features/chat/runtimeEventParser';
import { controlClient } from '@/shared/api/controlClient';
import type { HTTPAgentEventDTO, HTTPTelemetryEventDTO, SessionMessageDTO } from '@/shared/types/api';
import { type TelemetryEventVM } from '@/features/telemetry/traceModel';
import {
  isTelemetryEvent as isTelemetryPayload,
  normalizeTelemetryEvent,
} from '@/shared/utils/telemetryHelpers';

// ─── Types ───

export type ChatWorkspaceTab = 'chat' | 'runs';

export type SnapshotViewState =
  | { active: false }
  | { active: true; runId: string; runLabel: string; messages: SessionMessageDTO[]; checkpointId?: string };

// ─── Helpers ───

function isRunActive(status: RunStatusVM): boolean {
  return ['starting', 'streaming', 'waiting_hitl', 'canceling'].includes(status);
}

function isRuntimeEvent(payload: unknown): payload is HTTPAgentEventDTO {
  return typeof payload === 'object' && payload !== null && 'type' in payload;
}

function isTelemetryEvent(payload: unknown): payload is HTTPTelemetryEventDTO {
  return typeof payload === 'object' && payload !== null && ('event_type' in payload || 'public_event' in payload);
}

type StatusStyle = { text: string; color: string; dot: string };

const CYAN = '#00f0ff';

function formatStatus(status: RunStatusVM): StatusStyle {
  switch (status) {
    case 'starting': return { text: 'starting', color: CYAN, dot: CYAN };
    case 'streaming': return { text: 'streaming', color: '#39ff14', dot: '#39ff14' };
    case 'waiting_hitl': return { text: 'waiting', color: '#ff9f1a', dot: '#ff9f1a' };
    case 'canceling': return { text: 'canceling', color: '#ff9f1a', dot: '#ff9f1a' };
    case 'completed': return { text: 'completed', color: '#39ff14', dot: '#39ff14' };
    case 'canceled': return { text: 'canceled', color: 'var(--control-subtle)', dot: 'var(--control-subtle)' };
    case 'failed': return { text: 'failed', color: '#ff3b5c', dot: '#ff3b5c' };
    default: return { text: 'idle', color: 'var(--control-subtle)', dot: 'var(--control-subtle)' };
  }
}

// ─── Hook ───

export function useChatWorkspaceState() {
  const navigate = useNavigate();
  const params = useParams<{ agentName?: string; threadId?: string }>();
  const selectedAgentName = params.agentName;
  const selectedThreadId = params.threadId;
  const streamAbortRef = useRef<AbortController | null>(null);
  const timelineViewportRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const nextEventIdRef = useRef(1);

  // Existing state
  const [runSessionId, setRunSessionId] = useState<string | undefined>(undefined);
  const [composerValue, setComposerValue] = useState('');
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [uploadedWorkspaceFiles, setUploadedWorkspaceFiles] = useState<string[]>([]);
  const [runtimeState, setRuntimeState] = useState(() => createRuntimeStateFromHistory([]));
  const [artifactsPanelOpen, setArtifactsPanelOpen] = useState(false);

  // New state for Runs integration
  const [activeTab, setActiveTab] = useState<ChatWorkspaceTab>('chat');
  const [snapshotView, setSnapshotView] = useState<SnapshotViewState>({ active: false });
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(undefined);
  const [liveEvents, setLiveEvents] = useState<TelemetryEventVM[]>([]);
  const [currentRunId, setCurrentRunId] = useState<string | undefined>(undefined);

  // ─── SWR queries ───

  const agentsQuery = useSWR('chat-agents', () => controlClient.agents.list({ pageSize: 100, pageNumber: 1 }));
  const sessionsQuery = useSWR(
    selectedAgentName ? ['chat-sessions', selectedAgentName] : null,
    () => controlClient.sessions.list({ agentName: selectedAgentName, pageSize: 50 }),
  );
  const messagesQuery = useSWR(
    selectedAgentName && selectedThreadId ? ['chat-messages', selectedAgentName, selectedThreadId] : null,
    () => controlClient.sessions.getMessages(selectedAgentName!, selectedThreadId!, { pageSize: 200 }),
  );
  const artifactsQuery = useSWR(
    selectedAgentName && selectedThreadId ? ['thread-artifacts', selectedAgentName, selectedThreadId] : null,
    () => controlClient.sessions.listArtifacts(selectedThreadId!, selectedAgentName!),
  );

  // ─── Effects ───

  useEffect(() => {
    if (!messagesQuery.data || isRunActive(runtimeState.runStatus)) return;
    setRuntimeState(createRuntimeStateFromHistory(messagesQuery.data.messages));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only rebuild on fresh data fetch, not on runStatus change
  }, [messagesQuery.data]);

  useEffect(() => {
    const viewport = timelineViewportRef.current;
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [runtimeState.timeline]);

  useEffect(() => {
    return () => { streamAbortRef.current?.abort(); };
  }, []);

  useEffect(() => {
    setUploadedWorkspaceFiles([]);
  }, [selectedThreadId]);

  // ─── Derived values ───

  const agentOptions = useMemo(
    () => (agentsQuery.data?.agents ?? []).map((item) => ({ label: item.name ?? 'unnamed-agent', value: item.name ?? '' })),
    [agentsQuery.data?.agents],
  );
  const sessionItems = sessionsQuery.data?.sessions ?? [];
  const chatTimelineItems = useMemo(
    () => createConversationTimeline(runtimeState.timeline).filter((item) => item.kind !== 'system_event'),
    [runtimeState.timeline],
  );
  const statusView = formatStatus(runtimeState.runStatus);
  const runActive = isRunActive(runtimeState.runStatus);

  // ─── Business logic ───

  async function startRun(): Promise<void> {
    if (!selectedAgentName) { Message.warning('Please select an agent first.'); return; }
    if (isRunActive(runtimeState.runStatus)) { Message.warning('The current run is still active.'); return; }
    const message = composerValue.trim();
    if (!message) return;

    setComposerValue('');
    setRuntimeState((prev) => appendUserMessage(prev, message));
    setRunSessionId(undefined);
    setLiveEvents([]);
    setCurrentRunId(undefined);

    const controller = new AbortController();
    streamAbortRef.current = controller;

    try {
      await controlClient.runs.streamTelemetry(
        selectedAgentName,
        { message, thread_id: selectedThreadId },
        {
          signal: controller.signal,
          onOpen: ({ runSessionId: next }) => setRunSessionId(next),
          onEvent: (eventName, payload) => {
            if (eventName === 'run_session' && typeof payload === 'object' && payload !== null && 'session_id' in payload) {
              const value = (payload as Record<string, unknown>).session_id;
              if (typeof value === 'string') setRunSessionId(value);
              return;
            }
            if (eventName === 'transport_error' && typeof payload === 'object' && payload !== null && 'error' in payload) {
              Message.error(typeof (payload as Record<string, unknown>).error === 'string' ? ((payload as Record<string, unknown>).error as string) : 'stream transport error');
              return;
            }
            if (!isTelemetryEvent(payload)) return;

            // Chat timeline path
            const runtimeEvent = telemetryEventToRuntimeEvent(payload);
            if (runtimeEvent && isRuntimeEvent(runtimeEvent)) {
              if (runtimeEvent.thread_id && selectedAgentName && runtimeEvent.thread_id !== selectedThreadId) {
                void navigate(links.chatThread(selectedAgentName, runtimeEvent.thread_id), { replace: true });
              }
              setRuntimeState((prev) => reduceRuntimeEvent(prev, runtimeEvent));
            }

            // Telemetry events path (for Runs tab)
            if (isTelemetryPayload(payload)) {
              const normalized = normalizeTelemetryEvent(payload, `live-${nextEventIdRef.current++}`);
              if (!payload.event_type) normalized.eventType = eventName;
              setLiveEvents((prev) => [...prev, normalized]);
              if (normalized.runId) setCurrentRunId(normalized.runId);
            }
          },
          onClose: () => {
            setRunSessionId(undefined);
            void sessionsQuery.mutate();
            void artifactsQuery.mutate();
          },
        },
      );
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'run stream failed');
      setRuntimeState((prev) => ({ ...prev, runStatus: 'failed' }));
    } finally {
      streamAbortRef.current = null;
    }
  }

  async function cancelRun(): Promise<void> {
    if (!runSessionId) { Message.warning('No cancelable run_session.'); return; }
    setRuntimeState((prev) => markRunCanceling(prev));
    try {
      await controlClient.runs.cancel(runSessionId, { reason: 'user_requested' });
      Message.success('cancel request sent');
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'cancel failed');
    }
  }

  function openWorkspaceUploadPicker(): void {
    if (!selectedAgentName) { Message.warning('Please select an agent first.'); return; }
    if (isRunActive(runtimeState.runStatus)) { Message.warning('Wait for the current run to finish.'); return; }
    fileInputRef.current?.click();
  }

  async function handleWorkspaceFilesSelected(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (files.length === 0) return;
    if (!selectedAgentName) { Message.warning('Please select an agent first.'); return; }
    if (isRunActive(runtimeState.runStatus)) { Message.warning('Wait for the current run to finish.'); return; }

    setUploadingFiles(true);
    try {
      const response = await controlClient.agents.uploadWorkspaceFiles(selectedAgentName, files, selectedThreadId);
      const successful = (response.files ?? []).filter((item) => !item.error && item.path);
      const failed = (response.files ?? []).filter((item) => item.error);
      if (successful.length > 0) {
        setUploadedWorkspaceFiles((prev) => {
          const next = new Set(prev);
          for (const item of successful) { if (item.path) next.add(item.path); }
          return Array.from(next);
        });
      }
      if (response.thread_id && selectedAgentName && response.thread_id !== selectedThreadId) {
        setRuntimeState(createRuntimeStateFromHistory([]));
        void navigate(links.chatThread(selectedAgentName, response.thread_id), { replace: !selectedThreadId });
      }
      void sessionsQuery.mutate();
      void messagesQuery.mutate();
      void artifactsQuery.mutate();
      if (successful.length > 0 && failed.length === 0) {
        Message.success(`uploaded ${successful.length} file${successful.length === 1 ? '' : 's'}`);
      } else if (successful.length > 0) {
        Message.warning(`uploaded ${successful.length} file(s), ${failed.length} failed`);
      } else {
        Message.error(failed.map((item) => `${item.path ?? 'unknown'}: ${item.error ?? 'upload_failed'}`).join('; '));
      }
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'workspace upload failed');
    } finally {
      setUploadingFiles(false);
    }
  }

  async function submitInterruptDecision(interrupt: PendingInterruptVM, type: 'approve' | 'reject'): Promise<void> {
    if (!runSessionId) { Message.warning('No active run_session.'); return; }
    const decisionCount = Math.max(1, interrupt.actionRequests.length);
    const decisions = Array.from({ length: decisionCount }, () => ({ type }));
    try {
      await controlClient.runs.submitHitl(runSessionId, { interrupt_id: interrupt.interruptId, decisions });
      setRuntimeState((prev) => markInterruptResolved(prev, interrupt.interruptId));
      Message.success(`${type} submitted`);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'submit hitl decision failed');
    }
  }

  function handleAgentChange(value: string | number | Record<string, unknown> | undefined): void {
    if (isRunActive(runtimeState.runStatus)) { Message.warning('Current run is still active.'); return; }
    const nextAgentName = typeof value === 'string' ? value : '';
    resetWorkspace();
    if (!nextAgentName) { void navigate(links.chatRoot()); return; }
    void navigate(links.chatAgent(nextAgentName));
  }

  function handleThreadSelect(threadId: string): void {
    if (!selectedAgentName) return;
    if (isRunActive(runtimeState.runStatus)) { Message.warning('Current run is still active.'); return; }
    resetWorkspace();
    void navigate(links.chatThread(selectedAgentName, threadId));
  }

  function handleNewConversation(): void {
    if (!selectedAgentName) { Message.warning('Please select an agent first.'); return; }
    if (isRunActive(runtimeState.runStatus)) { Message.warning('Current run is still active.'); return; }
    resetWorkspace();
    void navigate(links.chatAgent(selectedAgentName));
  }

  function resetWorkspace(): void {
    setRunSessionId(undefined);
    setComposerValue('');
    setUploadingFiles(false);
    setUploadedWorkspaceFiles([]);
    setArtifactsPanelOpen(false);
    setRuntimeState(createRuntimeStateFromHistory([]));
    setSnapshotView({ active: false });
    setSelectedRunId(undefined);
    setLiveEvents([]);
    setCurrentRunId(undefined);
  }

  // ─── Runs Tab handlers ───

  function selectRun(runId: string): void {
    setSelectedRunId(runId);
  }

  function clearSnapshot(): void {
    setSnapshotView({ active: false });
    setSelectedRunId(undefined);
  }

  async function loadSnapshot(runId: string, runLabel: string): Promise<void> {
    try {
      const snapshot = await controlClient.runs.getTelemetryRunSnapshot(runId, 'after', { pageSize: 200 });
      setSnapshotView({
        active: true,
        runId,
        runLabel,
        messages: snapshot.messages ?? [],
        checkpointId: snapshot.resolved_checkpoint_id,
      });
      setActiveTab('chat');
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to load snapshot');
    }
  }

  return {
    // Route params
    selectedAgentName,
    selectedThreadId,

    // Refs
    timelineViewportRef,
    fileInputRef,

    // Existing state
    runSessionId,
    composerValue,
    setComposerValue,
    uploadingFiles,
    uploadedWorkspaceFiles,
    runtimeState,
    artifactsPanelOpen,
    setArtifactsPanelOpen,

    // New state
    activeTab,
    setActiveTab,
    snapshotView,
    selectedRunId,
    liveEvents,
    currentRunId,

    // Queries
    agentsQuery,
    sessionsQuery,
    messagesQuery,
    artifactsQuery,

    // Derived
    agentOptions,
    sessionItems,
    chatTimelineItems,
    statusView,
    runActive,

    // Handlers
    startRun,
    cancelRun,
    openWorkspaceUploadPicker,
    handleWorkspaceFilesSelected,
    submitInterruptDecision,
    handleAgentChange,
    handleThreadSelect,
    handleNewConversation,

    // Runs Tab handlers
    selectRun,
    clearSnapshot,
    loadSnapshot,
  };
}
