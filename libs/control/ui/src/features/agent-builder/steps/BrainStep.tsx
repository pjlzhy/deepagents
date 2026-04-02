import { Form, Input, Typography } from '@arco-design/web-react';
import type { FormInstance } from '@arco-design/web-react';
import { Brain } from '@icon-park/react';
import ModelCardPicker from '@/features/agent-builder/pickers/ModelCardPicker';
import type { BuilderFormValues } from '@/features/agent-builder/builderForm';

type BrainStepProps = {
  form: FormInstance<BuilderFormValues>;
  isEdit: boolean;
};

const ACCENT = '#00f0ff';
const TINT = 'rgba(0,240,255,0.06)';

export default function BrainStep(props: BrainStepProps) {
  return (
    <div className='mx-auto max-w-800px'>
      <div className='builder-step-header'>
        <div
          className='builder-step-header-icon'
          style={{ background: TINT, '--step-glow': 'rgba(0,240,255,0.2)' } as React.CSSProperties}
        >
          <Brain size={24} fill={[ACCENT]} />
        </div>
        <div>
          <Typography.Title heading={5} className='!mb-0 !mt-0 text-[var(--control-text)]'>
            Brain
          </Typography.Title>
          <Typography.Text className='text-13px text-[var(--control-subtle)]'>
            Select the model that powers this agent and define its core personality via system prompt.
          </Typography.Text>
        </div>
        <span
          className='builder-step-header-chip ml-auto'
          style={{ color: ACCENT, borderColor: ACCENT, background: TINT }}
        >
          BRAIN
        </span>
      </div>

      <Form.Item
        field='modelRef'
        label='Model'
        rules={[{ required: true, message: 'A model is required' }]}
      >
        <ModelCardPicker />
      </Form.Item>

      <Form.Item field='promptSystem' label='System Prompt'>
        <Input.TextArea
          autoSize={{ minRows: 8, maxRows: 24 }}
          placeholder='You are a helpful assistant...'
        />
      </Form.Item>
    </div>
  );
}
