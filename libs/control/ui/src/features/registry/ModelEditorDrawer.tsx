import { useEffect, useState } from 'react';
import { Button, Drawer, Form, Input, Select } from '@arco-design/web-react';
import { Brain } from '@icon-park/react';
import type { ModelConfigDTO, ModelConfigUpsertRequestDTO } from '@/shared/types/api';
import { authoredStatusOptions } from '@/features/registry/formCodecs';
import KeyValueEditor from '@/shared/components/KeyValueEditor';
import '@/styles/registry-cards.css';

const CYAN = '#00f0ff';

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
  apiKey: string;
  apiKeyEnv: string;
  status: string;
  extraParams: Record<string, string>;
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
      apiKey: '',
      apiKeyEnv: props.value?.api_key_env ?? '',
      status: props.value?.status ?? 'draft',
      extraParams: props.value?.extra_params ?? {},
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
        api_key: values.apiKey.trim() || undefined,
        api_key_env: values.apiKeyEnv.trim() || undefined,
        extra_params: Object.keys(values.extraParams).length > 0 ? values.extraParams : undefined,
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
          <Button
            type='primary'
            loading={submitting}
            onClick={() => void handleSubmit()}
          >
            Save
          </Button>
        </div>
      }
    >
      {/* Hero header */}
      <div className='flex items-center gap-14px mb-20px pb-16px' style={{ borderBottom: '1px solid rgba(0,240,255,0.12)' }}>
        <div
          className='w-40px h-40px rd-10px flex-center shrink-0'
          style={{ background: 'rgba(0,240,255,0.08)', border: '1px solid rgba(0,240,255,0.20)' }}
        >
          <Brain size={22} fill={[CYAN]} />
        </div>
        <div>
          <div className='text-16px font-700 text-[var(--control-text)]'>
            {isEdit ? `Edit / ${props.value?.name ?? ''}` : 'Create Model'}
          </div>
          <div className='text-12px text-[var(--control-subtle)]'>
            Configure model provider, credentials, and parameters
          </div>
        </div>
        <span
          className='ml-auto rd-full px-8px py-2px text-10px font-bold tracking-wider uppercase border border-solid shrink-0'
          style={{ color: CYAN, borderColor: `${CYAN}40`, background: `${CYAN}0a` }}
        >
          MODEL
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
            <Input placeholder='gpt-4o-prod' disabled={isEdit} />
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

        {/* Provider */}
        <SectionLabel title='Provider' />
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
        <Form.Item field='baseUrl' label='Base URL'>
          <Input placeholder='https://api.openai.com/v1' />
        </Form.Item>

        {/* Credentials */}
        <SectionLabel title='Credentials' />
        <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
          <Form.Item
            field='apiKey'
            label='API Key'
            extra={
              isEdit && props.value?.api_key
                ? `Current: ${props.value.api_key}`
                : 'Direct API key (encrypted at rest)'
            }
          >
            <Input.Password
              placeholder={isEdit ? 'Leave empty to keep current' : 'sk-...'}
              autoComplete='off'
            />
          </Form.Item>
          <Form.Item field='apiKeyEnv' label='API Key Env'>
            <Input placeholder='OPENAI_API_KEY' />
          </Form.Item>
        </div>

        {/* Extra */}
        <SectionLabel title='Extra Params' />
        <Form.Item field='extraParams'>
          <KeyValueEditor keyPlaceholder='Param' valuePlaceholder='Value' />
        </Form.Item>
      </Form>
    </Drawer>
  );
}

function SectionLabel({ title }: { title: string }) {
  return (
    <div className='flex items-center gap-8px mt-12px mb-8px'>
      <span
        className='text-11px font-bold tracking-wider uppercase'
        style={{ color: CYAN }}
      >
        {title}
      </span>
      <div className='flex-1 h-1px' style={{ background: 'rgba(0,240,255,0.08)' }} />
    </div>
  );
}
