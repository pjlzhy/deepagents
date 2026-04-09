import { useState, useMemo, useDeferredValue } from 'react';
import { Button, Empty, Input, Select, Tag, Typography } from '@arco-design/web-react';
import type { TelemetryEventVM } from '@/features/telemetry/traceModel';
import {
  eventAccent,
  formatCompactDateTime,
  groupLabel,
  namespaceLabel,
  stringifyValue,
  summarizeEvent,
  type DebugDetailTab,
  type TelemetryGroupMode,
} from '@/shared/utils/telemetryHelpers';
import SegmentedTabs from '@/shared/components/telemetry/SegmentedTabs';
import ScrollableViewport from '@/shared/components/telemetry/ScrollableViewport';

type EventsPanelProps = {
  events: TelemetryEventVM[];
};

export default function EventsPanel(props: EventsPanelProps) {
  const [searchFilter, setSearchFilter] = useState('');
  const [selectedModes, setSelectedModes] = useState<string[]>([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([]);
  const [namespaceFilter, setNamespaceFilter] = useState('');
  const [groupBy, setGroupBy] = useState<TelemetryGroupMode>('namespace');
  const [selectedEventId, setSelectedEventId] = useState<string | undefined>(undefined);
  const [debugDetailTab, setDebugDetailTab] = useState<DebugDetailTab>('payload');

  const deferredSearchFilter = useDeferredValue(searchFilter);
  const deferredNamespaceFilter = useDeferredValue(namespaceFilter);

  const modeOptions = useMemo(
    () => Array.from(new Set(props.events.map((e) => e.streamMode))).sort().map((mode) => ({ label: mode, value: mode })),
    [props.events],
  );
  const eventTypeOptions = useMemo(
    () => Array.from(new Set(props.events.map((e) => e.eventType))).sort().map((et) => ({ label: et, value: et })),
    [props.events],
  );

  const filteredEvents = useMemo(() => {
    const namespaceNeedle = deferredNamespaceFilter.trim().toLowerCase();
    const searchNeedle = deferredSearchFilter.trim().toLowerCase();
    return props.events.filter((event) => {
      if (selectedModes.length > 0 && !selectedModes.includes(event.streamMode)) return false;
      if (selectedEventTypes.length > 0 && !selectedEventTypes.includes(event.eventType)) return false;
      const namespaceText = namespaceLabel(event).toLowerCase();
      if (namespaceNeedle && !namespaceText.includes(namespaceNeedle)) return false;
      if (!searchNeedle) return true;
      const haystacks = [
        event.eventType,
        event.streamMode,
        namespaceLabel(event),
        summarizeEvent(event),
        stringifyValue(event.metadata) ?? '',
        stringifyValue(event.payload) ?? '',
        stringifyValue(event.publicEvent) ?? '',
      ];
      return haystacks.some((value) => value.toLowerCase().includes(searchNeedle));
    });
  }, [deferredNamespaceFilter, deferredSearchFilter, props.events, selectedEventTypes, selectedModes]);

  const groupedEvents = useMemo(() => {
    if (groupBy === 'flat') return [{ key: 'all-events', label: 'all events', events: filteredEvents }];
    const groups = new Map<string, TelemetryEventVM[]>();
    for (const event of filteredEvents) {
      const key = groupLabel(event, groupBy);
      const items = groups.get(key);
      if (items) items.push(event);
      else groups.set(key, [event]);
    }
    return Array.from(groups.entries()).map(([key, items]) => ({ key, label: key, events: items }));
  }, [filteredEvents, groupBy]);

  const selectedEvent = useMemo(
    () => filteredEvents.find((e) => e.id === selectedEventId) ?? filteredEvents.at(-1),
    [filteredEvents, selectedEventId],
  );

  const hasActiveFilters = selectedModes.length > 0 || selectedEventTypes.length > 0 || deferredNamespaceFilter.trim() !== '' || deferredSearchFilter.trim() !== '';

  function clearFilters() {
    setSelectedModes([]);
    setSelectedEventTypes([]);
    setNamespaceFilter('');
    setSearchFilter('');
    setGroupBy('namespace');
  }

  return (
    <div className='flex h-full min-h-0 overflow-hidden'>
      {/* Left: event list */}
      <div className='flex min-h-0 flex-col overflow-hidden' style={{ width: '50%', borderRight: '1px solid var(--control-border)' }}>
        <div className='border-b border-solid border-[var(--control-border)] px-12px py-10px'>
          <div className='mb-8px flex items-center justify-between gap-8px'>
            <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>
              events ({filteredEvents.length})
            </span>
            {hasActiveFilters ? (
              <Button size='mini' type='text' className='control-quiet-icon-button' onClick={clearFilters}>Clear</Button>
            ) : null}
          </div>
          <div className='grid grid-cols-1 gap-8px'>
            <Input allowClear size='small' placeholder='Search event, payload, metadata' value={searchFilter} onChange={setSearchFilter} />
            <div className='grid grid-cols-2 gap-8px'>
              <Select
                mode='multiple'
                allowClear
                size='small'
                placeholder='Stream modes'
                options={modeOptions}
                value={selectedModes}
                onChange={(value) => setSelectedModes(Array.isArray(value) ? value.map(String) : [])}
              />
              <Select
                size='small'
                placeholder='Group by'
                value={groupBy}
                options={[
                  { label: 'Namespace', value: 'namespace' },
                  { label: 'Stream mode', value: 'stream_mode' },
                  { label: 'Event type', value: 'event_type' },
                  { label: 'Flat list', value: 'flat' },
                ]}
                onChange={(value) => setGroupBy(String(value) as TelemetryGroupMode)}
              />
            </div>
          </div>
        </div>
        <div className='min-h-0 flex-1 overflow-hidden'>
          <ScrollableViewport viewportClassName='px-10px py-10px'>
            {props.events.length === 0 ? (
              <div className='flex h-full items-center justify-center'>
                <Empty description='No events found for this run' />
              </div>
            ) : filteredEvents.length === 0 ? (
              <div className='flex h-full items-center justify-center'>
                <Empty description='No events match the current filters' />
              </div>
            ) : (
              <div className='flex flex-col gap-12px'>
                {groupedEvents.map((group) => (
                  <div key={group.key} className='flex flex-col gap-8px'>
                    {groupBy !== 'flat' ? (
                      <div
                        className='sticky top-0 z-1 flex items-center justify-between rd-10px px-10px py-8px'
                        style={{ background: 'rgba(12,16,36,0.98)', border: '1px solid rgba(0,240,255,0.08)' }}
                      >
                        <span className='text-11px font-semibold uppercase tracking-widest text-[var(--control-subtle)]'>
                          {group.label}
                        </span>
                        <Tag size='small' color='arcoblue'>{group.events.length}</Tag>
                      </div>
                    ) : null}
                    {group.events.map((event) => {
                      const active = selectedEvent?.id === event.id;
                      const accent = eventAccent(event);
                      return (
                        <button
                          key={event.id}
                          type='button'
                          className='cursor-pointer border-none rd-12px px-12px py-10px text-left transition-all duration-200'
                          style={{
                            background: active ? `${accent}14` : 'rgba(16,22,48,0.76)',
                            border: `1px solid ${active ? `${accent}55` : 'rgba(0,240,255,0.08)'}`,
                            boxShadow: active ? `0 0 12px ${accent}20` : 'none',
                          }}
                          onClick={() => setSelectedEventId(event.id)}
                        >
                          <div className='flex items-center gap-8px'>
                            <span
                              className='inline-block h-8px w-8px shrink-0 rd-full'
                              style={{ background: accent, boxShadow: `0 0 8px ${accent}` }}
                            />
                            <span className='text-12px font-semibold text-[var(--control-text)]'>{event.eventType}</span>
                            <Tag size='small' color='arcoblue'>{event.streamMode}</Tag>
                            <span className='ml-auto text-11px text-[var(--control-subtle)]'>
                              {formatCompactDateTime(event.timestamp)}
                            </span>
                          </div>
                          <div className='mt-6px text-11px uppercase tracking-wider text-[var(--control-subtle)]'>
                            {namespaceLabel(event)}
                          </div>
                          <div className='mt-6px text-12px leading-18px text-[var(--control-subtle)]'>
                            {summarizeEvent(event)}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </ScrollableViewport>
        </div>
      </div>

      {/* Right: selected event detail */}
      <div className='flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden'>
        {selectedEvent ? (
          <>
            <div className='border-b border-solid border-[var(--control-border)] px-14px py-10px'>
              <div className='mb-6px flex items-center justify-between gap-8px'>
                <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>event details</span>
                <SegmentedTabs
                  value={debugDetailTab}
                  tabs={[
                    { value: 'payload', label: 'Payload' },
                    { value: 'metadata', label: 'Metadata' },
                    { value: 'public_event', label: 'Public' },
                  ]}
                  onChange={(value) => setDebugDetailTab(value as DebugDetailTab)}
                />
              </div>
              <div className='grid grid-cols-2 gap-x-10px gap-y-6px text-12px'>
                <span className='text-[var(--control-subtle)]'>type</span>
                <span className='truncate text-right'>{selectedEvent.eventType}</span>
                <span className='text-[var(--control-subtle)]'>time</span>
                <span className='truncate text-right'>{formatCompactDateTime(selectedEvent.timestamp)}</span>
                <span className='text-[var(--control-subtle)]'>namespace</span>
                <span className='truncate text-right'>{namespaceLabel(selectedEvent)}</span>
              </div>
            </div>
            <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden px-14px py-12px'>
              {debugDetailTab === 'payload' ? (
                <pre
                  className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                  style={{ background: 'rgba(255,45,149,0.03)', border: '1px solid rgba(255,45,149,0.10)' }}
                >
                  {stringifyValue(selectedEvent.payload) ?? 'n/a'}
                </pre>
              ) : debugDetailTab === 'metadata' ? (
                <pre
                  className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                  style={{ background: 'rgba(0,240,255,0.03)', border: '1px solid rgba(0,240,255,0.08)' }}
                >
                  {stringifyValue(selectedEvent.metadata) ?? 'n/a'}
                </pre>
              ) : (
                <pre
                  className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                  style={{ background: 'rgba(57,255,20,0.03)', border: '1px solid rgba(57,255,20,0.10)' }}
                >
                  {stringifyValue(selectedEvent.publicEvent) ?? 'n/a'}
                </pre>
              )}
            </div>
          </>
        ) : (
          <div className='flex h-full items-center justify-center'>
            <Typography.Text className='text-12px text-[var(--control-subtle)]'>No event selected</Typography.Text>
          </div>
        )}
      </div>
    </div>
  );
}
