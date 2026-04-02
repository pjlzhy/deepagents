import { useCallback, useEffect, useMemo, useState } from 'react';
import { Form, Message, Spin, Typography } from '@arco-design/web-react';
import useSWR from 'swr';
import { useNavigate, useParams } from 'react-router-dom';
import { links } from '@/app/links';
import { controlClient } from '@/shared/api/controlClient';
import AgentBuilderLayout from '@/features/agent-builder/AgentBuilderLayout';
import {
  toBuildFormValues,
  toBuildUpsertRequest,
  computeStepCompletion,
  type BuilderFormValues,
  type StepCompletion,
} from '@/features/agent-builder/builderForm';
import '@/styles/agent-builder.css';

export default function AgentBuilderPage() {
  const navigate = useNavigate();
  const params = useParams<{ agentName?: string }>();
  const isEdit = Boolean(params.agentName);
  const [form] = Form.useForm<BuilderFormValues>();
  const [currentStep, setCurrentStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [completion, setCompletion] = useState<StepCompletion[]>(() =>
    computeStepCompletion(toBuildFormValues()),
  );

  const agentQuery = useSWR(
    isEdit && params.agentName ? ['builder-agent', params.agentName] : null,
    () => controlClient.agents.get(params.agentName!),
  );

  useEffect(() => {
    if (isEdit && agentQuery.data) {
      const values = toBuildFormValues(agentQuery.data);
      form.setFieldsValue(values);
      setCompletion(computeStepCompletion(values));
    } else if (!isEdit) {
      const values = toBuildFormValues();
      form.setFieldsValue(values);
      setCompletion(computeStepCompletion(values));
    }
  }, [agentQuery.data, form, isEdit]);

  const handleValuesChange = useCallback(() => {
    const values = form.getFieldsValue();
    setCompletion(computeStepCompletion(values));
  }, [form]);

  const handleSave = useCallback(async () => {
    let values: BuilderFormValues;
    try {
      values = await form.validate();
    } catch {
      Message.warning('Please fix validation errors before saving');
      return;
    }

    const name = values.name.trim();
    if (!name) {
      Message.warning('Agent name is required');
      return;
    }

    setSaving(true);
    try {
      await controlClient.agents.upsert(name, toBuildUpsertRequest(values));
      Message.success(`Agent "${name}" saved`);
      if (!isEdit) {
        void navigate(links.buildAgentEdit(name), { replace: true });
      }
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'Failed to save agent');
    } finally {
      setSaving(false);
    }
  }, [form, isEdit, navigate]);

  const handleBuild = useCallback(async () => {
    await handleSave();
    const values = form.getFieldsValue();
    const name = (values.name ?? '').trim();
    if (!name) return;

    try {
      await controlClient.agents.ensureRunnable(name);
      Message.success(`Agent "${name}" is compiling`);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'Failed to build agent');
    }
  }, [form, handleSave]);

  const loading = isEdit && agentQuery.isLoading;
  const errorMessage = isEdit && agentQuery.error instanceof Error ? agentQuery.error.message : undefined;

  if (loading) {
    return (
      <div className='flex-center h-full'>
        <Spin size={32} />
      </div>
    );
  }

  if (errorMessage) {
    return (
      <div className='flex-center h-full'>
        <Typography.Text type='error'>Failed to load agent: {errorMessage}</Typography.Text>
      </div>
    );
  }

  return (
    <div className='agent-builder flex h-full flex-col overflow-hidden'>
      <Form
        form={form}
        layout='vertical'
        onValuesChange={handleValuesChange}
        className='flex min-h-0 flex-1 flex-col'
      >
        <AgentBuilderLayout
          currentStep={currentStep}
          completion={completion}
          onStepChange={setCurrentStep}
          saving={saving}
          onSave={handleSave}
          onBuild={handleBuild}
          isEdit={isEdit}
          form={form}
        />
      </Form>
    </div>
  );
}
