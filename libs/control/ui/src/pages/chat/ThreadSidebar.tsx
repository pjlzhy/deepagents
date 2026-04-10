import { MessageOne } from '@icon-park/react';
import { Tooltip } from '@arco-design/web-react';
import { useMemo } from 'react';
import type { SessionSummaryDTO } from '@/shared/types/api';

const CYAN = '#00f0ff';

export type ThreadSidebarProps = {
  selectedThreadId?: string;
  sessions: SessionSummaryDTO[];
  selectedAgentName?: string;
  onThreadSelect: (threadId: string) => void;
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

function truncatePrompt(value?: string, max = 60): string {
  if (!value) return 'New conversation';
  const line = value.split(/\r?\n/).find((l) => l.trim()) ?? value;
  const trimmed = line.trim();
  return trimmed.length <= max ? trimmed : `${trimmed.slice(0, max - 1)}...`;
}

export default function ThreadSidebar(props: ThreadSidebarProps) {
  const { selectedThreadId, sessions, selectedAgentName, onThreadSelect } = props;

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

  return (
    <div
      className='flex h-full w-44px shrink-0 flex-col items-center py-8px'
      style={{ borderRight: '1px solid var(--control-border)', background: 'rgba(12,16,36,0.97)' }}
    >
      {/* Thread icon list */}
      <div className='control-scroll flex min-h-0 flex-1 flex-col items-center gap-2px overflow-auto'>
        {sortedSessions.length === 0 ? (
          <Tooltip content={selectedAgentName ? 'No conversations' : 'Select an agent'} position='right' mini>
            <div className='flex-center h-30px w-30px opacity-40'>
              <MessageOne theme='outline' size='14' fill='var(--control-subtle)' />
            </div>
          </Tooltip>
        ) : (
          sortedSessions.map((session) => {
            const isActive = session.thread_id === selectedThreadId;
            const label = truncatePrompt(session.initial_prompt);
            const time = formatThreadTime(session.updated_at);
            return (
              <Tooltip
                key={session.thread_id}
                position='right'
                mini
                content={
                  <div className='max-w-280px'>
                    <div className='text-12px leading-18px'>{label}</div>
                    {time ? <div className='mt-2px text-11px opacity-60'>{time}</div> : null}
                  </div>
                }
              >
                <button
                  type='button'
                  className='flex-center h-32px w-32px cursor-pointer border-none rd-8px transition-all duration-150'
                  style={{
                    background: isActive ? 'rgba(0,240,255,0.10)' : 'transparent',
                    boxShadow: isActive ? '0 0 8px rgba(0,240,255,0.12)' : 'none',
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) (e.currentTarget as HTMLElement).style.background = 'rgba(0,240,255,0.06)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) (e.currentTarget as HTMLElement).style.background = 'transparent';
                  }}
                  onClick={() => session.thread_id && onThreadSelect(session.thread_id)}
                >
                  <MessageOne
                    theme='outline'
                    size='14'
                    fill={isActive ? CYAN : 'var(--control-subtle)'}
                  />
                </button>
              </Tooltip>
            );
          })
        )}
      </div>
    </div>
  );
}
