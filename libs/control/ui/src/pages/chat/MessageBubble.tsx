import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, CloseOne, RobotOne, User } from '@icon-park/react';
import { Button } from '@arco-design/web-react';
import { useState, type ReactNode } from 'react';
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
        className='max-w-[85%] min-w-280px rd-12px px-14px py-9px'
        style={{
          background: 'rgba(255,159,26,0.06)',
          border: '1px solid rgba(255,159,26,0.22)',
          boxShadow: '0 0 10px rgba(255,159,26,0.06)',
        }}
      >
        <div className='text-center'>
          <span className='text-11px font-semibold uppercase tracking-widest text-[var(--control-warning)]'>
            approval required
          </span>
        </div>
        {item.actionRequests.length > 0 ? (
          <div className='mt-6px flex flex-col gap-6px'>
            {item.actionRequests.map((req, i) => (
              <div
                key={i}
                className='rd-8px px-10px py-8px'
                style={{ background: 'rgba(255,159,26,0.04)', border: '1px solid rgba(255,159,26,0.10)' }}
              >
                <span
                  className='rd-4px px-6px py-1px text-11px font-semibold font-mono'
                  style={{ color: 'var(--control-warning)', background: 'rgba(255,159,26,0.10)', border: '1px solid rgba(255,159,26,0.18)' }}
                >
                  {req.name}
                </span>
                {req.description ? (
                  <div className='mt-4px whitespace-pre-wrap text-12px leading-18px text-[var(--control-text)]'>
                    {req.description}
                  </div>
                ) : null}
                {req.arguments && typeof req.arguments === 'object' ? (
                  <HitlArguments args={req.arguments as Record<string, unknown>} />
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className='mt-3px text-center text-14px text-[var(--control-text)]'>{item.title}</div>
        )}
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
          <div className='mt-6px text-center text-12px text-[var(--control-subtle)]'>resolved</div>
        ) : null}
        <div className='mt-3px text-center'>
          <Timestamp value={item.createdAt} />
        </div>
      </div>
    </div>
  );
}

/** Max characters for an argument value to be shown inline (not collapsed). */
const ARG_INLINE_LIMIT = 80;
/** Lines shown in collapsed preview for long values. */
const ARG_PREVIEW_LINES = 4;

function HitlArguments(props: { args: Record<string, unknown> }) {
  const { args } = props;
  const entries = Object.entries(args);
  if (entries.length === 0) return null;

  const inlineEntries: [string, string][] = [];
  const longEntries: [string, string][] = [];

  for (const [key, value] of entries) {
    const display = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    if (display.length <= ARG_INLINE_LIMIT && !display.includes('\n')) {
      inlineEntries.push([key, display]);
    } else {
      longEntries.push([key, display]);
    }
  }

  return (
    <div
      className='mt-4px rd-6px px-8px py-6px font-mono text-11px leading-16px'
      style={{ background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.06)' }}
    >
      {inlineEntries.map(([key, value]) => (
        <div key={key} className='mb-2px'>
          <span style={{ color: 'var(--control-warning)', opacity: 0.8 }}>{key}</span>
          <span style={{ color: 'var(--control-subtle)' }}>{': '}</span>
          <span style={{ color: 'var(--control-text)', opacity: 0.85 }}>{value}</span>
        </div>
      ))}
      {longEntries.map(([key, value]) => (
        <CollapsibleArgValue key={key} name={key} value={value} />
      ))}
    </div>
  );
}

function CollapsibleArgValue(props: { name: string; value: string }) {
  const { name, value } = props;
  const [expanded, setExpanded] = useState(false);

  const lines = value.split('\n');
  const totalLines = lines.length;
  const totalChars = value.length;
  const needsCollapse = totalLines > ARG_PREVIEW_LINES || totalChars > ARG_INLINE_LIMIT * 3;

  const preview = needsCollapse && !expanded
    ? lines.slice(0, ARG_PREVIEW_LINES).join('\n')
    : value;

  return (
    <div className='mb-2px'>
      <div className='flex items-center gap-4px'>
        <span style={{ color: 'var(--control-warning)', opacity: 0.8 }}>{name}</span>
        {needsCollapse ? (
          <span
            className='cursor-pointer select-none rd-3px px-4px text-10px'
            style={{ color: 'var(--control-primary)', background: 'rgba(0,240,255,0.08)' }}
            onClick={() => setExpanded((prev) => !prev)}
          >
            {expanded ? 'collapse' : `${totalLines} lines · ${formatArgSize(totalChars)}`}
          </span>
        ) : null}
      </div>
      <div
        className='mt-1px whitespace-pre-wrap break-all'
        style={{
          color: 'var(--control-text)',
          opacity: 0.85,
          maxHeight: expanded ? 'none' : '80px',
          overflow: 'hidden',
        }}
      >
        {preview}
        {needsCollapse && !expanded ? (
          <span style={{ color: 'var(--control-subtle)' }}>{' …'}</span>
        ) : null}
      </div>
    </div>
  );
}

function formatArgSize(chars: number): string {
  if (chars < 1024) return `${chars} chars`;
  return `${(chars / 1024).toFixed(1)}K chars`;
}
