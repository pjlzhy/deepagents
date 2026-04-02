import { useEffect, useState } from 'react';
import { Button, Drawer, Form, Input, InputNumber, Select } from '@arco-design/web-react';
import { Server } from '@icon-park/react';
import type { SandboxConfigDTO, SandboxConfigUpsertRequestDTO, SandboxEnvVarDTO } from '@/shared/types/api';
import {
  authoredStatusOptions,
  formatMultilineList,
  parseMultilineList,
} from '@/features/registry/formCodecs';
import KeyValueEditor from '@/shared/components/KeyValueEditor';
import '@/styles/registry-cards.css';

const ACCENT = '#ff2d95';

type SandboxEditorDrawerProps = {
  visible: boolean;
  mode: 'create' | 'edit';
  value?: SandboxConfigDTO;
  onClose: () => void;
  onSubmit: (name: string, body: SandboxConfigUpsertRequestDTO) => Promise<void>;
};

type SandboxFormValues = {
  name: string;
  description: string;
  status: string;
  backend: 'local' | 'docker' | 'kubernetes';
  imageReference: string;
  imagePullPolicy: string;
  commandTimeoutSeconds?: number;
  setupTimeoutSeconds?: number;
  startupTimeoutSeconds?: number;
  maxOutputBytes?: number;
  env: Record<string, string>;
  setupCommandsText: string;
  dockerCpu: string;
  dockerMemory: string;
  dockerShmSize: string;
  dockerPidsLimit?: number;
  kubernetesRequests: Record<string, string>;
  kubernetesLimits: Record<string, string>;
};

const pullPolicyOptions = [
  { label: 'default', value: '' },
  { label: 'if_not_present', value: 'if_not_present' },
  { label: 'always', value: 'always' },
  { label: 'never', value: 'never' },
] as const;

function SectionLabel({ title, color = ACCENT }: { title: string; color?: string }) {
  return (
    <div className='flex items-center gap-8px mt-14px mb-8px'>
      <span className='text-11px font-bold tracking-wider uppercase' style={{ color }}>
        {title}
      </span>
      <div className='flex-1 h-1px' style={{ background: `${color}18` }} />
    </div>
  );
}

