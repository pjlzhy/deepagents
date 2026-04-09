import { Button, Empty, Spin, Tag, Typography } from '@arco-design/web-react';
import {
  CYAN,
  formatCompactDateTime,
  telemetryStatusFromRun,
  formatTelemetryStatus,
  truncate,
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

export default function RunList(props: RunListProps) {
  return (
    <div className='flex h-full min-h-0 flex-col overflow-hidden'>
      <div className='flex items-center justify-between border-b border-solid border-[var(--control-border)] px-14px py-10px'>
        <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>run history</span>
        <Typography.Text className='text-12px text-[var(--control-subtle)]'>
          {props.runs.length} runs
        </Typography.Text>
      </div>

      <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden px-10px py-10px'>
        {props.loading ? (
          <div className='flex h-full items-center justify-center'>
            <Spin />
          </div>
        ) : props.runs.length === 0 && !props.liveRunId ? (
          <div className='flex h-full items-center justify-center'>
            <Empty description='No runs found for this conversation' />
          </div>
        ) : (
          <div className='flex flex-col gap-8px'>
            {/* Live run indicator */}
            {props.liveRunId ? (
              <button
                type='button'
                className='cursor-pointer border-none rd-12px px-12px py-10px text-left transition-all duration-200'
                style={{
                  background: props.selectedRunId === props.liveRunId ? `${CYAN}14` : 'rgba(16,22,48,0.76)',
                  border: `1px solid ${props.selectedRunId === props.liveRunId ? `${CYAN}55` : 'rgba(0,240,255,0.08)'}`,
                  boxShadow: props.selectedRunId === props.liveRunId ? `0 0 12px ${CYAN}20` : 'none',
                }}
                onClick={() => props.onSelectRun(props.liveRunId!)}
              >
                <div className='flex items-center gap-8px'>
                  <span
                    className='inline-block h-8px w-8px shrink-0 rd-full'
                    style={{
                      background: CYAN,
                      boxShadow: `0 0 8px ${CYAN}`,
                      animation: 'pulse 2s ease-in-out infinite',
                    }}
                  />
                  <span className='text-12px font-semibold text-[var(--control-text)]'>Live Run</span>
                  <Tag size='small' color='arcoblue'>streaming</Tag>
                </div>
                <div className='mt-6px text-12px text-[var(--control-subtle)]'>
                  {truncate(props.liveRunId, 40)}
                </div>
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

              return (
                <button
                  key={runId}
                  type='button'
                  className='cursor-pointer border-none rd-12px px-12px py-10px text-left transition-all duration-200'
                  style={{
                    background: active ? `${statusView.color}14` : 'rgba(16,22,48,0.76)',
                    border: `1px solid ${active ? `${statusView.color}55` : 'rgba(0,240,255,0.08)'}`,
                    boxShadow: active ? `0 0 12px ${statusView.color}20` : 'none',
                  }}
                  onClick={() => props.onSelectRun(runId)}
                >
                  <div className='flex items-center gap-8px'>
                    <span
                      className='inline-block h-8px w-8px shrink-0 rd-full'
                      style={{ background: statusView.color }}
                    />
                    <span className='text-12px font-semibold text-[var(--control-text)]'>
                      {formatCompactDateTime(run.started_at)}
                    </span>
                    <Tag size='small' color='arcoblue'>{statusView.text}</Tag>
                    <span className='ml-auto text-11px text-[var(--control-subtle)]'>
                      {runDurationLabel(run)}
                    </span>
                  </div>
                  {run.reasoning_summary ? (
                    <div className='mt-6px text-12px leading-18px text-[var(--control-subtle)]'>
                      {truncate(run.reasoning_summary, 120)}
                    </div>
                  ) : null}
                  <div className='mt-8px flex flex-wrap gap-6px'>
                    {run.node_step_count ? <Tag size='small' color='purple'>nodes {run.node_step_count}</Tag> : null}
                    {run.model_step_count ? <Tag size='small' color='arcoblue'>model {run.model_step_count}</Tag> : null}
                    {run.tool_step_count ? <Tag size='small' color='orange'>tools {run.tool_step_count}</Tag> : null}
                  </div>
                  {/* Snapshot button - placeholder for future fork/replay */}
                  {props.onViewSnapshot ? (
                    <div className='mt-8px flex justify-end'>
                      <Button
                        size='mini'
                        type='text'
                        className='control-quiet-icon-button'
                        onClick={(e) => {
                          e.stopPropagation();
                          props.onViewSnapshot!(runId, label);
                        }}
                      >
                        View Snapshot
                      </Button>
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
