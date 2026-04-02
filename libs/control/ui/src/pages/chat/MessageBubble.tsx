import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, CloseOne, RobotOne, User } from '@icon-park/react';
import { Button } from '@arco-design/web-react';
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

export function UserAvatar() {
  return (
    <div
      className='flex-center mt-2px h-30px w-30px shrink-0 rd-full'
      style={{ background: 'rgba(0,240,255,0.12)', border: '1px solid rgba(0,240,255,0.20)' }}
    >
      <User theme='outline' size='14' fill='var(--control-primary)' />
    </div>
  );
}

export function AssistantAvatar() {
  return (
    <div
      className='flex-center mt-2px h-30px w-30px shrink-0 rd-full'
      style={{ background: 'rgba(255,45,149,0.10)', border: '1px solid rgba(255,45,149,0.18)' }}
    >
      <RobotOne theme='outline' size='14' fill='var(--control-accent)' />
    </div>
  );
}

type UserMessageItem = Extract<ConversationTimelineItemVM, { kind: 'user_message' }>;
type AssistantMessageItem = Extract<ConversationTimelineItemVM, { kind: 'assistant_message' | 'assistant_draft' }>;
type HitlRequestItem = Extract<ConversationTimelineItemVM, { kind: 'hitl_request' }>;

export function UserBubble(props: { item: UserMessageItem }) {
  const { item } = props;
  return (
    <div className='flex items-start justify-end gap-8px'>
      <div className='min-w-60px max-w-[75%]'>
        <div
          className='rd-14px rd-br-4px px-14px py-9px'
          style={{
            background: 'linear-gradient(135deg, rgba(0,240,255,0.14) 0%, rgba(0,240,255,0.06) 100%)',
            border: '1px solid rgba(0,240,255,0.22)',
          }}
        >
          <div className='whitespace-pre-wrap break-words text-14px leading-22px text-[var(--control-text)]'>
            {item.text}
          </div>
        </div>
        <div className='mt-3px flex justify-end'>
          <Timestamp value={item.createdAt} />
        </div>
      </div>
      <UserAvatar />
    </div>
  );
}

export function AssistantBubble(props: { item: AssistantMessageItem }) {
  const { item } = props;
  return (
    <div className='flex items-start justify-start gap-8px'>
      <AssistantAvatar />
      <div className='min-w-60px max-w-[80%]'>
        <div
          className='chat-markdown rd-14px rd-tl-4px px-14px py-9px'
          style={{
            background: 'rgba(16,22,48,0.92)',
            border: '1px solid rgba(0,240,255,0.08)',
          }}
        >
          <Markdown remarkPlugins={[remarkGfm]}>{item.text}</Markdown>
        </div>
        <div className='mt-3px flex items-center gap-6px'>
          <Timestamp value={item.createdAt} />
          {item.kind === 'assistant_draft' ? (
            <span
              className='rd-4px px-5px py-1px text-11px text-[var(--control-primary)]'
              style={{ background: 'rgba(0,240,255,0.08)', border: '1px solid rgba(0,240,255,0.12)' }}
            >
              streaming
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function HitlRequestBubble(props: {
  item: HitlRequestItem;
  resolved?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
}) {
  const { item, resolved, onApprove, onReject } = props;
  return (
    <div className='flex justify-center'>
      <div
        className='max-w-[85%] rd-12px px-14px py-9px text-center'
        style={{
          background: 'rgba(255,159,26,0.06)',
          border: '1px solid rgba(255,159,26,0.22)',
          boxShadow: '0 0 10px rgba(255,159,26,0.06)',
        }}
      >
        <span className='text-11px font-semibold uppercase tracking-widest text-[var(--control-warning)]'>
          approval required
        </span>
        <div className='mt-3px text-14px text-[var(--control-text)]'>{item.title}</div>
        {item.actionRequests.length > 0 ? (
          <div className='mt-6px flex flex-wrap justify-center gap-4px'>
            {item.actionRequests.map((req, i) => (
              <span
                key={i}
                className='rd-4px px-6px py-1px text-12px text-[var(--control-subtle)]'
                style={{ background: 'rgba(255,159,26,0.08)', border: '1px solid rgba(255,159,26,0.15)' }}
              >
                {req.name}
              </span>
            ))}
          </div>
        ) : null}
        {!resolved && (onApprove || onReject) ? (
          <div className='mt-8px flex justify-center gap-8px'>
            {onReject ? (
              <Button
                size='mini'
                status='danger'
                icon={<CloseOne theme='outline' size='14' fill='currentColor' />}
                onClick={onReject}
              >
                Reject
              </Button>
            ) : null}
            {onApprove ? (
              <Button
                size='mini'
                type='primary'
                icon={<Check theme='outline' size='14' fill='currentColor' />}
                onClick={onApprove}
              >
                Approve
              </Button>
            ) : null}
          </div>
        ) : resolved ? (
          <div className='mt-6px text-12px text-[var(--control-subtle)]'>resolved</div>
        ) : null}
        <div className='mt-3px'>
          <Timestamp value={item.createdAt} />
        </div>
      </div>
    </div>
  );
}
