import { RobotOne, FolderOpen } from '@icon-park/react';
import { Button, Message, Spin, Typography } from '@arco-design/web-react';
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
  type ConversationTimelineItemVM,
  type PendingInterruptVM,
  type RunStatusVM,
} from '@/features/chat/runtimeEventParser';
import { controlClient } from '@/shared/api/controlClient';
import type { HTTPAgentEventDTO } from '@/shared/types/api';
import '@/styles/registry-cards.css';

import ThreadSidebar from './ThreadSidebar';
import { UserBubble, AssistantBubble, HitlRequestBubble } from './MessageBubble';
import ToolCallCard from './ToolCallCard';
import ChatComposer from './ChatComposer';
import ArtifactsPanel from './ArtifactsPanel';

const CYAN = '#00f0ff';

function isRunActive(status: RunStatusVM): boolean {
  return ['starting', 'streaming', 'waiting_hitl', 'canceling'].includes(status);
}

function isRuntimeEvent(payload: unknown): payload is HTTPAgentEventDTO {
  return typeof payload === 'object' && payload !== null && 'type' in payload;
}

type StatusStyle = { text: string; color: string; dot: string };

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

function renderTimelineItem(
  item: ConversationTimelineItemVM,
  opts: {
    pendingInterrupts: PendingInterruptVM[];
    onSubmitDecision: (interrupt: PendingInterruptVM, type: 'approve' | 'reject') => void;
  },
) {
  if (item.kind === 'user_message') return <UserBubble item={item} />;
  if (item.kind === 'assistant_message' || item.kind === 'assistant_draft') return <AssistantBubble item={item} />;
  if (item.kind === 'assistant_tool_call') {
    return <ToolCallCard item={item} />;
  }
  if (item.kind === 'hitl_request') {
    const pending = opts.pendingInterrupts.find((p) => p.interruptId === item.interruptId);
    return (
      <HitlRequestBubble
        item={item}
        resolved={!pending}
        onApprove={pending ? () => opts.onSubmitDecision(pending, 'approve') : undefined}
        onReject={pending ? () => opts.onSubmitDecision(pending, 'reject') : undefined}
      />
    );
  }
  return null;
}