export default function SandboxEditorDrawer(props: SandboxEditorDrawerProps) {
  const [form] = Form.useForm<SandboxFormValues>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!props.visible) {
      form.resetFields();
      setSubmitting(false);
      return;
    }

    const spec = props.value?.spec;
    const backend = spec?.docker
      ? 'docker'
      : spec?.kubernetes
        ? 'kubernetes'
        : 'local';

    form.setFieldsValue({
      name: props.value?.name ?? '',
      description: props.value?.description ?? '',
      status: props.value?.status ?? 'draft',
      backend,
      imageReference: spec?.docker?.image?.reference ?? spec?.kubernetes?.image?.reference ?? '',
      imagePullPolicy: spec?.docker?.image?.pull_policy ?? spec?.kubernetes?.image?.pull_policy ?? '',
      commandTimeoutSeconds: spec?.execution?.command_timeout_seconds,
      setupTimeoutSeconds: spec?.execution?.setup_timeout_seconds,
      startupTimeoutSeconds: spec?.execution?.startup_timeout_seconds,
      maxOutputBytes: spec?.execution?.max_output_bytes,
      env: sandboxEnvToRecord(spec?.env),
      setupCommandsText: formatMultilineList(spec?.setup_commands),
      dockerCpu: spec?.docker?.resources?.cpu ?? '',
      dockerMemory: spec?.docker?.resources?.memory ?? '',
      dockerShmSize: spec?.docker?.resources?.shm_size ?? '',
      dockerPidsLimit: spec?.docker?.resources?.pids_limit,
      kubernetesRequests: spec?.kubernetes?.resources?.requests ?? {},
      kubernetesLimits: spec?.kubernetes?.resources?.limits ?? {},
    });
  }, [form, props.value, props.visible]);

  async function handleSubmit() {
    const values = await form.validate();
    validateSandboxForm(values);
    const name = values.name.trim();

    setSubmitting(true);
    try {
      await props.onSubmit(name, {
        description: values.description.trim() || undefined,
        spec: buildSandboxSpec(values),
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
      width={920}
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
          <Server size={22} fill={[ACCENT]} />
        </div>
        <div>
          <div className='text-16px font-700 text-[var(--control-text)]'>
            {isEdit ? `Edit / ${props.value?.name ?? ''}` : 'Create Sandbox'}
          </div>
          <div className='text-12px text-[var(--control-subtle)]'>
            Configure execution environment — backend, image, resources, and setup
          </div>
        </div>
        <span
          className='ml-auto rd-full px-8px py-2px text-10px font-bold tracking-wider uppercase border border-solid shrink-0'
          style={{ color: ACCENT, borderColor: `${ACCENT}40`, background: `${ACCENT}0a` }}
        >
          SANDBOX
        </span>
      </div>

      <Form form={form} layout='vertical'>
        {/* Identity */}
        <SectionLabel title='Identity' />
        <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
          <Form.Item field='name' label='Name' rules={[{ required: true, message: 'name is required' }]}>
            <Input placeholder='python-slim' disabled={isEdit} />
          </Form.Item>
          <Form.Item field='status' label='Status' rules={[{ required: true, message: 'status is required' }]}>
            <Select options={authoredStatusOptions as unknown as Array<{ label: string; value: string }>} />
          </Form.Item>
        </div>
        <Form.Item field='description' label='Description'>
          <Input placeholder='Python sandbox for general coding tasks' />
        </Form.Item>

        {/* Backend */}
        <SectionLabel title='Backend' />
        <div className='grid grid-cols-1 gap-16px md:grid-cols-3'>
          <Form.Item field='backend' label='Backend' rules={[{ required: true, message: 'backend is required' }]}>
            <Select
              className='w-full'
              options={[
                { label: 'local', value: 'local' },
                { label: 'docker', value: 'docker' },
                { label: 'kubernetes', value: 'kubernetes' },
              ]}
              onChange={(value) => handleBackendChange(form, value as SandboxFormValues['backend'])}
            />
          </Form.Item>
          <Form.Item shouldUpdate noStyle>
            {(values) =>
              values.backend === 'local' ? null : (
                <Form.Item field='imageReference' label='Image' rules={[{ required: true, message: 'image is required' }]}>
                  <Input className='w-full' placeholder='python:3.12-slim' />
                </Form.Item>
              )
            }
          </Form.Item>
          <Form.Item shouldUpdate noStyle>
            {(values) =>
              values.backend === 'local' ? null : (
                <Form.Item field='imagePullPolicy' label='Pull Policy' rules={[{ required: true, message: 'pull policy is required' }]}>
                  <Select
                    className='w-full'
                    options={pullPolicyOptions as unknown as Array<{ label: string; value: string }>}
                  />
                </Form.Item>
              )
            }
          </Form.Item>
        </div>

        {/* Docker Resources */}
        <Form.Item shouldUpdate noStyle>
          {(values) =>
            values.backend === 'docker' ? (
              <>
                <SectionLabel title='Docker Resources' />
                <div className='grid grid-cols-2 gap-16px xl:grid-cols-4'>
                  <Form.Item field='dockerCpu' label='CPU'>
                    <Input placeholder='2' />
                  </Form.Item>
                  <Form.Item field='dockerMemory' label='Memory'>
                    <Input placeholder='4Gi' />
                  </Form.Item>
                  <Form.Item field='dockerShmSize' label='SHM Size'>
                    <Input placeholder='1Gi' />
                  </Form.Item>
                  <Form.Item field='dockerPidsLimit' label='PIDs Limit'>
                    <InputNumber min={0} placeholder='0' className='w-full' />
                  </Form.Item>
                </div>
              </>
            ) : null
          }
        </Form.Item>

        {/* Kubernetes Resources */}
        <Form.Item shouldUpdate noStyle>
          {(values) =>
            values.backend === 'kubernetes' ? (
              <>
                <SectionLabel title='Kubernetes Resources' />
                <div className='grid grid-cols-1 gap-16px md:grid-cols-2'>
                  <Form.Item field='kubernetesRequests' label='Requests'>
                    <KeyValueEditor keyPlaceholder='Resource' valuePlaceholder='Value' />
                  </Form.Item>
                  <Form.Item field='kubernetesLimits' label='Limits'>
                    <KeyValueEditor keyPlaceholder='Resource' valuePlaceholder='Value' />
                  </Form.Item>
                </div>
              </>
            ) : null
          }
        </Form.Item>

        {/* Execution Policy */}
        <SectionLabel title='Execution Policy' />
        <div className='grid grid-cols-2 gap-16px xl:grid-cols-4'>
          <Form.Item field='commandTimeoutSeconds' label='Command Timeout (s)'>
            <InputNumber min={0} placeholder='0' className='w-full' />
          </Form.Item>
          <Form.Item field='setupTimeoutSeconds' label='Setup Timeout (s)'>
            <InputNumber min={0} placeholder='0' className='w-full' />
          </Form.Item>
          <Form.Item field='startupTimeoutSeconds' label='Startup Timeout (s)'>
            <InputNumber min={0} placeholder='0' className='w-full' />
          </Form.Item>
          <Form.Item field='maxOutputBytes' label='Max Output (bytes)'>
            <InputNumber min={0} placeholder='0' className='w-full' />
          </Form.Item>
        </div>

        {/* Environment & Setup */}
        <SectionLabel title='Environment & Setup' />
        <Form.Item field='env' label='Environment Variables'>
          <KeyValueEditor keyPlaceholder='Variable' valuePlaceholder='Value' />
        </Form.Item>
        <Form.Item field='setupCommandsText' label='Setup Commands' extra='One command per line, executed after sandbox startup'>
          <Input.TextArea
            autoSize={{ minRows: 3, maxRows: 10 }}
            placeholder={'python --version\npip install -r requirements.txt'}
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
}

/* ── Helpers (unchanged logic) ── */

function sandboxEnvToRecord(env?: SandboxEnvVarDTO[]): Record<string, string> {
  if (!env || env.length === 0) return {};
  const result: Record<string, string> = {};
  for (const item of env) {
    if (item.name) result[item.name] = item.value ?? '';
  }
  return result;
}

function recordToSandboxEnv(record: Record<string, string>): SandboxEnvVarDTO[] | undefined {
  const entries = Object.entries(record);
  if (entries.length === 0) return undefined;
  return entries.map(([name, value]) => ({ name, value }));
}

function optionalRecord(record: Record<string, string>): Record<string, string> | undefined {
  return Object.keys(record).length > 0 ? record : undefined;
}

function buildSandboxSpec(values: SandboxFormValues): SandboxConfigUpsertRequestDTO['spec'] {
  const spec: SandboxConfigUpsertRequestDTO['spec'] = {
    execution: {
      command_timeout_seconds: values.commandTimeoutSeconds || undefined,
      setup_timeout_seconds: values.setupTimeoutSeconds || undefined,
      startup_timeout_seconds: values.startupTimeoutSeconds || undefined,
      max_output_bytes: values.maxOutputBytes || undefined,
    },
    env: recordToSandboxEnv(values.env),
    setup_commands: parseMultilineList(values.setupCommandsText),
  };

  if (!spec.execution?.command_timeout_seconds &&
    !spec.execution?.setup_timeout_seconds &&
    !spec.execution?.startup_timeout_seconds &&
    !spec.execution?.max_output_bytes) {
    spec.execution = undefined;
  }

  if (values.backend === 'local') {
    spec.local = {};
    return spec;
  }

  const image = {
    reference: (values.imageReference ?? '').trim() || undefined,
    pull_policy: (values.imagePullPolicy ?? '').trim() || undefined,
  };

  if (values.backend === 'docker') {
    spec.docker = {
      image,
      resources: {
        cpu: (values.dockerCpu ?? '').trim() || undefined,
        memory: (values.dockerMemory ?? '').trim() || undefined,
        shm_size: (values.dockerShmSize ?? '').trim() || undefined,
        pids_limit: values.dockerPidsLimit || undefined,
      },
    };
    return spec;
  }

  spec.kubernetes = {
    image,
    resources: {
      requests: optionalRecord(values.kubernetesRequests),
      limits: optionalRecord(values.kubernetesLimits),
    },
  };
  return spec;
}

function validateSandboxForm(values: SandboxFormValues): void {
  if (values.backend !== 'local' && !(values.imageReference ?? '').trim()) {
    throw new Error('image reference is required for docker and kubernetes sandboxes');
  }
}

function handleBackendChange(
  form: ReturnType<typeof Form.useForm<SandboxFormValues>>[0],
  backend: SandboxFormValues['backend'],
): void {
  if (backend === 'local') {
    form.clearFields([
      'imageReference',
      'imagePullPolicy',
      'dockerCpu',
      'dockerMemory',
      'dockerShmSize',
      'dockerPidsLimit',
      'kubernetesRequests',
      'kubernetesLimits',
    ]);
    return;
  }

  if (backend === 'docker') {
    form.clearFields(['kubernetesRequests', 'kubernetesLimits']);
    return;
  }

  form.clearFields(['dockerCpu', 'dockerMemory', 'dockerShmSize', 'dockerPidsLimit']);
}
