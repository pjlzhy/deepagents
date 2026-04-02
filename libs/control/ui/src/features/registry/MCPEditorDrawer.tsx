import { useEffect, useState } from 'react';
import { Button, Drawer, Form, Input, Select, Space } from '@arco-design/web-react';
import type { MCPConfigDTO, MCPConfigUpsertRequestDTO } from '@/shared/types/api';
import {
  authoredStatusOptions,
  formatMultilineList,
  parseMultilineList,
} from '@/features/registry/formCodecs';
import KeyValueEditor from '@/shared/components/KeyValueEditor';

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

  return (
    <Drawer
      width={760}
      title={props.mode === 'create' ? 'Create MCP' : `Edit MCP / ${props.value?.name ?? ''}`}
      visible={props.visible}
      unmountOnExit
      onCancel={props.onClose}
      footer={
        <Space>
          <Button onClick={props.onClose}>Cancel</Button>
          <Button type='primary' loading={submitting} onClick={() => void handleSubmit()}>
            Save
          </Button>
        </Space>
      }
    >
      <Form form={form} layout='vertical'>
        <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
          <Form.Item
            field='name'
            label='Name'
            rules={[{ required: true, message: 'name is required' }]}
          >
            <Input placeholder='github' disabled={props.mode === 'edit'} />
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
        <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
          <Form.Item
            field='command'
            label='Command'
            rules={[{ required: true, message: 'command is required' }]}
          >
            <Input placeholder='npx' />
          </Form.Item>
          <Form.Item field='transport' label='Transport'>
            <Input placeholder='stdio' />
          </Form.Item>
        </div>
        <Form.Item field='argsText' label='Args'>
          <Input.TextArea autoSize={{ minRows: 4, maxRows: 10 }} placeholder={'-y\n@mcp/server-github'} />
        </Form.Item>
        <Form.Item field='env' label='Environment Variables'>
          <KeyValueEditor keyPlaceholder='Variable' valuePlaceholder='Value' />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
