import { useEffect, useState } from 'react';
import { Button, Drawer, Form, Input, Select, Space } from '@arco-design/web-react';
import type { SkillDTO, SkillUpsertRequestDTO } from '@/shared/types/api';
import {
  authoredStatusOptions,
  formatJsonValue,
  formatMultilineList,
  parseMultilineList,
  parseOptionalSkillFiles,
} from '@/features/registry/formCodecs';

type SkillEditorDrawerProps = {
  visible: boolean;
  mode: 'create' | 'edit';
  value?: SkillDTO;
  onClose: () => void;
  onSubmit: (name: string, body: SkillUpsertRequestDTO) => Promise<void>;
};

type SkillFormValues = {
  name: string;
  description: string;
  status: string;
  tagsText: string;
  content: string;
  filesJson: string;
};

export default function SkillEditorDrawer(props: SkillEditorDrawerProps) {
  const [form] = Form.useForm<SkillFormValues>();
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
      status: props.value?.status ?? 'draft',
      tagsText: formatMultilineList(props.value?.tags),
      content: props.value?.content ?? '',
      filesJson: formatJsonValue(props.value?.files),
    });
  }, [form, props.mode, props.value, props.visible]);

  async function handleSubmit() {
    const values = await form.validate();
    const name = values.name.trim();

    setSubmitting(true);
    try {
      await props.onSubmit(name, {
        description: values.description.trim() || undefined,
        tags: parseMultilineList(values.tagsText),
        content: values.content,
        files: parseOptionalSkillFiles(values.filesJson),
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
      title={props.mode === 'create' ? 'Create Skill' : `Edit Skill / ${props.value?.name ?? ''}`}
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
            <Input placeholder='code-review' disabled={props.mode === 'edit'} />
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
          <Input placeholder='Code review workflow skill' />
        </Form.Item>
        <Form.Item field='tagsText' label='Tags'>
          <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder={'review\nquality\naudit'} />
        </Form.Item>
        <Form.Item field='content' label='SKILL.md Content'>
          <Input.TextArea autoSize={{ minRows: 8, maxRows: 18 }} placeholder='Primary SKILL.md content' />
        </Form.Item>
        <Form.Item field='filesJson' label='Extra Files JSON'>
          <Input.TextArea
            autoSize={{ minRows: 8, maxRows: 18 }}
            placeholder={'[\n  {\n    "path": "scripts/init.py",\n    "content": "print(\\"hello\\")"\n  }\n]'}
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
