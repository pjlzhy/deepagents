import { useState, useMemo, useDeferredValue } from 'react';
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

type TracePanelProps = {
  traceSpans: TraceSpanVM[];
  events: TelemetryEventVM[];
};

export default function TracePanel(props: TracePanelProps) {
  const [traceSearchFilter, setTraceSearchFilter] = useState('');
  const [traceStatusFilter, setTraceStatusFilter] = useState<TraceStatusFilter>('all');
  const [selectedTraceId, setSelectedTraceId] = useState<string | undefined>(undefined);
  const [traceDetailTab, setTraceDetailTab] = useState<TraceDetailTab>('io');
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

  const selectedTrace = useMemo(
    () => filteredTraceSpans.find((span) => span.id === selectedTraceId) ?? filteredTraceSpans.at(0),
    [filteredTraceSpans, selectedTraceId],
  );

  function clearTraceFilters() {
    setTraceSearchFilter('');
    setTraceStatusFilter('all');
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
          <ScrollableViewport viewportClassName='px-10px py-10px'>
            {props.traceSpans.length === 0 ? (
              <div className='flex h-full items-center justify-center'>
                <Empty description='No trace steps found for this run' />
              </div>
            ) : filteredTraceSpans.length === 0 ? (
              <div className='flex h-full items-center justify-center'>
                <Empty description='No trace spans match the current filters' />
              </div>
            ) : (
              <div className='flex flex-col gap-8px'>
                {filteredTraceSpans.map((span) => {
                  const active = selectedTrace?.id === span.id;
                  const accent = traceAccent(span.status);
                  return (
                    <button
                      key={span.id}
                      type='button'
                      className='cursor-pointer border-none rd-12px px-12px py-10px text-left transition-all duration-200'
                      style={{
                        marginLeft: `${span.depth * 14}px`,
                        background: active ? `${accent}14` : 'rgba(16,22,48,0.76)',
                        border: `1px solid ${active ? `${accent}55` : 'rgba(0,240,255,0.08)'}`,
                        boxShadow: active ? `0 0 12px ${accent}20` : 'none',
                      }}
                      onClick={() => setSelectedTraceId(span.id)}
                    >
                      {/* Row 1: status dot + node name (truncated) */}
                      <div className='flex items-center gap-8px'>
                        <span
                          className='inline-block h-8px w-8px shrink-0 rd-full'
                          style={{ background: accent, boxShadow: `0 0 8px ${accent}` }}
                        />
                        <span className='truncate text-12px font-semibold text-[var(--control-text)]'>{span.nodeName}</span>
                      </div>
                      {/* Row 2: kind + status + step tags + duration */}
                      <div className='mt-6px flex flex-wrap items-center gap-6px'>
                        <Tag size='small' color='purple'>{span.kind}</Tag>
                        <Tag size='small' color='arcoblue'>{traceStatusLabel(span.status)}</Tag>
                        {span.step !== undefined ? <Tag size='small' color='purple'>step {span.step}</Tag> : null}
                        <span className='ml-auto text-11px text-[var(--control-subtle)]'>
                          {traceDurationLabel(span)}
                        </span>
                      </div>
                      {/* Row 3: namespace (hidden if "root") */}
                      {traceNamespaceLabel(span) !== 'root' ? (
                        <div className='mt-6px text-11px uppercase tracking-wider text-[var(--control-subtle)]'>
                          {traceNamespaceLabel(span)}
                        </div>
                      ) : null}
                      <div className='mt-6px text-12px leading-18px text-[var(--control-subtle)]'>
                        {traceSummary(span)}
                      </div>
                      <div className='mt-8px flex flex-wrap gap-6px'>
                        <Tag size='small' color='green'>events {span.eventCount}</Tag>
                        {span.messages.length > 0 ? <Tag size='small' color='arcoblue'>messages {span.messages.length}</Tag> : null}
                        {span.reasoning.length > 0 ? <Tag size='small' color='magenta'>reasoning {span.reasoning.length}</Tag> : null}
                        {span.reasoningEncrypted && span.reasoning.length === 0 ? <Tag size='small' color='magenta'>reasoning hidden</Tag> : null}
                        {span.toolCalls.length > 0 ? <Tag size='small' color='purple'>tool calls {span.toolCalls.length}</Tag> : null}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </ScrollableViewport>
        </div>
      </div>

      {/* Right: selected span detail - 60% */}
      <div className='flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden'>
        {selectedTrace ? (
          <>
            <div className='border-b border-solid border-[var(--control-border)] px-14px py-10px'>
              <div className='mb-6px flex items-center justify-between gap-8px'>
                <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>step details</span>
                <SegmentedTabs
                  value={traceDetailTab}
                  tabs={[
                    { value: 'io', label: 'I/O' },
                    { value: 'reasoning', label: 'Reasoning' },
                    { value: 'events', label: 'Events' },
                  ]}
                  onChange={(value) => setTraceDetailTab(value as TraceDetailTab)}
                />
              </div>
              <div className='grid grid-cols-2 gap-x-10px gap-y-6px text-12px'>
                <span className='text-[var(--control-subtle)]'>node</span>
                <span className='truncate text-right'>{selectedTrace.nodeName}</span>
                <span className='text-[var(--control-subtle)]'>namespace</span>
                <span className='truncate text-right'>{traceNamespaceLabel(selectedTrace)}</span>
                <span className='text-[var(--control-subtle)]'>started</span>
                <span className='truncate text-right'>{formatCompactDateTime(selectedTrace.startedAt)}</span>
                <span className='text-[var(--control-subtle)]'>duration</span>
                <span className='truncate text-right'>{traceDurationLabel(selectedTrace)}</span>
              </div>
            </div>
            <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden px-14px py-12px'>
              {traceDetailTab === 'io' ? (
                <div className='flex flex-col gap-12px'>
                  <div>
                    <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>input</span>
                    <pre
                      className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                      style={{ background: 'rgba(0,240,255,0.03)', border: '1px solid rgba(0,240,255,0.08)' }}
                    >
                      {stringifyValue(selectedTrace.input) ?? 'n/a'}
                    </pre>
                  </div>
                  <div>
                    <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>output</span>
                    <pre
                      className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                      style={{ background: 'rgba(57,255,20,0.03)', border: '1px solid rgba(57,255,20,0.10)' }}
                    >
                      {stringifyValue(selectedTrace.output ?? selectedTrace.messages.at(-1)) ?? 'n/a'}
                    </pre>
                  </div>
                  <div>
                    <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>state updates</span>
                    <pre
                      className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                      style={{ background: 'rgba(255,159,26,0.03)', border: '1px solid rgba(255,159,26,0.12)' }}
                    >
                      {selectedTrace.updates.length > 0 ? stringifyValue(selectedTrace.updates) : 'n/a'}
                    </pre>
                  </div>
                </div>
              ) : traceDetailTab === 'reasoning' ? (
                <div>
                  <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>reasoning</span>
                  <div
                    className='chat-markdown rd-10px p-10px'
                    style={{ background: 'rgba(255,45,149,0.03)', border: '1px solid rgba(255,45,149,0.10)' }}
                  >
                    {traceReasoningMarkdown(selectedTrace) ? (
                      <Markdown remarkPlugins={[remarkGfm]}>
                        {traceReasoningMarkdown(selectedTrace)!}
                      </Markdown>
                    ) : 'n/a'}
                  </div>
                </div>
              ) : (
                <div>
                  <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>raw events</span>
                  <div className='flex flex-col gap-6px'>
                    {selectedTrace.events.map((event) => (
                      <div
                        key={event.id}
                        className='rd-10px px-10px py-8px'
                        style={{ background: 'rgba(16,22,48,0.76)', border: '1px solid rgba(0,240,255,0.08)' }}
                      >
                        <div className='flex items-center gap-8px'>
                          <Tag size='small' color='arcoblue'>{event.streamMode}</Tag>
                          <span className='text-12px text-[var(--control-text)]'>{event.eventType}</span>
                          <span className='ml-auto text-11px text-[var(--control-subtle)]'>{formatCompactDateTime(event.timestamp)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
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
