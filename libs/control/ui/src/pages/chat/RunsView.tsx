import { useState, useEffect } from 'react';
import useSWR from 'swr';
import { controlClient } from '@/shared/api/controlClient';
import type { TelemetryEventVM } from '@/features/telemetry/traceModel';
import RunList from './RunList';
import RunDetail from './RunDetail';

type RunsViewProps = {
  agentName: string;
  threadId: string;
  liveRunId?: string;
  liveEvents?: TelemetryEventVM[];
  selectedRunId?: string;
  onSelectRun: (runId: string) => void;
  onViewSnapshot?: (runId: string, runLabel: string) => void;
};

export default function RunsView(props: RunsViewProps) {
  const [detailRunId, setDetailRunId] = useState<string | undefined>(props.selectedRunId);

  const runsQuery = useSWR(
    ['chat-telemetry-runs', props.agentName, props.threadId],
    () => controlClient.runs.listTelemetryRuns({
      agentName: props.agentName,
      threadId: props.threadId,
      pageSize: 50,
      pageNumber: 1,
    }),
    { revalidateOnFocus: true },
  );

  const runs = runsQuery.data?.runs ?? [];
  const effectiveRunId = detailRunId ?? props.selectedRunId;

  // Auto-select first run when data loads and nothing is selected
  useEffect(() => {
    if (effectiveRunId) return;
    const firstId = props.liveRunId ?? runs[0]?.run_id;
    if (firstId) {
      setDetailRunId(firstId);
      props.onSelectRun(firstId);
    }
  }, [runs, props.liveRunId, effectiveRunId]);

  function handleSelectRun(runId: string) {
    setDetailRunId(runId);
    props.onSelectRun(runId);
  }

  return (
    <div className='flex h-full min-h-0 overflow-hidden'>
      {/* Left: Run list */}
      <div
        className='flex min-h-0 flex-col overflow-hidden'
        style={{ width: '320px', borderRight: '1px solid var(--control-border)' }}
      >
        <RunList
          runs={runs}
          loading={runsQuery.isLoading}
          liveRunId={props.liveRunId}
          selectedRunId={effectiveRunId}
          onSelectRun={handleSelectRun}
          onViewSnapshot={props.onViewSnapshot}
        />
      </div>

      {/* Right: Run detail */}
      <div className='flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden'>
        {effectiveRunId ? (
          <RunDetail
            runId={effectiveRunId}
            agentName={props.agentName}
            isLive={effectiveRunId === props.liveRunId}
            liveEvents={effectiveRunId === props.liveRunId ? props.liveEvents : undefined}
          />
        ) : (
          <div className='flex h-full items-center justify-center'>
            <span className='text-13px text-[var(--control-subtle)]'>
              Select a run to view details
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
