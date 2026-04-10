type MetadataTableProps = {
  entries: Array<{ key: string; value: string }>;
};

export default function MetadataTable(props: MetadataTableProps) {
  if (props.entries.length === 0) {
    return <span className='text-11px text-[var(--control-subtle)]'>n/a</span>;
  }

  return (
    <div
      className='rd-8px px-10px py-6px'
      style={{ background: 'rgba(0,240,255,0.02)', border: '1px solid rgba(0,240,255,0.06)' }}
    >
      {props.entries.map((entry) => (
        <div key={entry.key} className='flex items-baseline gap-8px py-3px text-12px'>
          <span className='shrink-0 text-[var(--control-subtle)]'>{entry.key}</span>
          <span className='min-w-0 flex-1 truncate text-right text-[var(--control-text)]'>{entry.value}</span>
        </div>
      ))}
    </div>
  );
}
