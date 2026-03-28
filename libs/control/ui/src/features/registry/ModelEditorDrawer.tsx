import { useEffect, useState } from 'react';
import { Button, Drawer, Form, Input, Select, Space } from '@arco-design/web-react';
import type { ModelConfigDTO, ModelConfigUpsertRequestDTO } from '@/shared/types/api';
import { authoredStatusOptions, formatJsonValue, parseOptionalStringMap } from '@/features/registry/formCodecs';

type ModelEditorDrawerProps = {
  visible: boolean;
  mode: 'create' | 'edit';
  value?: ModelConfigDTO;
  onClose: () => void;
  onSubmit: (name: string, body: ModelConfigUpsertRequestDTO) => Promise<void>;
};

type ModelFormValues = {
  name: string;
  description: string;
  provider: string;
  model: string;
  baseUrl: string;
  apiKeyEnv: string;
  status: string;
  extraParamsJson: string;
};

export default function ModelEditorDrawer(props: ModelEditorDrawerProps) {
  const [form] = Form.useForm<ModelFormValues>();
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
      provider: props.value?.provider ?? '',
      model: props.value?.model ?? '',
      baseUrl: props.value?.base_url ?? '',
      apiKeyEnv: props.value?.api_key_env ?? '',
      status: props.value?.status ?? 'draft',
      extraParamsJson: formatJsonValue(props.value?.extra_params),
    });
  }, [form, props.mode, props.value, props.visible]);

  async function handleSubmit() {
    const values = await form.validate();
    const name = values.name.trim();

    setSubmitting(true);
    try {
      await props.onSubmit(name, {
        description: values.description.trim() || undefined,
        provider: values.provider.trim() || undefined,
        model: values.model.trim() || undefined,
        base_url: values.baseUrl.trim() || undefined,
        api_key_env: values.apiKeyEnv.trim() || undefined,
        extra_params: parseOptionalStringMap(values.extraParamsJson, 'extra_params'),
        status: values.status || undefined,
      });
      props.onClose();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Drawer
      width={720}
      title={props.mode === 'create' ? 'Create Model' : `Edit Model / ${props.value?.name ?? ''}`}
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
            <Input placeholder='gpt-4o-prod' disabled={props.mode === 'edit'} />
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
          <Input placeholder='Production OpenAI model config' />
        </Form.Item>
        <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
          <Form.Item
            field='provider'
            label='Provider'
            rules={[{ required: true, message: 'provider is required' }]}
          >
            <Input placeholder='openai' />
          </Form.Item>
          <Form.Item
            field='model'
            label='Model'
            rules={[{ required: true, message: 'model is required' }]}
          >
            <Input placeholder='gpt-4.1' />
          </Form.Item>
        </div>
        <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
          <Form.Item field='baseUrl' label='Base URL'>
            <Input placeholder='https://api.openai.com/v1' />
          </Form.Item>
          <Form.Item field='apiKeyEnv' label='API Key Env'>
            <Input placeholder='OPENAI_API_KEY' />
          </Form.Item>
        </div>
        <Form.Item field='extraParamsJson' label='Extra Params JSON'>
          <Input.TextArea
            autoSize={{ minRows: 6, maxRows: 12 }}
            placeholder='{\n  "reasoning_effort": "medium"\n}'
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
