import { formatTelemetryStatus, type TelemetryStatus } from '@/shared/utils/telemetryHelpers';

export default function StatusPill(props: { status: TelemetryStatus }) {
  const view = formatTelemetryStatus(props.status);
  return (
    <span
      className='rd-full px-8px py-2px text-11px font-bold uppercase tracking-wider border border-solid'
      style={{ color: view.color, borderColor: `${view.color}40`, background: `${view.color}10` }}
    >
      {view.text}
    </span>
  );
}
