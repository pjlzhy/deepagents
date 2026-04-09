import { Button } from '@arco-design/web-react';

export default function SegmentedTabs(props: {
  value: string;
  tabs: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className='flex items-center gap-4px rd-full px-4px py-4px'
      style={{ border: '1px solid var(--control-border)', background: 'rgba(16,22,48,0.76)' }}
    >
      {props.tabs.map((tab) => (
        <Button
          key={tab.value}
          size='small'
          type={props.value === tab.value ? 'primary' : 'text'}
          className={props.value === tab.value ? '' : 'control-quiet-icon-button'}
          disabled={props.disabled}
          onClick={() => props.onChange(tab.value)}
        >
          {tab.label}
        </Button>
      ))}
    </div>
  );
}
