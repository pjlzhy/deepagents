import { useState } from 'react';
import { Button, Form, Input, Typography } from '@arco-design/web-react';
import type { FormInstance } from '@arco-design/web-react';
import { RobotOne } from '@icon-park/react';
import RegistryReferenceSelect from '@/features/registry/RegistryReferenceSelect';
import { controlClient } from '@/shared/api/controlClient';
import type { BuilderFormValues } from '@/features/agent-builder/builderForm';

type DelegateCardProps = {
  index: number;
  form: FormInstance<BuilderFormValues>;
  onDelete: (index: number) => void;
};

const ACCENT = '#a855f7';

export default function DelegateCard(props: DelegateCardProps) {
  const [expanded, setExpanded] = useState(true);
  const prefix = `subagents.${props.index}`;

  const name = (props.form.getFieldValue as (field: string) => unknown)(`subagents.${props.index}.name`) as string | undefined;
  const summaryText = name?.trim() || `Delegate ${props.index + 1}`;

  return (
    <div className='delegate-card control-card mb-12px'>
      {/* Header */}
      <div
        className='flex cursor-pointer items-center justify-between px-16px py-10px'
        onClick={() => setExpanded((prev) => !prev)}
      >
        <div className='delegate-card-header'>
          <div className='delegate-card-icon'>
            <RobotOne size={18} fill={[ACCENT]} />
          </div>
          <div>
            <Typography.Text className='text-13px font-medium text-[var(--control-text)]'>
              {summaryText}
            </Typography.Text>
            {name?.trim() ? (
              <div className='mt-1px'>
                <span
                  className='rd-4px border border-solid px-4px py-1px text-9px font-bold tracking-wider'
                  style={{ color: ACCENT, borderColor: ACCENT, background: 'rgba(168,85,247,0.06)' }}
                >
                  DELEGATE
                </span>
              </div>
            ) : null}
          </div>
        </div>
        <div className='flex items-center gap-8px'>
          <Button
            size='mini'
            type='text'
            status='danger'
            onClick={(e) => {
              e.stopPropagation();
              props.onDelete(props.index);
            }}
          >
            Remove
          </Button>
          <Typography.Text className='text-11px text-[var(--control-subtle)]'>
            {expanded ? '▲' : '▼'}
          </Typography.Text>
        </div>
      </div>

      {/* Collapsible body */}
      <div className={`delegate-card-body ${expanded ? 'delegate-card-body--expanded' : ''}`}>
        <div className='delegate-card-body-inner px-16px pb-16px'>
          <div className='grid grid-cols-1 gap-14px md:grid-cols-2'>
            <Form.Item
              field={`${prefix}.name`}
              label='Name'
              rules={[{ required: true, message: 'Delegate name is required' }]}
            >
              <Input placeholder='planner' />
            </Form.Item>
            <Form.Item field={`${prefix}.modelRef`} label='Model'>
              <RegistryReferenceSelect
                resourceLabel='model configs'
                placeholder='Select a model'
                allowClear
                fetchPage={(params) => controlClient.models.list(params)}
                extractItems={(page) => page.models}
              />
            </Form.Item>
          </div>
          <Form.Item field={`${prefix}.description`} label='Description'>
            <Input placeholder='Planning helper agent' />
          </Form.Item>
          <Form.Item field={`${prefix}.skillRefs`} label='Skills'>
            <RegistryReferenceSelect
              mode='multiple'
              resourceLabel='skills'
              allowClear
              placeholder='Select skills for this delegate'
              fetchPage={(params) => controlClient.skills.list(params)}
              extractItems={(page) => page.skills}
            />
          </Form.Item>
          <Form.Item field={`${prefix}.systemPrompt`} label='System Prompt'>
            <Input.TextArea
              autoSize={{ minRows: 3, maxRows: 10 }}
              placeholder='You are a specialized planning agent...'
            />
          </Form.Item>
        </div>
      </div>
    </div>
  );
}
