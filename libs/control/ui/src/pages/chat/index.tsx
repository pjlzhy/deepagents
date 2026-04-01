import { Check, CloseOne, Pause, Refresh, RobotOne, Send } from '@icon-park/react';
import {
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  List,
  Message,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from '@arco-design/web-react';
import useSWR from 'swr';
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react';
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
  type TimelineItemVM,
} from '@/features/chat/runtimeEventParser';
import { controlClient } from '@/shared/api/controlClient';
import type { HTTPAgentEventDTO } from '@/shared/types/api';

const { TextArea } = Input;

type ToolTimelineItem = Extract<TimelineItemVM, { kind: 'tool_event' }>;
type ChatTimelineItem = ConversationTimelineItemVM;
type AssistantToolCallItem = Extract<ConversationTimelineItemVM, { kind: 'assistant_tool_call' }>;

function isRunActive(status: RunStatusVM): boolean {
  return ['starting', 'streaming', 'waiting_hitl', 'canceling'].includes(status);
}

function isRuntimeEvent(payload: unknown): payload is HTTPAgentEventDTO {
  return typeof payload === 'object' && payload !== null && 'type' in payload;
}

function formatStatus(status: RunStatusVM): { text: string; color: 'arcoblue' | 'green' | 'orange' | 'red' | 'gray' } {
  switch (status) {
    case 'starting':
      return { text: 'starting', color: 'arcoblue' };
    case 'streaming':
      return { text: 'streaming', color: 'green' };
    case 'waiting_hitl':
      return { text: 'waiting_hitl', color: 'orange' };
    case 'canceling':
      return { text: 'canceling', color: 'orange' };
    case 'completed':
      return { text: 'completed', color: 'green' };
    case 'canceled':
      return { text: 'canceled', color: 'gray' };
    case 'failed':
      return { text: 'failed', color: 'red' };
    default:
      return { text: 'idle', color: 'gray' };
  }
}

function formatDateTime(value?: string): string {
  if (!value) {
    return 'n/a';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function formatCompactDateTime(value?: string): string {
  if (!value) {
    return 'n/a';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function renderCompactTimestamp(value?: string): ReactNode {
  if (!value) {
    return null;
  }

  return <Typography.Text className='text-[var(--control-subtle)]'>{formatCompactDateTime(value)}</Typography.Text>;
}

function truncateText(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  if (maxLength <= 3) {
    return value.slice(0, maxLength);
  }
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

function normalizeInlineCommand(value: string): string {
  return value
    .replace(/\s+/g, ' ')
    .replace(/ -c "([^"]+)"/g, ' -c $1')
    .replace(/ -c '([^']+)'/g, ' -c $1')
    .trim();
}

function formatInlineToolArguments(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') {
    return undefined;
  }

  if (typeof value === 'string') {
    return truncateText(normalizeInlineCommand(value), 180);
  }

  if (isRecord(value)) {
    if (typeof value.command === 'string') {
      return truncateText(normalizeInlineCommand(value.command), 180);
    }

    const entries = Object.entries(value).filter(([, entry]) => entry !== undefined && entry !== null && entry !== '');
    if (entries.length === 0) {
      return undefined;
    }

    const inline = entries
      .map(([key, entry]) => `${key}=${typeof entry === 'string' ? entry : JSON.stringify(entry)}`)
      .join(' ');
    return truncateText(inline, 180);
  }

  const formatted = formatStructuredValue(value);
  return formatted ? truncateText(formatted.replace(/\s+/g, ' ').trim(), 180) : undefined;
}

function formatToolResultSummary(value: string | undefined, status: 'running' | 'completed', isError?: boolean): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    if (isError) {
      return 'Tool call failed.';
    }
    return status === 'completed' ? 'No result returned.' : 'Running...';
  }

  const firstMeaningfulLine = trimmed.split(/\r?\n/).find((line) => line.trim());
  return truncateText((firstMeaningfulLine ?? trimmed).trim(), 180);
}

