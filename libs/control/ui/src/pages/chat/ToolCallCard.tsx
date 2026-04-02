import { Tag, Typography } from '@arco-design/web-react';
import { useState } from 'react';
import type { ConversationTimelineItemVM } from '@/features/chat/runtimeEventParser';

type AssistantToolCallItem = Extract<ConversationTimelineItemVM, { kind: 'assistant_tool_call' }>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function truncateText(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  if (maxLength <= 3) return value.slice(0, maxLength);
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
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'string') return truncateText(normalizeInlineCommand(value), 160);
  if (isRecord(value)) {
    if (typeof value.command === 'string') return truncateText(normalizeInlineCommand(value.command), 160);
    const entries = Object.entries(value).filter(([, entry]) => entry !== undefined && entry !== null && entry !== '');
    if (entries.length === 0) return undefined;
    const inline = entries.map(([key, entry]) => `${key}=${typeof entry === 'string' ? entry : JSON.stringify(entry)}`).join(' ');
    return truncateText(inline, 160);
  }
  try {
    const s = JSON.stringify(value, null, 2);
    return s ? truncateText(s.replace(/\s+/g, ' ').trim(), 160) : undefined;
  } catch {
    return undefined;
  }
}

function formatStructuredValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function ToolCallCard(props: { item: AssistantToolCallItem }) {
  const { item } = props;
  const [expanded, setExpanded] = useState(false);
  const inlineArgs = formatInlineToolArguments(item.arguments);
  const toolLabel = item.toolName ?? 'unknown_tool';
  const resultTrimmed = item.output?.trim();

  const summaryResult = resultTrimmed
    ? truncateText((resultTrimmed.split(/\r?\n/).find((l) => l.trim()) ?? resultTrimmed).trim(), 140)
    : item.isError
      ? 'Failed'
      : item.status === 'completed'
        ? 'Done'
        : 'Running...';

  return (
    <div className='flex justify-start'>
      <div
        role='button'
        tabIndex={0}
        className='max-w-[80%] w-full cursor-pointer outline-none'
        onClick={() => setExpanded((p) => !p)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded((p) => !p); } }}
      >
        <div
          className={`rd-12px border border-solid px-14px py-10px transition-colors ${
            item.isError
              ? 'border-[rgba(196,94,89,0.3)] bg-[rgba(196,94,89,0.04)]'
              : 'border-[var(--control-border)] bg-[var(--control-panel-muted)]'
          }`}
        >
          {/* Header row */}
          <div className='flex items-center gap-8px'>
            <span className='text-13px font-medium text-[var(--control-text)]'>{toolLabel}</span>
            {inlineArgs ? (
              <span className='min-w-0 flex-1 truncate text-12px text-[var(--control-subtle)]'>{inlineArgs}</span>
            ) : null}
            <Tag
              size='small'
              color={item.isError ? 'red' : item.status === 'completed' ? 'green' : 'arcoblue'}
              className='ml-auto shrink-0'
            >
              {item.isError ? 'error' : item.status}
            </Tag>
          </div>

          {/* Summary */}
          <Typography.Text className='mt-4px block truncate text-12px text-[var(--control-subtle)]'>
            {summaryResult}
          </Typography.Text>

          {/* Expanded detail */}
          {expanded ? (
            <div className='mt-10px border-t border-solid border-[var(--control-border)] pt-10px'>
              {item.arguments !== undefined ? (
                <div className='mb-8px'>
                  <span className='mb-4px block text-11px uppercase text-[var(--control-subtle)]'>arguments</span>
                  <pre className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-8px bg-[rgba(100,112,134,0.06)] p-10px text-12px text-[var(--control-text)]'>
                    {formatStructuredValue(item.arguments)}
                  </pre>
                </div>
              ) : null}
              {resultTrimmed ? (
                <div>
                  <span className='mb-4px block text-11px uppercase text-[var(--control-subtle)]'>result</span>
                  <Typography.Paragraph className='!mb-0 whitespace-pre-wrap break-words text-13px'>
                    {resultTrimmed}
                  </Typography.Paragraph>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
