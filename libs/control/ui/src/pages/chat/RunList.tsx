import { Empty, Spin } from '@arco-design/web-react';
import {
  CYAN,
  formatCompactDateTime,
  telemetryStatusFromRun,
  formatTelemetryStatus,
} from '@/shared/utils/telemetryHelpers';
import type { HTTPTelemetryRunDTO } from '@/shared/types/api';

type RunListProps = {
  runs: HTTPTelemetryRunDTO[];
  loading: boolean;
  liveRunId?: string;
  selectedRunId?: string;
  onSelectRun: (runId: string) => void;
  onViewSnapshot?: (runId: string, runLabel: string) => void;
};

function runDurationLabel(run: HTTPTelemetryRunDTO): string {
  if (!run.started_at || !run.finished_at) return '-';
  const start = new Date(run.started_at).getTime();
  const end = new Date(run.finished_at).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return '-';
  const ms = end - start;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function compactCounts(run: HTTPTelemetryRunDTO): string {
  const parts: string[] = [];
  if (run.node_step_count) parts.push(`${run.node_step_count}N`);
  if (run.model_step_count) parts.push(`${run.model_step_count}M`);
  if (run.tool_step_count) parts.push(`${run.tool_step_count}T`);
  if (run.hitl_wait_count) parts.push(`${run.hitl_wait_count}H`);
  return parts.join(' · ');
}

export default function RunList(props: RunListProps) {
  return (
    <div className='flex h-full min-h-0 flex-col overflow-hidden'>
      <div className='flex items-center justify-between border-b border-solid border-[var(--control-border)] px-12px py-8px'>
        <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>run history</span>
        <span className='text-11px text-[var(--control-subtle)]'>{props.runs.length} runs</span>
      </div>

      <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden py-4px'>
        {props.loading ? (
          <div className='flex h-full items-center justify-center'>
            <Spin />
          </div>
        ) : props.runs.length === 0 && !props.liveRunId ? (
          <div className='flex h-full items-center justify-center'>
            <Empty description='No runs found' />
          </div>
        ) : (
          <div className='flex flex-col'>
            {/* Live run */}
            {props.liveRunId ? (
              <button
                type='button'
                className='flex w-full cursor-pointer items-center gap-6px border-none bg-transparent px-10px py-6px text-left transition-colors duration-150'
                style={{
                  background: props.selectedRunId === props.liveRunId ? `${CYAN}0a` : 'transparent',
                  borderLeft: props.selectedRunId === props.liveRunId ? `2px solid ${CYAN}` : '2px solid transparent',
                }}
                onClick={() => props.onSelectRun(props.liveRunId!)}
                onMouseEnter={(e) => { if (props.selectedRunId !== props.liveRunId) (e.currentTarget as HTMLElement).style.background = 'rgba(0,240,255,0.04)'; }}
                onMouseLeave={(e) => { if (props.selectedRunId !== props.liveRunId) (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
              >
                <span
                  className='inline-block h-7px w-7px shrink-0 rd-full'
                  style={{ background: CYAN, boxShadow: `0 0 6px ${CYAN}`, animation: 'pulse 2s ease-in-out infinite' }}
                />
                <span className='text-12px font-medium text-[var(--control-text)]'>Live Run</span>
                <span className='rd-4px px-4px py-1px text-10px' style={{ background: `${CYAN}18`, color: CYAN }}>
                  streaming
                </span>
              </button>
            ) : null}

            {/* Historical runs */}
            {props.runs.map((run) => {
              const runId = run.run_id ?? '';
              if (runId === props.liveRunId) return null;
              const active = props.selectedRunId === runId;
              const telemetryStatus = telemetryStatusFromRun(run.status);
              const statusView = formatTelemetryStatus(telemetryStatus);
              const label = `Run ${formatCompactDateTime(run.started_at)}`;
              const counts = compactCounts(run);

              return (
                <button
                  key={runId}
                  type='button'
                  className='group flex w-full cursor-pointer flex-col border-none bg-transparent px-10px py-5px text-left transition-colors duration-150'
                  style={{
                    background: active ? `${statusView.color}0a` : 'transparent',
                    borderLeft: active ? `2px solid ${statusView.color}` : '2px solid transparent',
                  }}
                  onClick={() => props.onSelectRun(runId)}
                  onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLElement).style.background = 'rgba(0,240,255,0.04)'; }}
                  onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                >
                  {/* Line 1: dot + time + status badge + duration */}
                  <div className='flex items-center gap-6px'>
                    <span
                      className='inline-block h-7px w-7px shrink-0 rd-full'
                      style={{ background: statusView.color }}
                    />
                    <span className='text-12px font-medium text-[var(--control-text)]'>
                      {formatCompactDateTime(run.started_at)}
                    </span>
                    <span
                      className='shrink-0 rd-4px px-4px py-1px text-10px'
                      style={{ background: `${statusView.color}18`, color: statusView.color }}
                    >
                      {statusView.text}
                    </span>
                    <span className='ml-auto shrink-0 text-11px text-[var(--control-subtle)]'>
                      {runDurationLabel(run)}
                    </span>
                  </div>
                  {/* Line 2: compact counts + snapshot link */}
                  {(counts || (active && props.onViewSnapshot)) ? (
                    <div className='mt-2px flex items-center gap-6px pl-13px'>
                      {counts ? (
                        <span className='text-10px text-[var(--control-subtle)]'>{counts}</span>
                      ) : null}
                      {active && props.onViewSnapshot ? (
                        <span
                          role='button'
                          tabIndex={0}
                          className='ml-auto cursor-pointer text-10px text-[var(--control-accent)] opacity-80 hover:opacity-100'
                          onClick={(e) => { e.stopPropagation(); props.onViewSnapshot!(runId, label); }}
                          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); props.onViewSnapshot!(runId, label); } }}
                        >
                          Snapshot
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
