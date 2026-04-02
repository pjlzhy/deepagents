import { Typography } from '@arco-design/web-react';
import { RobotOne, User } from '@icon-park/react';
import type { ReactNode } from 'react';
import type { ConversationTimelineItemVM } from '@/features/chat/runtimeEventParser';

function formatCompactDateTime(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function Timestamp(props: { value?: string }): ReactNode {
  if (!props.value) return null;
  return <span className='text-11px text-[var(--control-subtle)]'>{formatCompactDateTime(props.value)}</span>;
}

type UserMessageItem = Extract<ConversationTimelineItemVM, { kind: 'user_message' }>;
type AssistantMessageItem = Extract<ConversationTimelineItemVM, { kind: 'assistant_message' | 'assistant_draft' }>;
type HitlRequestItem = Extract<ConversationTimelineItemVM, { kind: 'hitl_request' }>;

export function UserBubble(props: { item: UserMessageItem }) {
  const { item } = props;
  return (
    <div className='flex items-start justify-end gap-10px'>
      <div className='max-w-[75%]'>
        <div
          className='rd-16px rd-br-4px px-16px py-10px'
          style={{
            background: 'linear-gradient(135deg, rgba(0,240,255,0.15) 0%, rgba(0,240,255,0.08) 100%)',
            border: '1px solid rgba(0,240,255,0.25)',
          }}
        >
          <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words text-14px leading-22px text-[var(--control-text)]'>
            {item.text}
          </Typography.Paragraph>
        </div>
        <div className='mt-4px flex justify-end'>
          <Timestamp value={item.createdAt} />
        </div>
      </div>
      <div
        className='flex-center mt-2px h-32px w-32px shrink-0 rd-full'
        style={{ background: 'rgba(0,240,255,0.12)', border: '1px solid rgba(0,240,255,0.25)' }}
      >
        <User theme='outline' size='16' fill='var(--control-primary)' />
      </div>
    </div>
  );
}

export function AssistantBubble(props: { item: AssistantMessageItem }) {
  const { item } = props;
  return (
    <div className='flex items-start justify-start gap-10px'>
      <div
        className='flex-center mt-2px h-32px w-32px shrink-0 rd-full'
        style={{ background: 'rgba(255,45,149,0.10)', border: '1px solid rgba(255,45,149,0.20)' }}
      >
        <RobotOne theme='outline' size='16' fill='var(--control-accent)' />
      </div>
      <div className='max-w-[80%]'>
        <div
          className='rd-16px rd-tl-4px px-16px py-10px'
          style={{
            background: 'rgba(16,22,48,0.95)',
            border: '1px solid rgba(0,240,255,0.10)',
          }}
        >
          <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words text-14px leading-22px text-[var(--control-text)]'>
            {item.text}
          </Typography.Paragraph>
        </div>
        <div className='mt-4px flex items-center gap-6px'>
          <Timestamp value={item.createdAt} />
          {item.kind === 'assistant_draft' ? (
            <span
              className='rd-4px px-6px py-1px text-11px text-[var(--control-primary)]'
              style={{ background: 'rgba(0,240,255,0.08)', border: '1px solid rgba(0,240,255,0.15)' }}
            >
              streaming
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function HitlRequestBubble(props: { item: HitlRequestItem }) {
  const { item } = props;
  return (
    <div className='flex justify-center'>
      <div
        className='max-w-[85%] rd-12px px-16px py-10px text-center'
        style={{
          background: 'rgba(255,159,26,0.06)',
          border: '1px solid rgba(255,159,26,0.25)',
          boxShadow: '0 0 12px rgba(255,159,26,0.08)',
        }}
      >
        <span className='text-11px font-semibold uppercase tracking-widest text-[var(--control-warning)]'>
          approval required
        </span>
        <Typography.Paragraph className='!mb-0 mt-4px text-14px text-[var(--control-text)]'>{item.title}</Typography.Paragraph>
        <div className='mt-4px'>
          <Timestamp value={item.createdAt} />
        </div>
      </div>
    </div>
  );
}
