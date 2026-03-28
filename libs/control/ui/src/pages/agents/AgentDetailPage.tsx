import { useEffect, useState } from 'react';
import { Button, Card, Form, Input, Message, Select, Space, Spin, Typography } from '@arco-design/web-react';
import useSWR from 'swr';
import { useNavigate, useParams } from 'react-router-dom';
import { links } from '@/app/links';
import {
  authoredStatusOptions,
  formatJsonValue,
  formatMultilineList,
  parseMultilineList,
  parseOptionalStringMap,
  parseOptionalSubagents,
} from '@/features/registry/formCodecs';
import RegistryReferenceSelect from '@/features/registry/RegistryReferenceSelect';
import { controlClient } from '@/shared/api/controlClient';
import type { AgentSpecDTO, AgentSpecUpsertRequestDTO } from '@/shared/types/api';
import PageHeader from '@/shared/ui/PageHeader';

type AgentFormValues = {
  name: string;
  version: string;
  description: string;
  status: string;
  modelRef: string;
  tagsText: string;
  promptSystem: string;
  skillRefs: string[];
  mcpRefs: string[];
  interruptOnText: string;
  sandboxImage: string;
  sandboxResourcesJson: string;
  sandboxInitText: string;
  subagentsJson: string;
};

function toFormValues(agent?: AgentSpecDTO): AgentFormValues {
  return {
    name: agent?.name ?? '',
    version: agent?.version ?? '',
    description: agent?.description ?? '',
    status: agent?.status ?? 'draft',
    modelRef: agent?.model_ref ?? '',
    tagsText: formatMultilineList(agent?.tags),
    promptSystem: agent?.prompt?.system ?? '',
    skillRefs: agent?.skill_refs ?? [],
    mcpRefs: agent?.mcp_refs ?? [],
    interruptOnText: formatMultilineList(agent?.interrupt_on),
    sandboxImage: agent?.sandbox?.image ?? '',
    sandboxResourcesJson: formatJsonValue(agent?.sandbox?.resources),
    sandboxInitText: formatMultilineList(agent?.sandbox?.init),
    subagentsJson: formatJsonValue(agent?.subagents),
  };
}

export default function AgentDetailPage() {
  const navigate = useNavigate();
  const params = useParams<{ agentName: string }>();
  const routeAgentName = params.agentName ?? '';
  const isCreate = !routeAgentName || routeAgentName === 'new';
  const [form] = Form.useForm<AgentFormValues>();
  const [saving, setSaving] = useState(false);
  const agentQuery = useSWR(isCreate ? null : ['agent', routeAgentName], () => controlClient.agents.get(routeAgentName));

  useEffect(() => {
    if (isCreate) {
      form.setFieldsValue(toFormValues());
      return;
    }
    if (agentQuery.data) {
      form.setFieldsValue(toFormValues(agentQuery.data));
    }
  }, [agentQuery.data, form, isCreate]);

  async function handleSave() {
    const values = await form.validate();
    const name = values.name.trim();
    const request: AgentSpecUpsertRequestDTO = {
      version: values.version.trim() || undefined,
      description: values.description.trim() || undefined,
      tags: parseMultilineList(values.tagsText),
      model_ref: values.modelRef.trim() || undefined,
      prompt: {
        system: values.promptSystem,
      },
      skill_refs: values.skillRefs,
      mcp_refs: values.mcpRefs,
      subagents: parseOptionalSubagents(values.subagentsJson),
      sandbox: {
        image: values.sandboxImage.trim() || undefined,
        resources: parseOptionalStringMap(values.sandboxResourcesJson, 'sandbox.resources'),
        init: parseMultilineList(values.sandboxInitText),
      },
      interrupt_on: parseMultilineList(values.interruptOnText),
      status: values.status || undefined,
    };

    setSaving(true);
    try {
      const saved = await controlClient.agents.upsert(name, request);
      Message.success(`agent ${name} saved`);
      await agentQuery.mutate(saved, { revalidate: false });
      if (saved.name && (isCreate || saved.name !== routeAgentName)) {
        void navigate(links.agentDetail(saved.name), { replace: true });
        return;
      }
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to save agent');
      throw error;
    } finally {
      setSaving(false);
    }
  }

  async function handleEnsureRunnable() {
    if (isCreate) {
      return;
    }

    try {
      await controlClient.agents.ensureRunnable(routeAgentName);
      Message.success(`agent ${routeAgentName} is compiling`);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to ensure runnable');
    }
  }

  const loading = !isCreate && agentQuery.isLoading;

  return (
    <div>
      <PageHeader
        title={isCreate ? 'Create Agent' : routeAgentName}
        description='Edit the authored agent spec using registry-backed model, skill, and MCP references.'
        actions={
          <>
            {!isCreate ? (
              <Button onClick={() => void handleEnsureRunnable()}>
                Ensure Runnable
              </Button>
            ) : null}
            {!isCreate ? (
              <Button type='primary' onClick={() => void navigate(links.chatAgent(routeAgentName))}>
                Open Chat
              </Button>
            ) : null}
            <Button type='primary' loading={saving} onClick={() => void handleSave()}>
              Save
            </Button>
          </>
        }
      />
      <Spin loading={loading}>
        <div className='grid grid-cols-1 gap-18px xl:grid-cols-[1.2fr_0.8fr]'>
          <Card className='control-card'>
            <Form form={form} layout='vertical'>
              <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
                <Form.Item
                  field='name'
                  label='Name'
                  rules={[{ required: true, message: 'name is required' }]}
                >
                  <Input disabled={!isCreate} placeholder='assistant-prod' />
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
            </Form>
          </Card>
          <Card className='control-card'>
            <Typography.Title heading={5} className='!mt-0'>
              Notes
            </Typography.Title>
            <Space direction='vertical' size='large' className='w-full'>
              <div>
                <Typography.Paragraph className='!mb-6px text-[var(--control-subtle)]'>
                  Registry-backed references
                </Typography.Paragraph>
                <Typography.Paragraph className='!mb-0'>
                  `model_ref`, `skill_refs`, and `mcp_refs` now load registry options on demand in paged batches instead of
                  pulling the full registry into the form upfront.
                </Typography.Paragraph>
              </div>
              <div>
                <Typography.Paragraph className='!mb-6px text-[var(--control-subtle)]'>
                  Structured fields
                </Typography.Paragraph>
                <Typography.Paragraph className='!mb-0'>
                  `subagents` and `sandbox.resources` are edited as JSON for now to keep the northbound contract complete.
                </Typography.Paragraph>
              </div>
              {!isCreate && agentQuery.data ? (
                <div>
                  <Typography.Paragraph className='!mb-6px text-[var(--control-subtle)]'>
                    Metadata
                  </Typography.Paragraph>
                  <Typography.Paragraph className='!mb-4px'>created_at: {agentQuery.data.created_at ?? 'n/a'}</Typography.Paragraph>
                  <Typography.Paragraph className='!mb-4px'>updated_at: {agentQuery.data.updated_at ?? 'n/a'}</Typography.Paragraph>
                  <Typography.Paragraph className='!mb-0'>status: {agentQuery.data.status ?? 'n/a'}</Typography.Paragraph>
                </div>
              ) : null}
            </Space>
          </Card>
        </div>
      </Spin>
    </div>
  );
}