export default function ChatWorkspacePage() {
  const navigate = useNavigate();
  const params = useParams<{ agentName?: string; threadId?: string }>();
  const selectedAgentName = params.agentName;
  const selectedThreadId = params.threadId;
  const streamAbortRef = useRef<AbortController | null>(null);
  const timelineViewportRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [runSessionId, setRunSessionId] = useState<string | undefined>(undefined);
  const [composerValue, setComposerValue] = useState('');
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [uploadedWorkspaceFiles, setUploadedWorkspaceFiles] = useState<string[]>([]);
  const [runtimeState, setRuntimeState] = useState(() => createRuntimeStateFromHistory([]));
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [artifactsPanelOpen, setArtifactsPanelOpen] = useState(false);

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

  // Clear uploaded files on thread switch
  useEffect(() => {
    setUploadedWorkspaceFiles([]);
  }, [selectedThreadId]);

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

  // ─── Business logic (preserved from original) ───

  async function startRun(): Promise<void> {
    if (!selectedAgentName) { Message.warning('Please select an agent first.'); return; }
    if (isRunActive(runtimeState.runStatus)) { Message.warning('The current run is still active.'); return; }
    const message = composerValue.trim();
    if (!message) return;

    setComposerValue('');
    setRuntimeState((prev) => appendUserMessage(prev, message));
    setRunSessionId(undefined);

    const controller = new AbortController();
    streamAbortRef.current = controller;

    try {
      await controlClient.runs.stream(
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
            if (!isRuntimeEvent(payload)) return;
            if (payload.thread_id && selectedAgentName && payload.thread_id !== selectedThreadId) {
              void navigate(links.chatThread(selectedAgentName, payload.thread_id), { replace: true });
            }
            setRuntimeState((prev) => reduceRuntimeEvent(prev, payload));
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
    try {
      await controlClient.runs.submitHitl(runSessionId, { interrupt_id: interrupt.interruptId, decisions: [{ type }] });
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
  }

  // ─── Layout ───

  return (
    <div className='flex h-full min-h-0 overflow-hidden rd-4px'>
      {/* Thread sidebar */}
      <ThreadSidebar
        agentOptions={agentOptions}
        selectedAgentName={selectedAgentName}
        selectedThreadId={selectedThreadId}
        sessions={sessionItems}
        disabled={isRunActive(runtimeState.runStatus)}
        collapsed={sidebarCollapsed}
        onAgentChange={handleAgentChange}
        onThreadSelect={handleThreadSelect}
        onNewChat={handleNewConversation}
        onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
      />

      {/* Main chat area + artifacts panel */}
      <div className='flex min-w-0 flex-1 min-h-0'>
        <div className='flex min-w-0 flex-1 flex-col bg-[var(--control-panel)]'>
        {/* Top bar */}
        <div
          className='flex shrink-0 items-center justify-between px-20px py-10px'
          style={{
            borderBottom: '1px solid var(--control-border)',
            background: 'rgba(0,240,255,0.02)',
          }}
        >
          <div className='flex items-center gap-10px'>
            <div
              className='w-28px h-28px rd-8px flex-center shrink-0'
              style={{ background: 'rgba(0,240,255,0.08)' }}
            >
              <RobotOne size={16} fill={[CYAN]} />
            </div>
            <Typography.Text className='font-semibold text-[var(--control-text)]'>
              {selectedAgentName || 'No agent selected'}
            </Typography.Text>
            {/* Status chip */}
            <span
              className='flex items-center gap-5px rd-full px-8px py-2px text-11px font-semibold border border-solid'
              style={{
                color: statusView.color,
                borderColor: `${statusView.color}40`,
                background: `${statusView.color}0a`,
              }}
            >
              <span className='inline-block w-6px h-6px rd-full' style={{ background: statusView.dot }} />
              {statusView.text}
            </span>
            {selectedThreadId ? (
              <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                {selectedThreadId}
              </Typography.Text>
            ) : null}
          </div>
          <div className='flex items-center gap-6px'>
            {selectedThreadId && (artifactsQuery.data?.artifacts?.length ?? 0) > 0 ? (
              <Button
                type='text'
                size='mini'
                className='control-quiet-icon-button'
                icon={<FolderOpen theme='outline' size='16' fill={artifactsPanelOpen ? CYAN : 'var(--control-subtle)'} />}
                onClick={() => setArtifactsPanelOpen((prev) => !prev)}
              />
            ) : null}
          </div>
        </div>

        {/* Message area */}
        <div className='min-h-0 flex-1 overflow-hidden'>
          {messagesQuery.isLoading && !isRunActive(runtimeState.runStatus) ? (
            <div className='flex h-full items-center justify-center'>
              <Spin />
            </div>
          ) : chatTimelineItems.length === 0 ? (
            <div className='flex h-full flex-col items-center justify-center gap-16px px-24px'>
              <div
                className='w-56px h-56px rd-14px flex-center'
                style={{ background: 'rgba(0,240,255,0.08)', border: '1px solid rgba(0,240,255,0.18)' }}
              >
                <RobotOne theme='outline' size='28' fill={CYAN} />
              </div>
              <Typography.Text className='text-16px font-semibold text-[var(--control-text)]'>
                {selectedAgentName ? 'Start a new conversation' : 'Select an agent to begin'}
              </Typography.Text>
              <Typography.Text className='text-center text-13px text-[var(--control-subtle)]'>
                {selectedAgentName
                  ? 'Type a message below to get started.'
                  : 'Choose an agent from the sidebar, then start chatting.'}
              </Typography.Text>
            </div>
          ) : (
            <div
              ref={timelineViewportRef}
              className='control-scroll flex h-full min-h-0 flex-col gap-16px overflow-auto px-24px py-16px'
            >
              <div className='flex w-full flex-col gap-12px'>
                {chatTimelineItems.map((item) => (
                  <div key={item.id}>
                    {renderTimelineItem(item, {
                      pendingInterrupts: runtimeState.pendingInterrupts,
                      onSubmitDecision: (interrupt, type) => { void submitInterruptDecision(interrupt, type); },
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Composer */}
        <ChatComposer
          composerValue={composerValue}
          runStatus={runtimeState.runStatus}
          selectedAgentName={selectedAgentName}
          uploadingFiles={uploadingFiles}
          uploadedWorkspaceFiles={uploadedWorkspaceFiles}
          runSessionId={runSessionId}
          fileInputRef={fileInputRef}
          onComposerChange={setComposerValue}
          onSend={() => { void startRun(); }}
          onCancel={() => { void cancelRun(); }}
          onUploadClick={openWorkspaceUploadPicker}
          onFilesSelected={(e) => { void handleWorkspaceFilesSelected(e); }}
        />
      </div>

        {/* Artifacts panel */}
        {artifactsPanelOpen && selectedAgentName && selectedThreadId ? (
          <ArtifactsPanel
            agentName={selectedAgentName}
            threadId={selectedThreadId}
            artifacts={artifactsQuery.data?.artifacts ?? []}
            loading={artifactsQuery.isLoading}
            onClose={() => setArtifactsPanelOpen(false)}
          />
        ) : null}
      </div>
    </div>
  );
}
