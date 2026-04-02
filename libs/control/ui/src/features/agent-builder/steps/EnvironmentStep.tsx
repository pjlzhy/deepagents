import { Form, Select, Typography } from '@arco-design/web-react';
import type { FormInstance } from '@arco-design/web-react';
import { Server } from '@icon-park/react';
import RegistryReferenceSelect from '@/features/registry/RegistryReferenceSelect';
import { controlClient } from '@/shared/api/controlClient';
import type { BuilderFormValues } from '@/features/agent-builder/builderForm';

type EnvironmentStepProps = {
  form: FormInstance<BuilderFormValues>;
  isEdit: boolean;
};

const ACCENT = '#ff2d95';
const TINT = 'rgba(255,45,149,0.06)';

export default function EnvironmentStep(props: EnvironmentStepProps) {
  return (
    <div className='mx-auto max-w-700px'>
      <div className='builder-step-header'>
        <div
          className='builder-step-header-icon'
          style={{ background: TINT, '--step-glow': 'rgba(255,45,149,0.2)' } as React.CSSProperties}
        >
          <Server size={24} fill={[ACCENT]} />
        </div>
        <div>
          <Typography.Title heading={5} className='!mb-0 !mt-0 text-[var(--control-text)]'>
            Environment
          </Typography.Title>
          <Typography.Text className='text-13px text-[var(--control-subtle)]'>
            Choose the sandbox where this agent executes and configure interrupt triggers.
          </Typography.Text>
        </div>
        <span
          className='builder-step-header-chip ml-auto'
          style={{ color: ACCENT, borderColor: ACCENT, background: TINT }}
        >
          ENVIRONMENT
        </span>
      </div>

      <Form.Item field='sandboxRef' label='Sandbox'>
        <RegistryReferenceSelect
          resourceLabel='sandbox configs'
          allowClear
          placeholder='Select a sandbox config'
          fetchPage={(params) => controlClient.sandboxes.list(params)}
          extractItems={(page) => page.sandboxes}
        />
      </Form.Item>

      <Form.Item field='interruptOn' label='Interrupt On'>
        <Select
          mode='multiple'
          allowCreate
          allowClear
          placeholder='Type an interrupt trigger and press Enter'
        />
      </Form.Item>
    </div>
  );
}
