import type { TraceSpanVM } from '@/features/telemetry/traceModel';
import { traceAccent, traceDurationLabel, traceKindIcon } from '@/shared/utils/telemetryHelpers';

type TraceTreeRowProps = {
  span: TraceSpanVM;
  active: boolean;
  expandable: boolean;
  expanded: boolean;
  onSelect: () => void;
  onToggleExpand?: () => void;
  indentLevel: number;
};

export default function TraceTreeRow(props: TraceTreeRowProps) {
  const accent = traceAccent(props.span.status);

  return (
    <button
      type='button'
      className='flex w-full cursor-pointer items-center border-none bg-transparent px-8px text-left transition-colors duration-150'
      style={{
        height: '32px',
        paddingLeft: `${props.indentLevel * 20 + 8}px`,
        background: props.active ? `${accent}0a` : 'transparent',
        borderLeft: props.active ? `2px solid ${accent}` : '2px solid transparent',
      }}
      onClick={props.onSelect}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = props.active ? `${accent}0a` : 'rgba(0,240,255,0.04)'; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = props.active ? `${accent}0a` : 'transparent'; }}
    >
      {/* Expand/collapse arrow */}
      <span
        className='inline-flex w-16px shrink-0 items-center justify-center text-11px text-[var(--control-subtle)]'
        style={{ cursor: props.expandable ? 'pointer' : 'default' }}
        onClick={(e) => {
          if (props.expandable && props.onToggleExpand) {
            e.stopPropagation();
            props.onToggleExpand();
          }
        }}
      >
        {props.expandable ? (props.expanded ? '▾' : '▸') : ''}
      </span>

      {/* Status dot */}
      <span
        className='mx-6px inline-block h-8px w-8px shrink-0 rd-full'
        style={{ background: accent, boxShadow: `0 0 6px ${accent}` }}
      />

      {/* Kind icon */}
      <span className='mr-6px shrink-0 text-10px font-bold uppercase text-[var(--control-subtle)]' style={{ width: '14px', textAlign: 'center' }}>
        {traceKindIcon(props.span.kind)}
      </span>

      {/* Node name */}
      <span className='min-w-0 flex-1 truncate text-12px font-medium text-[var(--control-text)]'>
        {props.span.nodeName}
      </span>

      {/* Duration */}
      <span className='ml-8px shrink-0 text-11px text-[var(--control-subtle)]'>
        {traceDurationLabel(props.span)}
      </span>
    </button>
  );
}
