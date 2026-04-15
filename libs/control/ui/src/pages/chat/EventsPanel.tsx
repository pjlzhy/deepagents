import { useState, useMemo, useDeferredValue } from 'react';
import { Button, Empty, Input, Select, Tag, Typography } from '@arco-design/web-react';
import type { TelemetryEventVM } from '@/features/telemetry/eventModel';
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
import CollapsibleSection from '@/shared/components/telemetry/CollapsibleSection';

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
          <ScrollableViewport viewportClassName='py-4px'>
            {props.events.length === 0 ? (
              <div className='flex h-full items-center justify-center'>
                <Empty description='No events found for this run' />
              </div>
            ) : filteredEvents.length === 0 ? (
              <div className='flex h-full items-center justify-center'>
                <Empty description='No events match the current filters' />
              </div>
            ) : (
              <div className='flex flex-col gap-4px'>
                {groupedEvents.map((group) => (
                  <div key={group.key} className='flex flex-col'>
                    {groupBy !== 'flat' ? (
                      <div
                        className='sticky top-0 z-1 flex items-center justify-between px-12px py-6px'
                        style={{ background: 'rgba(12,16,36,0.98)', borderBottom: '1px solid rgba(0,240,255,0.06)' }}
                      >
                        <span className='text-10px font-semibold uppercase tracking-widest text-[var(--control-subtle)]'>
                          {group.label}
                        </span>
                        <span className='text-10px text-[var(--control-subtle)]'>{group.events.length}</span>
                      </div>
                    ) : null}
                    {group.events.map((event) => {
                      const active = selectedEvent?.id === event.id;
                      const accent = eventAccent(event);
                      return (
                        <button
                          key={event.id}
                          type='button'
                          className='flex w-full cursor-pointer items-center gap-8px border-none bg-transparent px-12px text-left transition-colors duration-150'
                          style={{
                            height: '32px',
                            background: active ? `${accent}0a` : 'transparent',
                            borderLeft: active ? `2px solid ${accent}` : '2px solid transparent',
                          }}
                          onClick={() => setSelectedEventId(event.id)}
                          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = active ? `${accent}0a` : 'rgba(0,240,255,0.04)'; }}
                          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = active ? `${accent}0a` : 'transparent'; }}
                        >
                          {/* Accent dot */}
                          <span
                            className='inline-block h-6px w-6px shrink-0 rd-full'
                            style={{ background: accent, boxShadow: `0 0 4px ${accent}` }}
                          />
                          {/* Event type */}
                          <span className='shrink-0 text-12px font-medium text-[var(--control-text)]'>
                            {event.eventType}
                          </span>
                          {/* Stream mode badge */}
                          <span
                            className='shrink-0 rd-4px px-4px py-1px text-10px'
                            style={{ background: `${accent}18`, color: accent }}
                          >
                            {event.streamMode}
                          </span>
                          {/* Namespace */}
                          <span className='min-w-0 flex-1 truncate text-11px text-[var(--control-subtle)]'>
                            {namespaceLabel(event)}
                          </span>
                          {/* Timestamp */}
                          <span className='shrink-0 text-10px text-[var(--control-subtle)]'>
                            {formatCompactDateTime(event.timestamp)}
                          </span>
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
            {/* Breadcrumb-style header */}
            <div className='border-b border-solid border-[var(--control-border)] px-14px py-10px'>
              <div className='mb-6px flex items-center justify-between gap-8px'>
                <div className='flex min-w-0 flex-1 items-center gap-8px'>
                  <span
                    className='inline-block h-8px w-8px shrink-0 rd-full'
                    style={{ background: eventAccent(selectedEvent), boxShadow: `0 0 6px ${eventAccent(selectedEvent)}` }}
                  />
                  <span className='truncate text-13px font-semibold text-[var(--control-text)]'>
                    {selectedEvent.eventType}
                  </span>
                  <span
                    className='shrink-0 rd-4px px-4px py-1px text-10px'
                    style={{ background: `${eventAccent(selectedEvent)}18`, color: eventAccent(selectedEvent) }}
                  >
                    {selectedEvent.streamMode}
                  </span>
                  <span className='text-[var(--control-border)]'>|</span>
                  <span className='truncate text-11px text-[var(--control-subtle)]'>
                    {namespaceLabel(selectedEvent)}
                  </span>
                  <span className='shrink-0 text-11px text-[var(--control-subtle)]'>
                    {formatCompactDateTime(selectedEvent.timestamp)}
                  </span>
                </div>
                <SegmentedTabs
                  value={debugDetailTab}
                  tabs={[
                    { value: 'payload', label: 'Payload' },
                    { value: 'metadata', label: 'Metadata' },
                  ]}
                  onChange={(value) => setDebugDetailTab(value as DebugDetailTab)}
                />
              </div>
            </div>
            <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden px-14px py-12px'>
              {debugDetailTab === 'payload' ? (
                <PayloadView label='payload' value={selectedEvent.payload} color='rgba(255,45,149' />
              ) : (
                <PayloadView label='metadata' value={selectedEvent.metadata} color='rgba(0,240,255' />
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

/** Collapsible JSON payload view */
function PayloadView(props: { label: string; value: unknown; color: string }) {
  const text = stringifyValue(props.value) ?? 'n/a';
  const isLarge = text.length > 2000;

  return (
    <CollapsibleSection label={props.label} defaultOpen>
      <pre
        className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
        style={{
          background: `${props.color},0.03)`,
          border: `1px solid ${props.color},0.10)`,
          maxHeight: isLarge ? '400px' : undefined,
        }}
      >
        {text}
      </pre>
    </CollapsibleSection>
  );
}
