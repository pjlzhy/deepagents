import { Form, Input, Select } from '@arco-design/web-react';
import { authoredStatusOptions } from '@/features/registry/formCodecs';
import RegistryReferenceSelect from '@/features/registry/RegistryReferenceSelect';
import { controlClient } from '@/shared/api/controlClient';

export default function AgentFormFields(props: { disableName?: boolean }) {
  return (
    <>
      <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
        <Form.Item
          field='name'
          label='Name'
          rules={[{ required: true, message: 'name is required' }]}
        >
          <Input disabled={props.disableName} placeholder='assistant-prod' />
        </Form.Item>
        <Form.Item
          field='status'
          label='Status'
          rules={[{ required: true, message: 'status is required' }]}
        >
          <Select options={authoredStatusOptions as unknown as Array<{ label: string; value: string }>} />
        </Form.Item>
      </div>
      <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
        <Form.Item field='version' label='Version'>
          <Input placeholder='v1' />
        </Form.Item>
        <Form.Item
          field='modelRef'
          label='Model Ref'
          rules={[{ required: true, message: 'model_ref is required' }]}
        >
          <RegistryReferenceSelect
            resourceLabel='model configs'
            placeholder='Select a model config'
            allowClear
            fetchPage={(params) => controlClient.models.list(params)}
            extractItems={(page) => page.models}
          />
        </Form.Item>
      </div>
      <Form.Item field='description' label='Description'>
        <Input placeholder='Runtime assistant for customer support' />
      </Form.Item>
      <Form.Item field='tagsText' label='Tags'>
        <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder={'support\nproduction'} />
      </Form.Item>
      <Form.Item field='promptSystem' label='System Prompt'>
        <Input.TextArea autoSize={{ minRows: 8, maxRows: 18 }} placeholder='You are a helpful assistant...' />
      </Form.Item>
      <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
        <Form.Item field='skillRefs' label='Skill Refs'>
          <RegistryReferenceSelect
            mode='multiple'
            resourceLabel='skills'
            allowClear
            placeholder='Select skills'
            fetchPage={(params) => controlClient.skills.list(params)}
            extractItems={(page) => page.skills}
          />
        </Form.Item>
        <Form.Item field='mcpRefs' label='MCP Refs'>
          <RegistryReferenceSelect
            mode='multiple'
            resourceLabel='MCP configs'
            allowClear
            placeholder='Select MCP configs'
            fetchPage={(params) => controlClient.mcps.list(params)}
            extractItems={(page) => page.mcps}
          />
        </Form.Item>
      </div>
      <Form.Item field='interruptOnText' label='Interrupt On'>
        <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder={'approval_required\nhuman_review'} />
      </Form.Item>
      <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
        <Form.Item field='sandboxImage' label='Sandbox Image'>
          <Input placeholder='python:3.12-slim' />
        </Form.Item>
        <Form.Item field='sandboxInitText' label='Sandbox Init'>
          <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder={'pip install -r requirements.txt'} />
        </Form.Item>
      </div>
      <Form.Item field='sandboxResourcesJson' label='Sandbox Resources JSON'>
        <Input.TextArea
          autoSize={{ minRows: 6, maxRows: 12 }}
          placeholder={'{\n  "cpu": "1",\n  "memory": "2Gi"\n}'}
        />
      </Form.Item>
      <Form.Item field='subagentsJson' label='Subagents JSON'>
        <Input.TextArea
          autoSize={{ minRows: 8, maxRows: 18 }}
          placeholder={
            '[\n  {\n    "name": "planner",\n    "description": "Planning helper",\n    "system_prompt": "Plan carefully",\n    "model": {\n      "provider": "openai",\n      "model": "gpt-4.1-mini"\n    }\n  }\n]'
          }
        />
      </Form.Item>
    </>
  );
}
