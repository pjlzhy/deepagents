import { Typography } from '@arco-design/web-react';
import { fieldToStep, BUILDER_STEPS } from '@/features/agent-builder/builderForm';

type DiagnosticError = {
  field: string;
  message: string;
};

type BuilderDiagnosticsProps = {
  open: boolean;
  errors: DiagnosticError[];
  onGoFix: (step: number) => void;
};

export default function BuilderDiagnostics(props: BuilderDiagnosticsProps) {
  if (props.errors.length === 0) return null;

  const grouped = new Map<number, DiagnosticError[]>();
  for (const err of props.errors) {
    const step = fieldToStep(err.field);
    const list = grouped.get(step) ?? [];
    list.push(err);
    grouped.set(step, list);
  }

  return (
    <div className={`builder-diagnostics ${props.open ? 'builder-diagnostics--open' : ''}`}>
      {Array.from(grouped.entries()).map(([stepIndex, errs]) => (
        <div key={stepIndex} className='mb-8px'>
          <Typography.Text className='mb-4px block text-12px font-medium text-[var(--control-text)]'>
            {BUILDER_STEPS[stepIndex]?.label ?? 'Unknown'}
          </Typography.Text>
          {errs.map((err, i) => (
            <div key={i} className='builder-diagnostics-item'>
              <span>{err.field}: {err.message}</span>
              <span
                className='builder-diagnostics-fix'
                onClick={() => props.onGoFix(stepIndex)}
              >
                Go fix
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
