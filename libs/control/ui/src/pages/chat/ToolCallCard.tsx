import { Tag } from '@arco-design/web-react';
import { useState } from 'react';
import type { ConversationTimelineItemVM } from '@/features/chat/runtimeEventParser';
import { AssistantAvatar } from './MessageBubble';

type AssistantToolCallItem = Extract<ConversationTimelineItemVM, { kind: 'assistant_tool_call' }>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function truncateText(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

function normalizeCmd(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

function formatInlineArgs(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'string') return truncateText(normalizeCmd(value), 120);
  if (isRecord(value)) {
    if (typeof value.command === 'string') return truncateText(normalizeCmd(value.command), 120);
    const entries = Object.entries(value).filter(([, v]) => v !== undefined && v !== null && v !== '');
    if (entries.length === 0) return undefined;
    return truncateText(entries.map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(' '), 120);
  }
  try { return truncateText(JSON.stringify(value).replace(/\s+/g, ' '), 120); } catch { return undefined; }
}

function formatJson(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

export default function ToolCallCard(props: { item: AssistantToolCallItem }) {
  const { item } = props;
  const [expanded, setExpanded] = useState(false);
  const inlineArgs = formatInlineArgs(item.arguments);
  const toolLabel = item.toolName ?? 'unknown_tool';
  const resultTrimmed = item.output?.trim();

  const statusColor = item.isError ? 'red' : item.status === 'completed' ? 'green' : 'arcoblue';
  const statusLabel = item.isError ? 'error' : item.status ?? 'running';

  return (
    <div className='flex items-start justify-start gap-8px'>
      <AssistantAvatar />
      <div
        role='button'
        tabIndex={0}
        className='min-w-120px max-w-[80%] cursor-pointer outline-none'
        onClick={() => setExpanded((p) => !p)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded((p) => !p); } }}
      >
        <div
          className='rd-12px px-12px py-8px transition-colors'
          style={{
            background: item.isError ? 'rgba(255,59,92,0.04)' : 'rgba(16,22,48,0.80)',
            border: item.isError ? '1px solid rgba(255,59,92,0.20)' : '1px solid rgba(0,240,255,0.08)',
          }}
        >
          {/* Header */}
          <div className='flex items-center gap-6px'>
            <span className='font-mono text-13px font-medium text-[var(--control-primary)]'>{toolLabel}</span>
            {inlineArgs ? (
              <span className='min-w-0 flex-1 truncate font-mono text-12px text-[var(--control-subtle)]'>
                {inlineArgs}
              </span>
            ) : null}
            <Tag size='small' color={statusColor} className='ml-auto shrink-0'>
              {statusLabel}
            </Tag>
          </div>

          {/* Summary */}
          {resultTrimmed && !expanded ? (
            <div className='mt-4px truncate text-12px text-[var(--control-subtle)]'>
              {truncateText((resultTrimmed.split(/\r?\n/).find((l) => l.trim()) ?? resultTrimmed).trim(), 100)}
            </div>
          ) : null}

          {/* Expanded */}
          {expanded ? (
            <div className='mt-8px border-t border-solid border-[rgba(0,240,255,0.06)] pt-8px'>
              {item.arguments !== undefined ? (
                <div className='mb-6px'>
                  <span className='mb-3px block text-11px uppercase text-[var(--control-subtle)]'>arguments</span>
                  <pre className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-6px bg-[rgba(0,240,255,0.03)] p-8px font-mono text-12px text-[var(--control-text)]'>
                    {formatJson(item.arguments)}
                  </pre>
                </div>
              ) : null}
              {resultTrimmed ? (
                <div>
                  <span className='mb-3px block text-11px uppercase text-[var(--control-subtle)]'>result</span>
                  <pre className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-6px bg-[rgba(0,240,255,0.03)] p-8px font-mono text-12px text-[var(--control-text)]'>
                    {resultTrimmed}
                  </pre>
                </div>
              ) : null}
            </div>
          ) : null}

        </div>
      </div>
    </div>
  );
}
