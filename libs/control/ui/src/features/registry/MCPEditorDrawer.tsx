import { useEffect, useState } from 'react';
import { Button, Drawer, Form, Input, Select } from '@arco-design/web-react';
import { PlugOne } from '@icon-park/react';
import type { MCPConfigDTO, MCPConfigUpsertRequestDTO } from '@/shared/types/api';
import {
  authoredStatusOptions,
  formatMultilineList,
  parseMultilineList,
} from '@/features/registry/formCodecs';
import KeyValueEditor from '@/shared/components/KeyValueEditor';
import '@/styles/registry-cards.css';

const ACCENT = '#ff9f1a';

type MCPEditorDrawerProps = {
  visible: boolean;
  mode: 'create' | 'edit';
  value?: MCPConfigDTO;
  onClose: () => void;
  onSubmit: (name: string, body: MCPConfigUpsertRequestDTO) => Promise<void>;
};

type MCPFormValues = {
  name: string;
  description: string;
  command: string;
  argsText: string;
  env: Record<string, string>;
  transport: string;
  status: string;
};

function SectionLabel({ title, color = ACCENT }: { title: string; color?: string }) {
  return (
    <div className='flex items-center gap-8px mt-12px mb-8px'>
      <span className='text-11px font-bold tracking-wider uppercase' style={{ color }}>
        {title}
      </span>
      <div className='flex-1 h-1px' style={{ background: `${color}18` }} />
    </div>
  );
}

export default function MCPEditorDrawer(props: MCPEditorDrawerProps) {
  const [form] = Form.useForm<MCPFormValues>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!props.visible) {
      form.resetFields();
      setSubmitting(false);
      return;
    }

    form.setFieldsValue({
      name: props.value?.name ?? '',
      description: props.value?.description ?? '',
      command: props.value?.command ?? '',
      argsText: formatMultilineList(props.value?.args),
      env: props.value?.env ?? {},
      transport: props.value?.transport ?? 'stdio',
      status: props.value?.status ?? 'draft',
    });
  }, [form, props.mode, props.value, props.visible]);

  async function handleSubmit() {
    const values = await form.validate();
    const name = values.name.trim();

    setSubmitting(true);
    try {
      await props.onSubmit(name, {
        description: values.description.trim() || undefined,
        command: values.command.trim() || undefined,
        args: parseMultilineList(values.argsText),
        env: Object.keys(values.env).length > 0 ? values.env : undefined,
        transport: values.transport.trim() || undefined,
        status: values.status || undefined,
      });
      props.onClose();
    } finally {
      setSubmitting(false);
    }
  }

  const isEdit = props.mode === 'edit';

  return (
    <Drawer
      width={780}
      title={null}
      visible={props.visible}
      unmountOnExit
      headerStyle={{ display: 'none' }}
      onCancel={props.onClose}
      footer={
        <div className='flex justify-end gap-10px'>
          <Button onClick={props.onClose}>Cancel</Button>
          <Button type='primary' loading={submitting} onClick={() => void handleSubmit()}>
            Save
          </Button>
        </div>
      }
    >
      {/* Hero header */}
      <div className='flex items-center gap-14px mb-20px pb-16px' style={{ borderBottom: `1px solid ${ACCENT}20` }}>
        <div
          className='w-40px h-40px rd-10px flex-center shrink-0'
          style={{ background: `${ACCENT}14`, border: `1px solid ${ACCENT}33` }}
        >
          <PlugOne size={22} fill={[ACCENT]} />
        </div>
        <div>
          <div className='text-16px font-700 text-[var(--control-text)]'>
            {isEdit ? `Edit / ${props.value?.name ?? ''}` : 'Create MCP'}
          </div>
          <div className='text-12px text-[var(--control-subtle)]'>
            Configure MCP server command, arguments, environment, and transport
          </div>
        </div>
        <span
          className='ml-auto rd-full px-8px py-2px text-10px font-bold tracking-wider uppercase border border-solid shrink-0'
          style={{ color: ACCENT, borderColor: `${ACCENT}40`, background: `${ACCENT}0a` }}
        >
          MCP
        </span>
      </div>

      <Form form={form} layout='vertical'>
        {/* Identity */}
        <SectionLabel title='Identity' />
        <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
          <Form.Item
            field='name'
            label='Name'
            rules={[{ required: true, message: 'name is required' }]}
          >
            <Input placeholder='github' disabled={isEdit} />
          </Form.Item>
          <Form.Item
            field='status'
            label='Status'
            rules={[{ required: true, message: 'status is required' }]}
          >
            <Select options={authoredStatusOptions as unknown as Array<{ label: string; value: string }>} />
          </Form.Item>
        </div>
        <Form.Item field='description' label='Description'>
          <Input placeholder='GitHub MCP server' />
        </Form.Item>

        {/* Server */}
        <SectionLabel title='Server' />
        <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
          <Form.Item
            field='command'
            label='Command'
            rules={[{ required: true, message: 'command is required' }]}
          >
            <Input placeholder='npx' />
          </Form.Item>
          <Form.Item field='transport' label='Transport' rules={[{ required: true, message: 'transport is required' }]}>
            <Select
              options={[
                { label: 'stdio', value: 'stdio' },
                { label: 'sse', value: 'sse' },
                { label: 'http', value: 'http' },
                { label: 'streamable_http', value: 'streamable_http' },
              ]}
            />
          </Form.Item>
        </div>
        <Form.Item field='argsText' label='Args' extra='One argument per line'>
          <Input.TextArea
            autoSize={{ minRows: 3, maxRows: 10 }}
            placeholder={'-y\n@modelcontextprotocol/server-github'}
          />
        </Form.Item>

        {/* Environment */}
        <SectionLabel title='Environment' />
        <Form.Item field='env' label='Environment Variables'>
          <KeyValueEditor keyPlaceholder='Variable' valuePlaceholder='Value' />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
