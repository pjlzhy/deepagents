import { Typography } from '@arco-design/web-react';
import type { FormInstance } from '@arco-design/web-react';
import { Peoples } from '@icon-park/react';
import DelegateList from '@/features/agent-builder/delegation/DelegateList';
import type { BuilderFormValues } from '@/features/agent-builder/builderForm';

type DelegationStepProps = {
  form: FormInstance<BuilderFormValues>;
  isEdit: boolean;
};

const ACCENT = '#a855f7';
const TINT = 'rgba(168,85,247,0.06)';

export default function DelegationStep(props: DelegationStepProps) {
  return (
    <div className='mx-auto max-w-800px'>
      <div className='builder-step-header'>
        <div
          className='builder-step-header-icon'
          style={{ background: TINT, '--step-glow': 'rgba(168,85,247,0.2)' } as React.CSSProperties}
        >
          <Peoples size={24} fill={[ACCENT]} />
        </div>
        <div>
          <Typography.Title heading={5} className='!mb-0 !mt-0 text-[var(--control-text)]'>
            Delegation
          </Typography.Title>
          <Typography.Text className='text-13px text-[var(--control-subtle)]'>
            Configure subordinate agents that this agent can delegate tasks to.
          </Typography.Text>
        </div>
        <span
          className='builder-step-header-chip ml-auto'
          style={{ color: ACCENT, borderColor: ACCENT, background: TINT }}
        >
          DELEGATION
        </span>
      </div>

      <DelegateList form={props.form} />
    </div>
  );
}
