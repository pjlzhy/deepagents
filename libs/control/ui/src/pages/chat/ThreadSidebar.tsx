import { Add, HamburgerButton, MessageOne } from '@icon-park/react';
import { Button, Select, Tooltip } from '@arco-design/web-react';
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

  // Collapsed state — narrow icon strip
  if (collapsed) {
    return (
      <div className='flex h-full w-44px shrink-0 flex-col items-center gap-4px border-r border-solid border-[var(--control-border)] bg-[var(--control-panel)] py-8px'>
        <Button
          type='text'
          size='small'
          className='control-quiet-icon-button'
          icon={<HamburgerButton theme='outline' size='16' fill='var(--control-subtle)' />}
          onClick={onToggleCollapse}
        />
        <Tooltip content='New chat' position='right' mini>
          <Button
            type='text'
            size='small'
            className='control-quiet-icon-button'
            icon={<Add theme='outline' size='16' fill='var(--control-primary)' />}
            disabled={!selectedAgentName || disabled}
            onClick={onNewChat}
          />
        </Tooltip>
        <div className='my-4px h-1px w-20px bg-[var(--control-border)]' />
        <div className='control-scroll flex min-h-0 flex-1 flex-col items-center gap-2px overflow-auto'>
          {sortedSessions.map((session) => {
            const isActive = session.thread_id === selectedThreadId;
            const label = truncatePrompt(session.initial_prompt, 60);
            const time = formatThreadTime(session.updated_at);
            return (
              <Tooltip
                key={session.thread_id}
                position='right'
                mini
                content={
                  <div className='max-w-200px'>
                    <div className='text-13px'>{label}</div>
                    {time ? <div className='mt-2px text-11px opacity-60'>{time}</div> : null}
                  </div>
                }
              >
                <button
                  type='button'
                  className={`flex-center h-30px w-30px cursor-pointer border-none rd-6px transition-colors ${
                    isActive
                      ? 'bg-[var(--control-primary-soft)]'
                      : 'bg-transparent hover:bg-[rgba(100,112,134,0.08)]'
                  }`}
                  onClick={() => session.thread_id && onThreadSelect(session.thread_id)}
                >
                  <MessageOne
                    theme='outline'
                    size='14'
                    fill={isActive ? 'var(--control-primary)' : 'var(--control-subtle)'}
                  />
                </button>
              </Tooltip>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className='flex h-full w-200px shrink-0 flex-col border-r border-solid border-[var(--control-border)] bg-[var(--control-panel)]'>
      {/* Header */}
      <div className='shrink-0 border-b border-solid border-[var(--control-border)] px-8px py-8px'>
        <div className='mb-6px flex items-center gap-4px'>
          <Select
            allowClear
            size='small'
            placeholder='Agent'
            options={agentOptions}
            value={selectedAgentName}
            disabled={disabled}
            className='min-w-0 flex-1'
            onChange={onAgentChange}
          />
          <Button
            type='text'
            size='mini'
            className='control-quiet-icon-button shrink-0'
            icon={<HamburgerButton theme='outline' size='14' fill='var(--control-subtle)' />}
            onClick={onToggleCollapse}
          />
        </div>
        <Button
          long
          size='small'
          type='primary'
          icon={<Add theme='outline' size='12' fill='currentColor' />}
          disabled={!selectedAgentName || disabled}
          onClick={onNewChat}
        >
          New Chat
        </Button>
      </div>

      {/* Thread list */}
      <div className='control-scroll min-h-0 flex-1 overflow-auto'>
        {sortedSessions.length === 0 ? (
          <div className='px-10px py-20px text-center text-12px text-[var(--control-subtle)]'>
            {selectedAgentName ? 'No conversations yet' : 'Select an agent'}
          </div>
        ) : (
          <div className='flex flex-col py-2px'>
            {sortedSessions.map((session) => {
              const isActive = session.thread_id === selectedThreadId;
              return (
                <button
                  key={session.thread_id}
                  type='button'
                  className={`mx-4px cursor-pointer border-none rd-6px px-8px py-6px text-left transition-colors ${
                    isActive
                      ? 'bg-[var(--control-primary-soft)]'
                      : 'bg-transparent hover:bg-[rgba(100,112,134,0.06)]'
                  }`}
                  onClick={() => session.thread_id && onThreadSelect(session.thread_id)}
                >
                  <div
                    className='truncate text-13px leading-18px text-[var(--control-text)]'
                    style={{ fontWeight: isActive ? 600 : 400 }}
                  >
                    {truncatePrompt(session.initial_prompt, 32)}
                  </div>
                  <div className='mt-1px text-11px text-[var(--control-subtle)]'>
                    {formatThreadTime(session.updated_at)}
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
