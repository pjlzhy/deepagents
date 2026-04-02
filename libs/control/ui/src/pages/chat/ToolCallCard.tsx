import { useState } from 'react';
import type { ConversationTimelineItemVM } from '@/features/chat/runtimeEventParser';
import { AssistantAvatar } from './MessageBubble';

const CYAN = '#00f0ff';

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

  const isError = item.isError;
  const statusLabel = isError ? 'error' : item.status ?? 'running';
  const statusColor = isError ? '#ff3b5c' : item.status === 'completed' ? '#39ff14' : CYAN;

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
          className='rd-12px px-12px py-8px transition-all duration-200'
          style={{
            background: isError ? 'rgba(255,59,92,0.04)' : 'rgba(16,22,48,0.80)',
            border: isError ? '1px solid rgba(255,59,92,0.20)' : '1px solid rgba(0,240,255,0.10)',
            boxShadow: expanded ? `0 0 10px ${isError ? 'rgba(255,59,92,0.08)' : 'rgba(0,240,255,0.06)'}` : 'none',
          }}
        >
          {/* Header */}
          <div className='flex items-center gap-6px'>
            <span className='font-mono text-13px font-semibold' style={{ color: CYAN }}>{toolLabel}</span>
            {inlineArgs ? (
              <span className='min-w-0 flex-1 truncate font-mono text-12px text-[var(--control-subtle)]'>
                {inlineArgs}
              </span>
            ) : null}
            {/* Status chip */}
            <span
              className='ml-auto shrink-0 rd-full px-8px py-1px text-10px font-bold uppercase tracking-wider border border-solid'
              style={{
                color: statusColor,
                borderColor: `${statusColor}35`,
                background: `${statusColor}0a`,
              }}
            >
              {statusLabel}
            </span>
          </div>

          {/* Summary */}
          {resultTrimmed && !expanded ? (
            <div className='mt-4px truncate text-12px text-[var(--control-subtle)]'>
              {truncateText((resultTrimmed.split(/\r?\n/).find((l) => l.trim()) ?? resultTrimmed).trim(), 100)}
            </div>
          ) : null}

          {/* Expanded */}
          {expanded ? (
            <div className='mt-8px pt-8px' style={{ borderTop: '1px solid rgba(0,240,255,0.08)' }}>
              {item.arguments !== undefined ? (
                <div className='mb-6px'>
                  <span
                    className='mb-3px block text-10px uppercase tracking-wider font-bold'
                    style={{ color: CYAN }}
                  >
                    arguments
                  </span>
                  <pre
                    className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-8px p-8px font-mono text-12px text-[var(--control-text)]'
                    style={{ background: 'rgba(0,240,255,0.03)', border: '1px solid rgba(0,240,255,0.06)' }}
                  >
                    {formatJson(item.arguments)}
                  </pre>
                </div>
              ) : null}
              {resultTrimmed ? (
                <div>
                  <span
                    className='mb-3px block text-10px uppercase tracking-wider font-bold'
                    style={{ color: '#39ff14' }}
                  >
                    result
                  </span>
                  <pre
                    className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-8px p-8px font-mono text-12px text-[var(--control-text)]'
                    style={{ background: 'rgba(57,255,20,0.03)', border: '1px solid rgba(57,255,20,0.06)' }}
                  >
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
