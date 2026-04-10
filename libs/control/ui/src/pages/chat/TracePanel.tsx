import { useState, useMemo, useDeferredValue, useCallback } from 'react';
import { Button, Empty, Input, Select, Tag, Typography } from '@arco-design/web-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { TelemetryEventVM, TraceSpanVM } from '@/features/telemetry/traceModel';
import {
  formatCompactDateTime,
  stringifyValue,
  traceAccent,
  traceDurationLabel,
  traceNamespaceLabel,
  traceReasoningMarkdown,
  traceStatusLabel,
  traceSummary,
  type TraceDetailTab,
  type TraceStatusFilter,
} from '@/shared/utils/telemetryHelpers';
import SegmentedTabs from '@/shared/components/telemetry/SegmentedTabs';
import ScrollableViewport from '@/shared/components/telemetry/ScrollableViewport';
import TraceTreeRow from '@/shared/components/telemetry/TraceTreeRow';
import CollapsibleSection from '@/shared/components/telemetry/CollapsibleSection';
import MetadataTable from '@/shared/components/telemetry/MetadataTable';

type TracePanelProps = {
  traceSpans: TraceSpanVM[];
  events: TelemetryEventVM[];
};

/** Resolve output content for detail display, with model-kind fallbacks. */
function resolveOutputContent(span: TraceSpanVM): string {
  const outputStr = stringifyValue(span.output);
  if (outputStr) return outputStr;

  // For model steps: show tool_calls + messages composite
  if (span.kind === 'model') {
    const parts: Record<string, unknown> = {};
    if (span.toolCalls.length > 0) parts.tool_calls = span.toolCalls;
    if (span.messages.length > 0) parts.messages = span.messages;
    const text = stringifyValue(parts);
    if (text && text !== '{}') return text;
  }

  // Generic fallback: last message
  const lastMsg = span.messages.at(-1);
  if (lastMsg) return lastMsg;

  return 'n/a';
}

