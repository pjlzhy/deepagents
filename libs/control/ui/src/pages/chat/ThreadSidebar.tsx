import { Add, HamburgerButton } from '@icon-park/react';
import { Button, Select, Typography } from '@arco-design/web-react';
import { useMemo } from 'react';
import type { SessionSummaryDTO } from '@/shared/types/api';

export type ThreadSidebarProps = {
  agentOptions: { label: string; value: string }[];
  selectedAgentName?: string;
  selectedThreadId?: string;
  sessions: SessionSummaryDTO[];
  disabled?: boolean;
  collapsed?: boolean;
  onAgentChange: (value: string | number | Record<string, unknown> | undefined) => void;
  onThreadSelect: (threadId: string) => void;
  onNewChat: () => void;
  onToggleCollapse?: () => void;
};

function formatThreadTime(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function truncatePrompt(value?: string, max = 48): string {
  if (!value) return 'New conversation';
  const line = value.split(/\r?\n/).find((l) => l.trim()) ?? value;
  const trimmed = line.trim();
  return trimmed.length <= max ? trimmed : `${trimmed.slice(0, max - 1)}...`;
}

export default function ThreadSidebar(props: ThreadSidebarProps) {
  const {
    agentOptions,
    selectedAgentName,
    selectedThreadId,
    sessions,
    disabled,
    collapsed,
    onAgentChange,
    onThreadSelect,
    onNewChat,
    onToggleCollapse,
  } = props;

  const sortedSessions = useMemo(
    () =>
      [...sessions]
        .filter((s) => Boolean(s.thread_id))
        .sort((a, b) => {
          const ta = a.updated_at ? new Date(a.updated_at).getTime() : 0;
          const tb = b.updated_at ? new Date(b.updated_at).getTime() : 0;
          return tb - ta;
        }),
    [sessions],
  );

  // Collapsed state — narrow strip with toggle button
  if (collapsed) {
    return (
      <div className='flex h-full w-44px shrink-0 flex-col items-center border-r border-solid border-[var(--control-border)] bg-[var(--control-panel)] py-10px'>
        <Button
          type='text'
          size='small'
          className='control-quiet-icon-button'
          icon={<HamburgerButton theme='outline' size='18' fill='var(--control-subtle)' />}
          onClick={onToggleCollapse}
        />
      </div>
    );
  }

  return (
    <div className='flex h-full w-240px shrink-0 flex-col border-r border-solid border-[var(--control-border)] bg-[var(--control-panel)] transition-all duration-200'>
      {/* Agent selector + New Chat */}
      <div className='shrink-0 border-b border-solid border-[var(--control-border)] px-12px py-12px'>
        <div className='mb-8px flex items-center justify-between'>
          <Select
            allowClear
            placeholder='Select agent'
            options={agentOptions}
            value={selectedAgentName}
            disabled={disabled}
            className='min-w-0 flex-1'
            onChange={onAgentChange}
          />
          <Button
            type='text'
            size='small'
            className='control-quiet-icon-button ml-6px shrink-0'
            icon={<HamburgerButton theme='outline' size='16' fill='var(--control-subtle)' />}
            onClick={onToggleCollapse}
          />
        </div>
        <Button
          long
          type='primary'
          icon={<Add theme='outline' size='14' fill='currentColor' />}
          disabled={!selectedAgentName || disabled}
          onClick={onNewChat}
        >
          New Chat
        </Button>
      </div>

      {/* Thread list */}
      <div className='control-scroll min-h-0 flex-1 overflow-auto'>
        {sortedSessions.length === 0 ? (
          <div className='px-16px py-24px text-center'>
            <Typography.Text className='text-[var(--control-subtle)]'>
              {selectedAgentName ? 'No conversations yet' : 'Select an agent to start'}
            </Typography.Text>
          </div>
        ) : (
          <div className='flex flex-col py-4px'>
            {sortedSessions.map((session) => {
              const isActive = session.thread_id === selectedThreadId;
              return (
                <button
                  key={session.thread_id}
                  type='button'
                  className={`mx-6px cursor-pointer border-none rd-8px px-12px py-10px text-left transition-colors ${
                    isActive
                      ? 'bg-[var(--control-primary-soft)] font-semibold'
                      : 'bg-transparent hover:bg-[rgba(100,112,134,0.06)]'
                  }`}
                  onClick={() => session.thread_id && onThreadSelect(session.thread_id)}
                >
                  <div className='flex items-start justify-between gap-6px'>
                    <Typography.Text
                      className='block truncate text-14px leading-20px text-[var(--control-text)]'
                      style={{ fontWeight: isActive ? 600 : 400 }}
                    >
                      {truncatePrompt(session.initial_prompt)}
                    </Typography.Text>
                  </div>
                  <div className='mt-2px flex items-center gap-6px'>
                    <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                      {formatThreadTime(session.updated_at)}
                    </Typography.Text>
                    {typeof session.message_count === 'number' && session.message_count > 0 ? (
                      <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                        · {session.message_count} msgs
                      </Typography.Text>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
