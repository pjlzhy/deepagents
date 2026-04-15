import { useMemo } from 'react';
import useSWR from 'swr';
import { controlClient } from '@/shared/api/controlClient';
import type { TelemetryEventVM } from '@/features/telemetry/eventModel';
import {
  normalizeTelemetryEvent,
} from '@/shared/utils/telemetryHelpers';
import EventsPanel from './EventsPanel';

type RunDetailProps = {
  runId: string;
  agentName: string;
  isLive: boolean;
  liveEvents?: TelemetryEventVM[];
};

export default function RunDetail(props: RunDetailProps) {
  const eventsQuery = useSWR(
    props.isLive ? null : ['chat-run-events', props.runId],
    () => controlClient.runs.listTelemetryEvents(props.runId, { pageSize: 1000, pageNumber: 1 }),
    { revalidateOnFocus: false },
  );

  const events: TelemetryEventVM[] = useMemo(() => {
    if (props.isLive && props.liveEvents) return props.liveEvents;
    const raw = eventsQuery.data?.events ?? [];
    return raw.map((event, index) => normalizeTelemetryEvent(event, `history-event-${index}`));
  }, [props.isLive, props.liveEvents, eventsQuery.data?.events]);

  return (
    <div className='flex h-full min-h-0 flex-col overflow-hidden'>
      <div className='flex items-center justify-between border-b border-solid border-[var(--control-border)] px-14px py-10px'>
        <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>
          {props.isLive ? 'live events' : 'run events'}
        </span>
      </div>
      <div className='min-h-0 flex-1 overflow-hidden'>
        <EventsPanel events={events} />
      </div>
    </div>
  );
}