function AssistantToolCallCard(props: { item: AssistantToolCallItem }) {
  const { item } = props;
  const [expanded, setExpanded] = useState(false);
  const inlineArguments = formatInlineToolArguments(item.arguments);
  const summaryTitle = inlineArguments ? `${item.toolName ?? 'unknown_tool'}  ${inlineArguments}` : (item.toolName ?? 'unknown_tool');
  const resultSummary = formatToolResultSummary(item.output, item.status, item.isError);
  const argumentsBlock = renderStructuredBlock('arguments', item.arguments);
  const resultBlock = item.output?.trim() ? (
    <div className='mt-12px'>
      <Typography.Text className='mb-6px block text-[var(--control-subtle)]'>result</Typography.Text>
      <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words'>{item.output}</Typography.Paragraph>
    </div>
  ) : (
    <div className='mt-12px'>
      <Typography.Text className='mb-6px block text-[var(--control-subtle)]'>result</Typography.Text>
      <Typography.Text className='text-[var(--control-subtle)]'>{resultSummary}</Typography.Text>
    </div>
  );

  return (
    <div className='flex justify-start'>
      <div
        role='button'
        tabIndex={0}
        className='w-full max-w-[82%] cursor-pointer outline-none'
        title={expanded ? 'Collapse tool call details' : 'Expand tool call details'}
        onClick={() => setExpanded((previous) => !previous)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            setExpanded((previous) => !previous);
          }
        }}
      >
        <Card
          className='control-card'
          style={
            item.isError
              ? {
                  borderColor: 'rgba(196, 94, 89, 0.35)',
                  background: 'rgba(196, 94, 89, 0.08)',
                }
              : undefined
          }
        >
          <div className='mb-10px flex items-center justify-between gap-12px'>
            <Typography.Text
              className='block text-12px uppercase tracking-[0.18em]'
              style={{ color: item.isError ? 'var(--control-danger)' : 'var(--control-subtle)' }}
            >
              tool call
            </Typography.Text>
            <Tag color={item.isError ? 'red' : item.status === 'completed' ? 'green' : 'arcoblue'}>
              {item.isError ? 'error' : item.status}
            </Tag>
          </div>
          <Typography.Paragraph className='!mb-8px whitespace-pre-wrap break-words font-semibold text-[var(--control-text)]'>
            {summaryTitle}
          </Typography.Paragraph>
          <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words text-[var(--control-text)]'>
            {resultSummary}
          </Typography.Paragraph>
          {expanded ? (
            <div className='mt-12px border-t border-[var(--control-border)] pt-12px'>
              {argumentsBlock}
              {resultBlock}
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}

function MetaRow(props: { label: string; value: ReactNode }) {
  return (
    <div className='flex items-start justify-between gap-12px'>
      <Typography.Text className='text-[var(--control-subtle)]'>{props.label}</Typography.Text>
      <div className='max-w-[65%] break-all text-right text-[var(--control-text)]'>{props.value}</div>
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function formatStructuredValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') {
    return undefined;
  }
  if (typeof value === 'string') {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function extractToolArguments(item: ToolTimelineItem): unknown {
  if (item.phase === 'start') {
    return item.payload;
  }
  if (isRecord(item.payload) && 'args' in item.payload) {
    return item.payload.args;
  }
  return undefined;
}

function extractToolStructuredPayload(item: ToolTimelineItem): unknown {
  if (item.phase !== 'result' || item.payload === undefined) {
    return undefined;
  }
  if (!isRecord(item.payload)) {
    return item.payload;
  }

  const keys = Object.keys(item.payload);
  const isToolCallEnvelope =
    keys.length > 0 && keys.every((key) => ['args', 'id', 'name', 'type'].includes(key));
  if (isToolCallEnvelope) {
    return undefined;
  }
  return item.payload;
}

function renderStructuredBlock(label: string, value: unknown) {
  const formatted = formatStructuredValue(value);
  if (!formatted) {
    return null;
  }

  return (
    <div className='mt-12px'>
      <Typography.Text className='mb-6px block text-[var(--control-subtle)]'>{label}</Typography.Text>
      <pre className='!m-0 overflow-auto whitespace-pre-wrap break-words rounded-12px bg-[rgba(100,112,134,0.08)] p-12px text-13px text-[var(--control-text)]'>
        {formatted}
      </pre>
    </div>
  );
}

function renderTimelineItem(item: ChatTimelineItem) {
  if (item.kind === 'user_message') {
    return (
      <div className='flex justify-end'>
        <Card className='control-card w-full max-w-[78%] border-[var(--control-accent)] bg-[var(--control-primary-soft)]'>
          <div className='mb-8px flex items-center justify-between gap-12px'>
            <Typography.Text className='block text-12px uppercase tracking-[0.18em] text-[var(--control-subtle)]'>
              user
            </Typography.Text>
            {renderCompactTimestamp(item.createdAt)}
          </div>
          <Typography.Paragraph className='!mb-0 whitespace-pre-wrap'>{item.text}</Typography.Paragraph>
        </Card>
      </div>
    );
  }

  if (item.kind === 'assistant_message' || item.kind === 'assistant_draft') {
    return (
      <div className='flex justify-start'>
        <Card className='control-card w-full max-w-[82%]'>
          <div className='mb-8px flex items-center justify-between gap-12px'>
            <div className='flex items-center gap-8px'>
              <Typography.Text className='block text-12px uppercase tracking-[0.18em] text-[var(--control-subtle)]'>
                assistant
              </Typography.Text>
              {item.kind === 'assistant_draft' ? <Tag color='arcoblue'>draft</Tag> : null}
            </div>
            {renderCompactTimestamp(item.createdAt)}
          </div>
          <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words'>{item.text}</Typography.Paragraph>
        </Card>
      </div>
    );
  }

  if (item.kind === 'assistant_tool_call') {
    return <AssistantToolCallCard item={item} />;
  }

  if (item.kind === 'hitl_request') {
    return (
      <div className='flex justify-center'>
        <Card className='control-card w-full max-w-[88%] border-[rgba(209,142,31,0.35)] bg-[rgba(209,142,31,0.08)]'>
          <div className='mb-8px flex items-center justify-between gap-12px'>
            <Typography.Text className='block text-12px uppercase tracking-[0.18em] text-[var(--control-warning)]'>
              hitl_request
            </Typography.Text>
            {renderCompactTimestamp(item.createdAt)}
          </div>
          <Typography.Paragraph className='!mb-0'>{item.title}</Typography.Paragraph>
        </Card>
      </div>
    );
  }

  return null;
}

function renderToolTimelineItem(item: ToolTimelineItem) {
  const argumentsBlock = renderStructuredBlock('arguments', extractToolArguments(item));
  const payloadBlock = renderStructuredBlock('payload', extractToolStructuredPayload(item));
  const outputText = item.text?.trim();

  return (
    <Card
      className='control-muted-card'
      style={
        item.isError
          ? {
              borderColor: 'rgba(196, 94, 89, 0.35)',
              background: 'rgba(196, 94, 89, 0.08)',
            }
          : undefined
      }
    >
      <div className='mb-10px flex items-center justify-between gap-12px'>
        <Typography.Text
          className='text-12px uppercase tracking-[0.18em]'
          style={{ color: item.isError ? 'var(--control-danger)' : 'var(--control-subtle)' }}
        >
          tool {item.phase}
        </Typography.Text>
        <Typography.Text className='text-[var(--control-subtle)]'>{formatDateTime(item.createdAt)}</Typography.Text>
      </div>
      <Typography.Text className='block font-semibold'>{item.toolName ?? 'unknown_tool'}</Typography.Text>
      <Typography.Text className='mt-4px block break-all text-[var(--control-subtle)]'>
        {item.toolCallId ?? 'no tool_call_id'}
      </Typography.Text>
      {argumentsBlock}
      {outputText ? (
        <div className='mt-12px'>
          <Typography.Text className='mb-6px block text-[var(--control-subtle)]'>output</Typography.Text>
          <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words'>{outputText}</Typography.Paragraph>
        </div>
      ) : null}
      {payloadBlock}
    </Card>
  );
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
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [uploadedWorkspaceFiles, setUploadedWorkspaceFiles] = useState<string[]>([]);
  const [runtimeState, setRuntimeState] = useState(() => createRuntimeStateFromHistory([]));

  const agentsQuery = useSWR('chat-agents', () => controlClient.agents.list({ pageSize: 100, pageNumber: 1 }));
  const sessionsQuery = useSWR(
    selectedAgentName ? ['chat-sessions', selectedAgentName] : null,
    () => controlClient.sessions.list({ agentName: selectedAgentName, pageSize: 50 }),
  );
  const messagesQuery = useSWR(
    selectedAgentName && selectedThreadId ? ['chat-messages', selectedAgentName, selectedThreadId] : null,
    () => controlClient.sessions.getMessages(selectedAgentName!, selectedThreadId!, { pageSize: 200 }),
  );

  useEffect(() => {
    if (!messagesQuery.data || isRunActive(runtimeState.runStatus)) {
      return;
    }
    setRuntimeState(createRuntimeStateFromHistory(messagesQuery.data.messages));
  }, [messagesQuery.data, runtimeState.runStatus]);

  useEffect(() => {
    if (runtimeState.pendingInterrupts.length > 0) {
      setInspectorOpen(true);
    }
  }, [runtimeState.pendingInterrupts.length]);

  useEffect(() => {
    const viewport = timelineViewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTop = viewport.scrollHeight;
  }, [runtimeState.timeline]);

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
    };
  }, []);

  const agentOptions = useMemo(
    () => (agentsQuery.data?.agents ?? []).map((item) => ({ label: item.name ?? 'unnamed-agent', value: item.name ?? '' })),
    [agentsQuery.data?.agents],
  );

  const sessionItems = sessionsQuery.data?.sessions ?? [];
  const selectedSession = useMemo(
    () => sessionItems.find((item) => item.thread_id === selectedThreadId),
    [selectedThreadId, sessionItems],
  );
  const threadOptions = useMemo(
    () =>
      sessionItems
        .filter((item) => Boolean(item.thread_id))
        .map((item) => ({
          label: `${item.thread_id ?? 'pending'}${typeof item.message_count === 'number' ? ` (${item.message_count})` : ''}`,
          value: item.thread_id ?? '',
        })),
    [sessionItems],
  );
  const chatTimelineItems = useMemo(
    () => createConversationTimeline(runtimeState.timeline).filter((item) => item.kind !== 'system_event'),
    [runtimeState.timeline],
  );
  const toolTimelineItems = useMemo(
    () => runtimeState.timeline.filter((item): item is ToolTimelineItem => item.kind === 'tool_event'),
    [runtimeState.timeline],
  );
  const statusView = formatStatus(runtimeState.runStatus);
  const hasPendingInterrupts = runtimeState.pendingInterrupts.length > 0;
  const composerDisabled = !selectedAgentName || isRunActive(runtimeState.runStatus) || uploadingFiles;

  async function startRun(): Promise<void> {
    if (!selectedAgentName) {
      Message.warning('Please select an agent first.');
      return;
    }
    if (isRunActive(runtimeState.runStatus)) {
      Message.warning('The current run is still active. Wait for it to finish, cancel it, or resolve HITL first.');
      return;
    }
    const message = composerValue.trim();
    if (!message) {
      return;
    }

    setComposerValue('');
    setRuntimeState((previous) => appendUserMessage(previous, message));
    setRunSessionId(undefined);

    const controller = new AbortController();
    streamAbortRef.current = controller;

    try {
      await controlClient.runs.stream(
        selectedAgentName,
        {
          message,
          thread_id: selectedThreadId,
        },
        {
          signal: controller.signal,
          onOpen: ({ runSessionId: nextRunSessionId }) => {
            setRunSessionId(nextRunSessionId);
          },
          onEvent: (eventName, payload) => {
            if (eventName === 'run_session' && typeof payload === 'object' && payload !== null && 'session_id' in payload) {
              const value = payload.session_id;
              if (typeof value === 'string') {
                setRunSessionId(value);
              }
              return;
            }

            if (eventName === 'transport_error' && typeof payload === 'object' && payload !== null && 'error' in payload) {
              Message.error(typeof payload.error === 'string' ? payload.error : 'stream transport error');
              return;
            }

            if (!isRuntimeEvent(payload)) {
              return;
            }

            if (payload.thread_id && selectedAgentName && payload.thread_id !== selectedThreadId) {
              void navigate(links.chatThread(selectedAgentName, payload.thread_id), { replace: true });
            }

            setRuntimeState((previous) => reduceRuntimeEvent(previous, payload));
          },
          onClose: () => {
            setRunSessionId(undefined);
            void sessionsQuery.mutate();
            void messagesQuery.mutate();
          },
        },
      );
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'run stream failed');
      setRuntimeState((previous) => ({
        ...previous,
        runStatus: 'failed',
      }));
    } finally {
      streamAbortRef.current = null;
    }
  }

  async function cancelRun(): Promise<void> {
    if (!runSessionId) {
      Message.warning('No cancelable run_session is available.');
      return;
    }
    setRuntimeState((previous) => markRunCanceling(previous));
    try {
      await controlClient.runs.cancel(runSessionId, { reason: 'user_requested' });
      Message.success('cancel request sent');
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'cancel failed');
    }
  }

  function openWorkspaceUploadPicker(): void {
    if (!selectedAgentName) {
      Message.warning('Please select an agent first.');
      return;
    }
    if (isRunActive(runtimeState.runStatus)) {
      Message.warning('Wait for the current run to finish before uploading new files.');
      return;
    }
    fileInputRef.current?.click();
  }

  async function handleWorkspaceFilesSelected(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (files.length === 0) {
      return;
    }
    if (!selectedAgentName) {
      Message.warning('Please select an agent first.');
      return;
    }
    if (isRunActive(runtimeState.runStatus)) {
      Message.warning('Wait for the current run to finish before uploading new files.');
      return;
    }

    setUploadingFiles(true);
    try {
      const response = await controlClient.agents.uploadWorkspaceFiles(
        selectedAgentName,
        files,
        selectedThreadId,
      );

      const successful = (response.files ?? []).filter((item) => !item.error && item.path);
      const failed = (response.files ?? []).filter((item) => item.error);
      if (successful.length > 0) {
        setUploadedWorkspaceFiles((previous) => {
          const next = new Set(previous);
          for (const item of successful) {
            if (item.path) {
              next.add(item.path);
            }
          }
          return Array.from(next);
        });
      }

      if (response.thread_id && selectedAgentName && response.thread_id !== selectedThreadId) {
        setRuntimeState(createRuntimeStateFromHistory([]));
        void navigate(links.chatThread(selectedAgentName, response.thread_id), { replace: !selectedThreadId });
      }

      void sessionsQuery.mutate();
      void messagesQuery.mutate();

      if (successful.length > 0 && failed.length === 0) {
        Message.success(`uploaded ${successful.length} file${successful.length === 1 ? '' : 's'} to workspace`);
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
    if (!runSessionId) {
      Message.warning('No active run_session is available.');
      return;
    }
    try {
      await controlClient.runs.submitHitl(runSessionId, {
        interrupt_id: interrupt.interruptId,
        decisions: [{ type }],
      });
      setRuntimeState((previous) => markInterruptResolved(previous, interrupt.interruptId));
      Message.success(`${type} submitted`);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'submit hitl decision failed');
    }
  }

  function handleAgentChange(value: string | number | Record<string, unknown> | undefined): void {
    if (isRunActive(runtimeState.runStatus)) {
      Message.warning('The current run is still active. Switching agents is disabled.');
      return;
    }
    const nextAgentName = typeof value === 'string' ? value : '';
    resetWorkspace();
    if (!nextAgentName) {
      void navigate(links.chatRoot());
      return;
    }
    void navigate(links.chatAgent(nextAgentName));
  }

  function handleThreadChange(value: string | number | Record<string, unknown> | undefined): void {
    if (!selectedAgentName) {
      Message.warning('Please select an agent first.');
      return;
    }
    if (isRunActive(runtimeState.runStatus)) {
      Message.warning('The current run is still active. Switching threads is disabled.');
      return;
    }
    const nextThreadId = typeof value === 'string' ? value : '';
    resetWorkspace();
    if (!nextThreadId) {
      void navigate(links.chatAgent(selectedAgentName));
      return;
    }
    void navigate(links.chatThread(selectedAgentName, nextThreadId));
  }

  function handleNewConversation(): void {
    if (!selectedAgentName) {
      Message.warning('Please select an agent first.');
      return;
    }
    if (isRunActive(runtimeState.runStatus)) {
      Message.warning('The current run is still active. Creating a new conversation is disabled.');
      return;
    }
    resetWorkspace();
    void navigate(links.chatAgent(selectedAgentName));
  }

  function resetWorkspace(): void {
    setRunSessionId(undefined);
    setComposerValue('');
    setInspectorOpen(false);
    setUploadingFiles(false);
    setUploadedWorkspaceFiles([]);
    setRuntimeState(createRuntimeStateFromHistory([]));
  }

  return (
    <div className='flex h-full min-h-0 flex-col overflow-hidden'>
      <Card
        className='control-card min-h-0 flex flex-1 flex-col overflow-hidden'
        style={{ height: '100%' }}
        bodyStyle={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}
      >
        <div className='mb-10px shrink-0'>
          <div className='flex flex-wrap items-center justify-between gap-12px'>
            <Typography.Title heading={5} className='!mb-0 !mt-0'>
              {selectedAgentName || 'No agent selected'}
            </Typography.Title>

            <Space wrap>
              <Button
                type='text'
                aria-label='Refresh'
                className='control-quiet-icon-button'
                style={{ minWidth: 40, width: 40, paddingInline: 0 }}
                icon={<Refresh theme='outline' size='16' fill='currentColor' />}
                onClick={() => {
                  void agentsQuery.mutate();
                  void sessionsQuery.mutate();
                  void messagesQuery.mutate();
                }}
              />
              <Tag color={statusView.color}>{statusView.text}</Tag>
              <Select
                allowClear
                placeholder='Agent'
                options={agentOptions}
                value={selectedAgentName}
                style={{ width: 220 }}
                onChange={handleAgentChange}
              />
              <Select
                allowClear
                showSearch
                placeholder='Thread'
                options={threadOptions}
                value={selectedThreadId}
                disabled={!selectedAgentName}
                style={{ width: 260 }}
                onChange={handleThreadChange}
              />
              <Button
                type='outline'
                style={{ minWidth: 64 }}
                onClick={() => {
                  handleNewConversation();
                }}
              >
                new
              </Button>
              <Button type={inspectorOpen ? 'secondary' : 'outline'} onClick={() => setInspectorOpen((previous) => !previous)}>
                {hasPendingInterrupts ? `Inspector (${runtimeState.pendingInterrupts.length})` : 'Inspector'}
              </Button>
            </Space>
          </div>
          <Typography.Text className='mt-6px block break-all text-[var(--control-subtle)]'>
            {selectedThreadId || 'A new thread will be created after the first successful run.'}
          </Typography.Text>
        </div>

        {hasPendingInterrupts && !inspectorOpen ? (
          <Card className='control-card mb-12px shrink-0 border-[rgba(209,142,31,0.35)] bg-[rgba(209,142,31,0.08)]'>
            <div className='flex items-center justify-between gap-12px'>
              <div>
                <Typography.Text className='block font-semibold text-[var(--control-warning)]'>
                  Pending HITL approvals
                </Typography.Text>
                <Typography.Text className='text-[var(--control-subtle)]'>
                  {runtimeState.pendingInterrupts.length} approval request(s) are waiting in the inspector drawer.
                </Typography.Text>
              </div>
              <Button type='primary' onClick={() => setInspectorOpen(true)}>
                Open Inspector
              </Button>
            </div>
          </Card>
        ) : null}

        <div className='min-h-0 flex-1 overflow-hidden'>
          {messagesQuery.isLoading && !isRunActive(runtimeState.runStatus) ? (
            <div className='flex h-full items-center justify-center'>
              <Spin />
            </div>
          ) : chatTimelineItems.length === 0 ? (
            <div className='control-muted-card flex h-full min-h-0 flex-center flex-col gap-8px'>
              <RobotOne theme='outline' size='28' fill='var(--control-primary)' />
              <Typography.Text className='text-[var(--control-text)]'>
                {selectedAgentName ? 'Start a new conversation with the selected agent.' : 'Select an agent from the top bar.'}
              </Typography.Text>
              <Typography.Text className='text-center text-[var(--control-subtle)]'>
                {selectedAgentName
                  ? 'History messages and the active run share the same chat timeline.'
                  : 'Use the agent and thread selectors above to enter an existing session or start a new one.'}
              </Typography.Text>
            </div>
          ) : (
            <div ref={timelineViewportRef} className='control-scroll flex h-full min-h-0 flex-col gap-12px overflow-auto pr-4px'>
              {chatTimelineItems.map((item) => (
                <div key={item.id}>{renderTimelineItem(item)}</div>
              ))}
            </div>
          )}
        </div>

        <div className='mt-12px shrink-0 border-t border-[var(--control-border)] bg-[var(--control-panel)] pt-12px'>
          <input
            ref={fileInputRef}
            type='file'
            multiple
            className='hidden'
            onChange={(event) => {
              void handleWorkspaceFilesSelected(event);
            }}
          />
          {uploadedWorkspaceFiles.length > 0 ? (
            <div className='mb-12px flex flex-wrap items-center gap-8px'>
              <Typography.Text className='text-[var(--control-subtle)]'>workspace files</Typography.Text>
              {uploadedWorkspaceFiles.map((path) => (
                <Tag key={path} color='arcoblue'>
                  {path}
                </Tag>
              ))}
            </div>
          ) : null}
          <TextArea
            autoSize={{ minRows: 4, maxRows: 10 }}
            placeholder='Type a message. Press Enter to send and Shift+Enter for a new line.'
            value={composerValue}
            disabled={composerDisabled}
            onChange={setComposerValue}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void startRun();
              }
            }}
          />
          <div className='mt-12px flex flex-wrap items-center justify-between gap-12px'>
            <Typography.Text className='text-[var(--control-subtle)]'>
              {uploadingFiles
                ? 'Uploading files to the current thread workspace...'
                : runtimeState.runStatus === 'waiting_hitl'
                ? 'Sending is paused until the pending HITL request is resolved.'
                : isRunActive(runtimeState.runStatus)
                  ? 'The current run is still active. Wait, cancel, or resolve HITL before sending again.'
                  : 'Press Enter to send. Use Shift+Enter for a new line.'}
            </Typography.Text>
            <Space wrap>
              <Button
                type='outline'
                loading={uploadingFiles}
                disabled={!selectedAgentName || isRunActive(runtimeState.runStatus)}
                onClick={openWorkspaceUploadPicker}
              >
                Upload
              </Button>
              <Button
                icon={<Pause theme='outline' size='16' fill='currentColor' />}
                disabled={!runSessionId || !isRunActive(runtimeState.runStatus)}
                onClick={() => {
                  void cancelRun();
                }}
              >
                Cancel
              </Button>
              <Button
                type='primary'
                icon={<Send theme='outline' size='16' fill='currentColor' />}
                disabled={composerDisabled || !composerValue.trim()}
                onClick={() => {
                  void startRun();
                }}
              >
                Send
              </Button>
            </Space>
          </div>
        </div>
      </Card>

      <Drawer
        width={380}
        visible={inspectorOpen}
        placement='right'
        title='Inspector'
        mask={false}
        footer={null}
        unmountOnExit={false}
        onCancel={() => setInspectorOpen(false)}
      >
        <div className='flex flex-col gap-16px'>
          <Card className='control-card'>
            <Typography.Text className='mb-12px block text-12px uppercase tracking-[0.2em] text-[var(--control-subtle)]'>
              run status
            </Typography.Text>
            <Space direction='vertical' size='large' className='w-full'>
              <MetaRow label='status' value={<Tag color={statusView.color}>{statusView.text}</Tag>} />
              <MetaRow label='agent' value={selectedAgentName ?? 'n/a'} />
              <MetaRow label='thread_id' value={selectedThreadId ?? 'pending'} />
              <MetaRow label='run_session_id' value={runSessionId ?? 'not established'} />
              <MetaRow label='timeline items' value={String(runtimeState.timeline.length)} />
            </Space>
          </Card>

          <Card className='control-card'>
            <Typography.Text className='mb-12px block text-12px uppercase tracking-[0.2em] text-[var(--control-subtle)]'>
              pending HITL
            </Typography.Text>
            {runtimeState.pendingInterrupts.length === 0 ? (
              <Empty description='No pending approvals.' />
            ) : (
              <div className='flex flex-col gap-12px'>
                {runtimeState.pendingInterrupts.map((interrupt) => (
                  <Card key={interrupt.interruptId} className='control-muted-card'>
                    <Typography.Text className='mb-8px block font-semibold'>{interrupt.title}</Typography.Text>
                    <List
                      size='small'
                      dataSource={interrupt.actionRequests}
                      render={(item) => (
                        <List.Item>
                          <Typography.Text>{item.name}</Typography.Text>
                        </List.Item>
                      )}
                    />
                    <div className='mt-12px flex justify-end gap-10px'>
                      <Button
                        status='danger'
                        icon={<CloseOne theme='outline' size='16' fill='currentColor' />}
                        onClick={() => {
                          void submitInterruptDecision(interrupt, 'reject');
                        }}
                      >
                        Reject
                      </Button>
                      <Button
                        type='primary'
                        icon={<Check theme='outline' size='16' fill='currentColor' />}
                        onClick={() => {
                          void submitInterruptDecision(interrupt, 'approve');
                        }}
                      >
                        Approve
                      </Button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </Card>

          <Card className='control-card'>
            <Typography.Text className='mb-12px block text-12px uppercase tracking-[0.2em] text-[var(--control-subtle)]'>
              tool timeline
            </Typography.Text>
            {toolTimelineItems.length === 0 ? (
              <Empty description='No tool events in this session yet.' />
            ) : (
              <div className='control-scroll flex max-h-320px flex-col gap-12px overflow-auto pr-4px'>
                {toolTimelineItems.map((item) => (
                  <div key={item.id}>{renderToolTimelineItem(item)}</div>
                ))}
              </div>
            )}
          </Card>

          <Card className='control-card'>
            <Typography.Text className='mb-12px block text-12px uppercase tracking-[0.2em] text-[var(--control-subtle)]'>
              session meta
            </Typography.Text>
            <Space direction='vertical' size='large' className='w-full'>
              <MetaRow label='message_count' value={String(selectedSession?.message_count ?? 0)} />
              <MetaRow label='checkpoint_count' value={String(selectedSession?.checkpoint_count ?? 0)} />
              <MetaRow label='latest_checkpoint' value={selectedSession?.latest_checkpoint_id ?? 'n/a'} />
              <MetaRow label='history_mode' value={selectedSession?.history_mode ?? 'n/a'} />
              <MetaRow label='agent_status' value={selectedSession?.agent_status ?? 'n/a'} />
              <MetaRow label='updated_at' value={formatDateTime(selectedSession?.updated_at)} />
            </Space>
            <div className='mt-16px'>
              <Typography.Text className='mb-8px block text-[var(--control-subtle)]'>initial_prompt</Typography.Text>
              <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words'>
                {selectedSession?.initial_prompt ?? 'No persisted prompt metadata for this thread yet.'}
              </Typography.Paragraph>
            </div>
          </Card>
        </div>
      </Drawer>
    </div>
  );
}
