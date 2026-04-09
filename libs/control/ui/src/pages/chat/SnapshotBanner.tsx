import { RobotOne } from '@icon-park/react';
import { Button, Typography } from '@arco-design/web-react';
import { CYAN } from '@/shared/utils/telemetryHelpers';

export default function SnapshotBanner(props: {
  runLabel: string;
  onBackToLatest: () => void;
}) {
  return (
    <div
      className='flex shrink-0 items-center justify-between gap-12px px-16px py-10px'
      style={{
        background: 'rgba(0,240,255,0.04)',
        borderBottom: '1px solid rgba(0,240,255,0.12)',
      }}
    >
      <div className='flex items-center gap-10px'>
        <RobotOne size={14} fill={[CYAN]} />
        <Typography.Text className='text-13px text-[var(--control-text)]'>
          Viewing snapshot of <span className='font-semibold'>{props.runLabel}</span>
        </Typography.Text>
      </div>
      <Button
        size='small'
        type='primary'
        onClick={props.onBackToLatest}
      >
        Back to latest
      </Button>
    </div>
  );
}
