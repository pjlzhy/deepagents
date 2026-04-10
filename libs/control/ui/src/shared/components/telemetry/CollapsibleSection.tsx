import { useState } from 'react';

type CollapsibleSectionProps = {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
};

export default function CollapsibleSection(props: CollapsibleSectionProps) {
  const [open, setOpen] = useState(props.defaultOpen ?? true);

  return (
    <div className='mb-8px'>
      <button
        type='button'
        className='flex w-full cursor-pointer items-center gap-6px border-none bg-transparent px-0 py-6px text-left'
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className='text-11px text-[var(--control-subtle)]'>
          {open ? '▾' : '▸'}
        </span>
        <span className='text-11px font-semibold uppercase tracking-widest text-[var(--control-subtle)]'>
          {props.label}
        </span>
      </button>
      {open ? (
        <div className='pl-4px'>
          {props.children}
        </div>
      ) : null}
    </div>
  );
}
