import { Form, Typography } from '@arco-design/web-react';
import type { FormInstance } from '@arco-design/web-react';
import { Lightning } from '@icon-park/react';
import ResourceCardGrid from '@/features/agent-builder/pickers/ResourceCardGrid';
import { controlClient } from '@/shared/api/controlClient';
import type { BuilderFormValues } from '@/features/agent-builder/builderForm';

type CapabilitiesStepProps = {
  form: FormInstance<BuilderFormValues>;
  isEdit: boolean;
};

const ACCENT = '#39ff14';
const TINT = 'rgba(57,255,20,0.06)';

export default function CapabilitiesStep(props: CapabilitiesStepProps) {
  return (
    <div className='mx-auto max-w-900px'>
      <div className='builder-step-header'>
        <div
          className='builder-step-header-icon'
          style={{ background: TINT, '--step-glow': 'rgba(57,255,20,0.2)' } as React.CSSProperties}
        >
          <Lightning size={24} fill={[ACCENT]} />
        </div>
        <div>
          <Typography.Title heading={5} className='!mb-0 !mt-0 text-[var(--control-text)]'>
            Capabilities
          </Typography.Title>
          <Typography.Text className='text-13px text-[var(--control-subtle)]'>
            Equip this agent with skills and MCP tool servers.
          </Typography.Text>
        </div>
        <span
          className='builder-step-header-chip ml-auto'
          style={{ color: ACCENT, borderColor: ACCENT, background: TINT }}
        >
          CAPABILITIES
        </span>
      </div>

      <div className='mb-28px'>
        <Typography.Text className='mb-10px block text-14px font-medium text-[var(--control-text)]'>
          Skills
        </Typography.Text>
        <Form.Item field='skillRefs' noStyle>
          <ResourceCardGrid
            label='skills'
            accent='#39ff14'
            iconKey='Lightning'
            fetchPage={(params) => controlClient.skills.list(params)}
            extractItems={(page) => page.skills}
          />
        </Form.Item>
      </div>

      <div>
        <Typography.Text className='mb-10px block text-14px font-medium text-[var(--control-text)]'>
          MCP Servers
        </Typography.Text>
        <Form.Item field='mcpRefs' noStyle>
          <ResourceCardGrid
            label='MCP configs'
            accent='#ff9f1a'
            iconKey='PlugOne'
            fetchPage={(params) => controlClient.mcps.list(params)}
            extractItems={(page) => page.mcps}
          />
        </Form.Item>
      </div>
    </div>
  );
}
