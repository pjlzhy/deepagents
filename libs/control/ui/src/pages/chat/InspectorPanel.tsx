import { Check, CloseOne } from '@icon-park/react';
import { Button, Card, Empty, List, Space, Tag, Typography } from '@arco-design/web-react';
import type { PendingInterruptVM, RunStatusVM, TimelineItemVM } from '@/features/chat/runtimeEventParser';
import type { SessionSummaryDTO } from '@/shared/types/api';

type ToolTimelineItem = Extract<TimelineItemVM, { kind: 'tool_event' }>;

function formatStatus(status: RunStatusVM): { text: string; color: 'arcoblue' | 'green' | 'orange' | 'red' | 'gray' } {
  switch (status) {
    case 'starting': return { text: 'starting', color: 'arcoblue' };
    case 'streaming': return { text: 'streaming', color: 'green' };
    case 'waiting_hitl': return { text: 'waiting', color: 'orange' };
    case 'canceling': return { text: 'canceling', color: 'orange' };
    case 'completed': return { text: 'completed', color: 'green' };
    case 'canceled': return { text: 'canceled', color: 'gray' };
    case 'failed': return { text: 'failed', color: 'red' };
    default: return { text: 'idle', color: 'gray' };
  }
}

function formatDateTime(value?: string): string {
  if (!value) return 'n/a';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatStructuredValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function extractToolArguments(item: ToolTimelineItem): unknown {
  if (item.phase === 'start') return item.payload;
  if (isRecord(item.payload) && 'args' in item.payload) return item.payload.args;
  return undefined;
}

export type InspectorPanelProps = {
  runStatus: RunStatusVM;
  selectedAgentName?: string;
  selectedThreadId?: string;
  runSessionId?: string;
  selectedSession?: SessionSummaryDTO;
  pendingInterrupts: PendingInterruptVM[];
  timeline: TimelineItemVM[];
  onSubmitDecision: (interrupt: PendingInterruptVM, type: 'approve' | 'reject') => void;
};

export default function InspectorPanel(props: InspectorPanelProps) {
  const {
    runStatus,
    selectedAgentName,
    selectedThreadId,
    runSessionId,
    selectedSession,
    pendingInterrupts,
    timeline,
    onSubmitDecision,
  } = props;

  const statusView = formatStatus(runStatus);
  const toolItems = timeline.filter((item): item is ToolTimelineItem => item.kind === 'tool_event');

  return (
    <div className='control-scroll flex h-full w-320px shrink-0 flex-col gap-12px overflow-auto border-l border-solid border-[var(--control-border)] bg-[var(--control-panel)] p-12px'>
      {/* Run status */}
      <Card className='control-muted-card' bodyStyle={{ padding: 14 }}>
        <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>status</span>
        <div className='flex flex-col gap-6px'>
          <div className='flex justify-between'>
            <span className='text-[var(--control-subtle)]'>status</span>
            <Tag size='small' color={statusView.color}>{statusView.text}</Tag>
          </div>
          <div className='flex justify-between'>
            <span className='text-[var(--control-subtle)]'>agent</span>
            <span className='text-right'>{selectedAgentName ?? 'n/a'}</span>
          </div>
          <div className='flex justify-between'>
            <span className='text-[var(--control-subtle)]'>thread</span>
            <span className='max-w-[60%] truncate text-right text-12px'>{selectedThreadId ?? 'pending'}</span>
          </div>
          <div className='flex justify-between'>
            <span className='text-[var(--control-subtle)]'>session</span>
            <span className='max-w-[60%] truncate text-right text-12px'>{runSessionId ?? '-'}</span>
          </div>
        </div>
      </Card>

      {/* HITL approvals */}
      {pendingInterrupts.length > 0 ? (
        <Card className='control-muted-card border-[rgba(209,142,31,0.35)]' bodyStyle={{ padding: 14 }}>
          <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-warning)]'>
            pending approvals ({pendingInterrupts.length})
          </span>
          <div className='flex flex-col gap-10px'>
            {pendingInterrupts.map((interrupt) => (
              <div key={interrupt.interruptId} className='rd-8px bg-[rgba(209,142,31,0.06)] p-10px'>
                <Typography.Text className='mb-6px block font-semibold text-13px'>{interrupt.title}</Typography.Text>
                <List
                  size='small'
                  dataSource={interrupt.actionRequests}
                  render={(item) => (
                    <List.Item>
                      <Typography.Text className='text-12px'>{item.name}</Typography.Text>
                    </List.Item>
                  )}
                />
                <div className='mt-8px flex justify-end gap-8px'>
                  <Button
                    size='mini'
                    status='danger'
                    icon={<CloseOne theme='outline' size='14' fill='currentColor' />}
                    onClick={() => onSubmitDecision(interrupt, 'reject')}
                  >
                    Reject
                  </Button>
                  <Button
                    size='mini'
                    type='primary'
                    icon={<Check theme='outline' size='14' fill='currentColor' />}
                    onClick={() => onSubmitDecision(interrupt, 'approve')}
                  >
                    Approve
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {/* Tool timeline */}
      <Card className='control-muted-card' bodyStyle={{ padding: 14 }}>
        <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>tool events</span>
        {toolItems.length === 0 ? (
          <Empty description='No tool events yet' className='!my-8px' />
        ) : (
          <div className='control-scroll flex max-h-280px flex-col gap-8px overflow-auto'>
            {toolItems.map((item) => {
              const argsFormatted = formatStructuredValue(extractToolArguments(item));
              const outputText = item.text?.trim();
              return (
                <div
                  key={item.id}
                  className={`rd-8px border border-solid p-8px text-12px ${
                    item.isError
                      ? 'border-[rgba(196,94,89,0.3)] bg-[rgba(196,94,89,0.04)]'
                      : 'border-[var(--control-border)] bg-[var(--control-panel)]'
                  }`}
                >
                  <div className='flex items-center justify-between gap-4px'>
                    <span className='font-medium'>{item.toolName ?? 'unknown'}</span>
                    <span className='text-11px uppercase text-[var(--control-subtle)]'>{item.phase}</span>
                  </div>
                  {argsFormatted ? (
                    <pre className='!m-0 mt-4px overflow-auto whitespace-pre-wrap break-words rd-6px bg-[rgba(100,112,134,0.06)] p-6px text-11px'>
                      {argsFormatted}
                    </pre>
                  ) : null}
                  {outputText ? (
                    <Typography.Paragraph className='!mb-0 mt-4px whitespace-pre-wrap break-words text-12px'>
                      {outputText}
                    </Typography.Paragraph>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Session meta */}
      <Card className='control-muted-card' bodyStyle={{ padding: 14 }}>
        <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>session</span>
        <Space direction='vertical' size='small' className='w-full text-13px'>
          <div className='flex justify-between'>
            <span className='text-[var(--control-subtle)]'>messages</span>
            <span>{selectedSession?.message_count ?? 0}</span>
          </div>
          <div className='flex justify-between'>
            <span className='text-[var(--control-subtle)]'>checkpoints</span>
            <span>{selectedSession?.checkpoint_count ?? 0}</span>
          </div>
          <div className='flex justify-between'>
            <span className='text-[var(--control-subtle)]'>history_mode</span>
            <span>{selectedSession?.history_mode ?? 'n/a'}</span>
          </div>
          <div className='flex justify-between'>
            <span className='text-[var(--control-subtle)]'>updated_at</span>
            <span className='text-12px'>{formatDateTime(selectedSession?.updated_at)}</span>
          </div>
        </Space>
        {selectedSession?.initial_prompt ? (
          <div className='mt-10px border-t border-solid border-[var(--control-border)] pt-8px'>
            <span className='mb-4px block text-11px text-[var(--control-subtle)]'>initial_prompt</span>
            <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words text-12px'>
              {selectedSession.initial_prompt}
            </Typography.Paragraph>
          </div>
        ) : null}
      </Card>
    </div>
  );
}
