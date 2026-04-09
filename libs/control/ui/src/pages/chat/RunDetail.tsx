import { useState, useMemo } from 'react';
import useSWR from 'swr';
import { controlClient } from '@/shared/api/controlClient';
import { buildTraceSpansFromSteps, type TelemetryEventVM } from '@/features/telemetry/traceModel';
import {
  normalizeTelemetryEvent,
  type TelemetryViewMode,
} from '@/shared/utils/telemetryHelpers';
import SegmentedTabs from '@/shared/components/telemetry/SegmentedTabs';
import TracePanel from './TracePanel';
import GraphPanel from './GraphPanel';
import EventsPanel from './EventsPanel';

type RunDetailProps = {
  runId: string;
  agentName: string;
  isLive: boolean;
  liveEvents?: TelemetryEventVM[];
};

export default function RunDetail(props: RunDetailProps) {
  const [viewMode, setViewMode] = useState<TelemetryViewMode>('trace');

  const traceStepsQuery = useSWR(
    ['chat-run-steps', props.runId],
    () => controlClient.runs.listTelemetrySteps(props.runId),
    {
      revalidateOnFocus: false,
      refreshInterval: props.isLive ? 2000 : 0,
    },
  );

  const eventsQuery = useSWR(
    props.isLive ? null : ['chat-run-events', props.runId],
    () => controlClient.runs.listTelemetryEvents(props.runId, { pageSize: 1000, pageNumber: 1 }),
    { revalidateOnFocus: false },
  );

  const graphQuery = useSWR(
    ['chat-run-graph', props.agentName],
    () => controlClient.agents.getGraph(props.agentName, 2),
  );

  const events: TelemetryEventVM[] = useMemo(() => {
    if (props.isLive && props.liveEvents) return props.liveEvents;
    const raw = eventsQuery.data?.events ?? [];
    return raw.map((event, index) => normalizeTelemetryEvent(event, `history-event-${index}`));
  }, [props.isLive, props.liveEvents, eventsQuery.data?.events]);

  const traceSpans = useMemo(
    () => buildTraceSpansFromSteps(traceStepsQuery.data?.steps ?? [], events),
    [events, traceStepsQuery.data?.steps],
  );

  return (
    <div className='flex h-full min-h-0 flex-col overflow-hidden'>
      {/* Header with view mode tabs */}
      <div className='flex items-center justify-between border-b border-solid border-[var(--control-border)] px-14px py-10px'>
        <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>
          {props.isLive ? 'live run' : 'run detail'}
        </span>
        <SegmentedTabs
          value={viewMode}
          tabs={[
            { value: 'trace', label: 'Trace' },
            { value: 'graph', label: 'Graph' },
            { value: 'debug', label: 'Events' },
          ]}
          onChange={(value) => setViewMode(value as TelemetryViewMode)}
        />
      </div>

      {/* Content area */}
      <div className='min-h-0 flex-1 overflow-hidden'>
        {viewMode === 'trace' ? (
          <TracePanel
            traceSpans={traceSpans}
            events={events}
          />
        ) : viewMode === 'graph' ? (
          <GraphPanel
            graphData={graphQuery.data}
            traceSpans={traceSpans}
            loading={graphQuery.isLoading}
            agentName={props.agentName}
          />
        ) : (
          <EventsPanel
            events={events}
          />
        )}
      </div>
    </div>
  );
}
