import { Form, Input, Select, Typography } from '@arco-design/web-react';
import type { FormInstance } from '@arco-design/web-react';
import { Fingerprint } from '@icon-park/react';
import { authoredStatusOptions } from '@/features/registry/formCodecs';
import type { BuilderFormValues } from '@/features/agent-builder/builderForm';

type IdentityStepProps = {
  form: FormInstance<BuilderFormValues>;
  isEdit: boolean;
};

const ACCENT = '#00f0ff';
const TINT = 'rgba(0,240,255,0.06)';

export default function IdentityStep(props: IdentityStepProps) {
  return (
    <div className='mx-auto max-w-700px'>
      <div className='builder-step-header'>
        <div
          className='builder-step-header-icon'
          style={{ background: TINT, '--step-glow': 'rgba(0,240,255,0.2)' } as React.CSSProperties}
        >
          <Fingerprint size={24} fill={[ACCENT]} />
        </div>
        <div>
          <Typography.Title heading={5} className='!mb-0 !mt-0 text-[var(--control-text)]'>
            Identity
          </Typography.Title>
          <Typography.Text className='text-13px text-[var(--control-subtle)]'>
            Define who this agent is — its name, version, and how it presents itself.
          </Typography.Text>
        </div>
        <span
          className='builder-step-header-chip ml-auto'
          style={{ color: ACCENT, borderColor: ACCENT, background: TINT }}
        >
          IDENTITY
        </span>
      </div>

      <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
        <Form.Item
          field='name'
          label='Name'
          rules={[{ required: true, message: 'Agent name is required' }]}
        >
          <Input disabled={props.isEdit} placeholder='assistant-prod' />
        </Form.Item>
        <Form.Item
          field='status'
          label='Status'
          rules={[{ required: true, message: 'Status is required' }]}
        >
          <Select options={authoredStatusOptions as unknown as Array<{ label: string; value: string }>} />
        </Form.Item>
      </div>

      <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
        <Form.Item field='version' label='Version'>
          <Input placeholder='v1' />
        </Form.Item>
        <Form.Item field='description' label='Description'>
          <Input placeholder='Runtime assistant for customer support' />
        </Form.Item>
      </div>

      <Form.Item field='tags' label='Tags'>
        <Select
          mode='multiple'
          allowCreate
          allowClear
          placeholder='Type a tag and press Enter'
        />
      </Form.Item>
    </div>
  );
}
