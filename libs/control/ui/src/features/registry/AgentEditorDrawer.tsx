import { useEffect, useState } from 'react';
import { Button, Card, Drawer, Form, Message, Space, Spin, Typography } from '@arco-design/web-react';
import useSWR from 'swr';
import { useNavigate } from 'react-router-dom';
import { links } from '@/app/links';
import AgentEditorNotes from '@/features/registry/AgentEditorNotes';
import AgentFormFields from '@/features/registry/AgentFormFields';
import { toAgentFormValues, toAgentUpsertRequest, type AgentFormValues } from '@/features/registry/agentForm';
import { controlClient } from '@/shared/api/controlClient';
import type { AgentSpecDTO } from '@/shared/types/api';

type AgentEditorDrawerProps = {
  visible: boolean;
  mode: 'create' | 'edit';
  agentName?: string;
  onClose: () => void;
  onSaved?: (saved: AgentSpecDTO) => Promise<void> | void;
};

export default function AgentEditorDrawer(props: AgentEditorDrawerProps) {
  const navigate = useNavigate();
  const [form] = Form.useForm<AgentFormValues>();
  const [saving, setSaving] = useState(false);
  const isCreate = props.mode === 'create';
  const agentQuery = useSWR(
    props.visible && !isCreate && props.agentName ? ['agent-editor', props.agentName] : null,
    () => controlClient.agents.get(props.agentName!),
  );

  useEffect(() => {
    if (!props.visible) {
      form.resetFields();
      setSaving(false);
      return;
    }

    if (isCreate) {
      form.setFieldsValue(toAgentFormValues());
      return;
    }

    if (agentQuery.data) {
      form.setFieldsValue(toAgentFormValues(agentQuery.data));
    }
  }, [agentQuery.data, form, isCreate, props.visible]);

  async function handleSave() {
    const values = await form.validate();
    const name = values.name.trim();

    setSaving(true);
    try {
      const saved = await controlClient.agents.upsert(name, toAgentUpsertRequest(values));
      Message.success(`agent ${name} saved`);
      await props.onSaved?.(saved);
      props.onClose();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to save agent');
      throw error;
    } finally {
      setSaving(false);
    }
  }

  async function handleEnsureRunnable() {
    if (isCreate || !props.agentName) {
      return;
    }

    try {
      await controlClient.agents.ensureRunnable(props.agentName);
      Message.success(`agent ${props.agentName} is compiling`);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to ensure runnable');
    }
  }

  const loading = !isCreate && agentQuery.isLoading;
  const errorMessage = !isCreate && agentQuery.error instanceof Error ? agentQuery.error.message : undefined;

  return (
    <Drawer
      width={1120}
      title={isCreate ? 'Create Agent' : `Edit Agent / ${props.agentName ?? ''}`}
      visible={props.visible}
      unmountOnExit
      onCancel={props.onClose}
      footer={
        <div className='flex flex-wrap items-center justify-between gap-12px'>
          <Space wrap>
            {!isCreate ? (
              <Button onClick={() => void handleEnsureRunnable()}>
                Ensure Runnable
              </Button>
            ) : null}
            {!isCreate && props.agentName ? (
              <Button
                onClick={() => {
                  props.onClose();
                  void navigate(links.chatAgent(props.agentName!));
                }}
              >
                Open Chat
              </Button>
            ) : null}
          </Space>
          <Space wrap>
            <Button onClick={props.onClose}>Cancel</Button>
            <Button type='primary' loading={saving} onClick={() => void handleSave()}>
              Save
            </Button>
          </Space>
        </div>
      }
    >
      <Spin loading={loading}>
        {errorMessage ? (
          <Card className='control-card'>
            <Typography.Text type='error'>Failed to load agent: {errorMessage}</Typography.Text>
          </Card>
        ) : (
          <div className='grid grid-cols-1 gap-18px xl:grid-cols-[1.2fr_0.8fr]'>
            <Card className='control-card'>
              <Form form={form} layout='vertical'>
                <AgentFormFields disableName={!isCreate} />
              </Form>
            </Card>
            <Card className='control-card'>
              <AgentEditorNotes agent={isCreate ? undefined : agentQuery.data} />
            </Card>
          </div>
        )}
      </Spin>
    </Drawer>
  );
}