export default function TracePanel(props: TracePanelProps) {
  const [traceSearchFilter, setTraceSearchFilter] = useState('');
  const [traceStatusFilter, setTraceStatusFilter] = useState<TraceStatusFilter>('all');
  const [selectedTraceId, setSelectedTraceId] = useState<string | undefined>(undefined);
  const [traceDetailTab, setTraceDetailTab] = useState<TraceDetailTab>('input');
  const [collapsedSpanIds, setCollapsedSpanIds] = useState<Set<string>>(new Set());
  const deferredTraceSearch = useDeferredValue(traceSearchFilter);

  const filteredTraceSpans = useMemo(() => {
    const needle = deferredTraceSearch.trim().toLowerCase();
    return props.traceSpans.filter((span) => {
      if (traceStatusFilter !== 'all' && span.status !== traceStatusFilter) return false;
      if (!needle) return true;
      const haystacks = [
        span.kind,
        span.nodeName,
        traceNamespaceLabel(span),
        traceSummary(span),
        JSON.stringify(span.input ?? ''),
        JSON.stringify(span.output ?? ''),
        span.reasoning.join(' '),
      ];
      return haystacks.some((value) => value.toLowerCase().includes(needle));
    });
  }, [deferredTraceSearch, props.traceSpans, traceStatusFilter]);

  // Build parent→children map for tree collapse
  const childrenMap = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const span of filteredTraceSpans) {
      if (span.parentStepId) {
        const existing = map.get(span.parentStepId);
        if (existing) existing.push(span.id);
        else map.set(span.parentStepId, [span.id]);
      }
    }
    return map;
  }, [filteredTraceSpans]);

  // Collect all descendant IDs for a span (recursive)
  const getDescendantIds = useCallback((spanId: string): Set<string> => {
    const result = new Set<string>();
    const children = childrenMap.get(spanId) ?? [];
    for (const childId of children) {
      result.add(childId);
      for (const descId of getDescendantIds(childId)) {
        result.add(descId);
      }
    }
    return result;
  }, [childrenMap]);

  // Visible spans: hide descendants of collapsed parents
  const visibleSpans = useMemo(() => {
    const hiddenIds = new Set<string>();
    for (const collapsedId of collapsedSpanIds) {
      for (const descId of getDescendantIds(collapsedId)) {
        hiddenIds.add(descId);
      }
    }
    return filteredTraceSpans.filter((span) => !hiddenIds.has(span.id));
  }, [filteredTraceSpans, collapsedSpanIds, getDescendantIds]);

  const hiddenCount = filteredTraceSpans.length - visibleSpans.length;

  const selectedTrace = useMemo(
    () => filteredTraceSpans.find((span) => span.id === selectedTraceId) ?? filteredTraceSpans.at(0),
    [filteredTraceSpans, selectedTraceId],
  );

  function clearTraceFilters() {
    setTraceSearchFilter('');
    setTraceStatusFilter('all');
  }

  function toggleCollapse(spanId: string) {
    setCollapsedSpanIds((prev) => {
      const next = new Set(prev);
      if (next.has(spanId)) next.delete(spanId);
      else next.add(spanId);
      return next;
    });
  }

  return (
    <div className='flex h-full min-h-0 overflow-hidden'>
      {/* Left: trace span list - 40% */}
      <div className='flex min-h-0 flex-col overflow-hidden' style={{ width: '40%', borderRight: '1px solid var(--control-border)' }}>
        <div className='border-b border-solid border-[var(--control-border)] px-12px py-10px'>
          <div className='mb-8px flex items-center justify-between gap-8px'>
            <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>
              trace ({filteredTraceSpans.length} steps)
            </span>
            {(traceSearchFilter.trim() !== '' || traceStatusFilter !== 'all') ? (
              <Button size='mini' type='text' className='control-quiet-icon-button' onClick={clearTraceFilters}>
                Clear
              </Button>
            ) : null}
          </div>
          <div className='grid grid-cols-1 gap-8px'>
            <Input
              allowClear
              size='small'
              placeholder='Search node, namespace, input, output'
              value={traceSearchFilter}
              onChange={setTraceSearchFilter}
            />
            <Select
              size='small'
              value={traceStatusFilter}
              options={[
                { label: 'All statuses', value: 'all' },
                { label: 'Running', value: 'running' },
                { label: 'Completed', value: 'completed' },
                { label: 'Failed', value: 'failed' },
                { label: 'Interrupted', value: 'interrupted' },
                { label: 'Observed', value: 'observed' },
              ]}
              onChange={(value) => setTraceStatusFilter(String(value) as TraceStatusFilter)}
            />
          </div>
        </div>
        <div className='min-h-0 flex-1 overflow-hidden'>
          <ScrollableViewport viewportClassName='py-4px'>
            {props.traceSpans.length === 0 ? (
              <div className='flex h-full items-center justify-center'>
                <Empty description='No trace steps found for this run' />
              </div>
            ) : filteredTraceSpans.length === 0 ? (
              <div className='flex h-full items-center justify-center'>
                <Empty description='No trace spans match the current filters' />
              </div>
            ) : (
              <div className='flex flex-col'>
                {visibleSpans.map((span) => {
                  const expandable = childrenMap.has(span.id);
                  const expanded = !collapsedSpanIds.has(span.id);
                  return (
                    <TraceTreeRow
                      key={span.id}
                      span={span}
                      active={selectedTrace?.id === span.id}
                      expandable={expandable}
                      expanded={expanded}
                      onSelect={() => setSelectedTraceId(span.id)}
                      onToggleExpand={() => toggleCollapse(span.id)}
                      indentLevel={span.depth}
                    />
                  );
                })}
              </div>
            )}
          </ScrollableViewport>
        </div>
        {/* Bottom summary bar */}
        {(hiddenCount > 0 || filteredTraceSpans.length > 0) ? (
          <div
            className='flex items-center justify-between border-t border-solid border-[var(--control-border)] px-12px py-6px text-11px text-[var(--control-subtle)]'
          >
            <span>{filteredTraceSpans.length} spans</span>
            {hiddenCount > 0 ? (
              <button
                type='button'
                className='cursor-pointer border-none bg-transparent text-11px text-[var(--control-accent)]'
                onClick={() => setCollapsedSpanIds(new Set())}
              >
                {hiddenCount} hidden — expand all
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* Right: selected span detail - 60% */}
      <div className='flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden'>
        {selectedTrace ? (
          <>
            {/* Breadcrumb-style header */}
            <div className='border-b border-solid border-[var(--control-border)] px-14px py-10px'>
              <div className='mb-6px flex items-center justify-between gap-8px'>
                <div className='flex min-w-0 flex-1 items-center gap-8px'>
                  <span
                    className='inline-block h-8px w-8px shrink-0 rd-full'
                    style={{ background: traceAccent(selectedTrace.status), boxShadow: `0 0 6px ${traceAccent(selectedTrace.status)}` }}
                  />
                  <span className='truncate text-13px font-semibold text-[var(--control-text)]'>
                    {selectedTrace.nodeName}
                  </span>
                  {traceNamespaceLabel(selectedTrace) !== 'root' ? (
                    <span className='truncate text-11px text-[var(--control-subtle)]'>
                      ({traceNamespaceLabel(selectedTrace)})
                    </span>
                  ) : null}
                  <span className='text-[var(--control-border)]'>|</span>
                  <span className='shrink-0 text-11px text-[var(--control-subtle)]'>
                    {traceDurationLabel(selectedTrace)}
                  </span>
                  <span className='shrink-0 text-11px text-[var(--control-subtle)]'>
                    started {formatCompactDateTime(selectedTrace.startedAt)}
                  </span>
                </div>
                <SegmentedTabs
                  value={traceDetailTab}
                  tabs={[
                    { value: 'input', label: 'Input' },
                    { value: 'output', label: 'Output' },
                    { value: 'attributes', label: 'Attributes' },
                  ]}
                  onChange={(value) => setTraceDetailTab(value as TraceDetailTab)}
                />
              </div>
            </div>
            <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden px-14px py-12px'>
              {traceDetailTab === 'input' ? (
                <div>
                  <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>
                    {selectedTrace.kind === 'model' && !selectedTrace.input && selectedTrace.reasoning.length > 0 ? 'reasoning' : 'input'}
                  </span>
                  {selectedTrace.kind === 'model' && !selectedTrace.input && selectedTrace.reasoning.length > 0 ? (
                    <div
                      className='chat-markdown rd-10px p-10px'
                      style={{ background: 'rgba(255,45,149,0.03)', border: '1px solid rgba(255,45,149,0.10)' }}
                    >
                      <Markdown remarkPlugins={[remarkGfm]}>
                        {selectedTrace.reasoning.join('\n\n')}
                      </Markdown>
                    </div>
                  ) : (
                    <pre
                      className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                      style={{ background: 'rgba(0,240,255,0.03)', border: '1px solid rgba(0,240,255,0.08)' }}
                    >
                      {stringifyValue(selectedTrace.input) ?? 'n/a'}
                    </pre>
                  )}
                </div>
              ) : traceDetailTab === 'output' ? (
                <div>
                  <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>output</span>
                  <pre
                    className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                    style={{ background: 'rgba(57,255,20,0.03)', border: '1px solid rgba(57,255,20,0.10)' }}
                  >
                    {resolveOutputContent(selectedTrace)}
                  </pre>
                </div>
              ) : (
                /* Attributes tab */
                <div className='flex flex-col gap-4px'>
                  {/* Tags section */}
                  <CollapsibleSection label='Tags' defaultOpen>
                    <div className='flex flex-wrap gap-6px'>
                      <Tag size='small' color='purple'>{selectedTrace.kind}</Tag>
                      <Tag size='small' color='arcoblue'>{traceStatusLabel(selectedTrace.status)}</Tag>
                      {selectedTrace.step !== undefined ? <Tag size='small' color='purple'>step {selectedTrace.step}</Tag> : null}
                      {selectedTrace.synthetic ? <Tag size='small' color='gray'>synthetic</Tag> : null}
                    </div>
                  </CollapsibleSection>

                  {/* Metadata section */}
                  <CollapsibleSection label='Metadata' defaultOpen>
                    <MetadataTable entries={[
                      { key: 'node', value: selectedTrace.nodeName },
                      { key: 'namespace', value: traceNamespaceLabel(selectedTrace) },
                      { key: 'started', value: formatCompactDateTime(selectedTrace.startedAt) || '-' },
                      { key: 'duration', value: traceDurationLabel(selectedTrace) },
                      { key: 'events', value: String(selectedTrace.eventCount) },
                      ...(selectedTrace.messages.length > 0 ? [{ key: 'messages', value: String(selectedTrace.messages.length) }] : []),
                      ...(selectedTrace.toolCalls.length > 0 ? [{ key: 'tool calls', value: selectedTrace.toolCalls.join(', ') }] : []),
                    ]} />
                  </CollapsibleSection>

                  {/* Reasoning section */}
                  {(selectedTrace.reasoning.length > 0 || selectedTrace.reasoningEncrypted) ? (
                    <CollapsibleSection label='Reasoning' defaultOpen={selectedTrace.kind === 'model'}>
                      <div
                        className='chat-markdown rd-10px p-10px'
                        style={{ background: 'rgba(255,45,149,0.03)', border: '1px solid rgba(255,45,149,0.10)' }}
                      >
                        {traceReasoningMarkdown(selectedTrace) ? (
                          <Markdown remarkPlugins={[remarkGfm]}>
                            {traceReasoningMarkdown(selectedTrace)!}
                          </Markdown>
                        ) : selectedTrace.reasoningEncrypted ? 'reasoning hidden (encrypted)' : 'n/a'}
                      </div>
                    </CollapsibleSection>
                  ) : null}

                  {/* Events section */}
                  {selectedTrace.events.length > 0 ? (
                    <CollapsibleSection label={`Events (${selectedTrace.events.length})`} defaultOpen={false}>
                      <div className='flex flex-col gap-4px'>
                        {selectedTrace.events.map((event) => (
                          <div
                            key={event.id}
                            className='flex items-center gap-8px rd-8px px-8px py-4px'
                            style={{ background: 'rgba(16,22,48,0.76)', border: '1px solid rgba(0,240,255,0.06)' }}
                          >
                            <Tag size='small' color='arcoblue'>{event.streamMode}</Tag>
                            <span className='min-w-0 flex-1 truncate text-12px text-[var(--control-text)]'>{event.eventType}</span>
                            <span className='shrink-0 text-11px text-[var(--control-subtle)]'>{formatCompactDateTime(event.timestamp)}</span>
                          </div>
                        ))}
                      </div>
                    </CollapsibleSection>
                  ) : null}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className='flex h-full items-center justify-center'>
            <Typography.Text className='text-12px text-[var(--control-subtle)]'>No step selected</Typography.Text>
          </div>
        )}
      </div>
    </div>
  );
}
