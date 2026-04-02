import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import { Server, Box, SettingConfig } from '@icon-park/react';
import useSWR from 'swr';
import SandboxEditorDrawer from '@/features/registry/SandboxEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import type { ResourceTypeConfig, StatBadge } from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';
import type { SandboxConfigDTO, SandboxConfigUpsertRequestDTO } from '@/shared/types/api';

const RESOURCE_TYPE: ResourceTypeConfig = {
  kind: 'sandbox',
  icon: <Server size={28} fill={['#ff2d95']} />,
  accent: '#ff2d95',
  glowColor: 'rgba(255,45,149,0.20)',
  headerTint: 'rgba(255,45,149,0.04)',
  categoryLabel: 'SANDBOX',
};

function buildStats(item: SandboxConfigDTO): StatBadge[] {
  return [
    { icon: 'Server', label: 'backend', value: describeBackend(item) },
    { icon: 'Box', label: 'image', value: describeImage(item) },
    { icon: 'SettingConfig', label: 'setup', value: `${item.spec?.setup_commands?.length ?? 0} cmds` },
  ];
}

function buildExpanded(item: SandboxConfigDTO) {
  const rows: Array<[string, string]> = [];
  const exec = item.spec?.execution;
  if (exec) {
    if (exec.command_timeout_seconds) rows.push(['command_timeout', `${exec.command_timeout_seconds}s`]);
    if (exec.setup_timeout_seconds) rows.push(['setup_timeout', `${exec.setup_timeout_seconds}s`]);
    if (exec.max_output_bytes) rows.push(['max_output', `${exec.max_output_bytes} bytes`]);
  }
  if (item.spec?.setup_commands && item.spec.setup_commands.length > 0) {
    rows.push(['setup_commands', item.spec.setup_commands.join(' && ')]);
  }
  if (item.spec?.env && item.spec.env.length > 0) {
    rows.push(['env', item.spec.env.map((e) => e.name).filter(Boolean).join(', ')]);
  }
  const docker = item.spec?.docker;
  if (docker?.resources) {
    const r = docker.resources;
    const parts: string[] = [];
    if (r.cpu) parts.push(`cpu=${r.cpu}`);
    if (r.memory) parts.push(`mem=${r.memory}`);
    if (parts.length > 0) rows.push(['resources', parts.join(', ')]);
  }
  if (rows.length === 0) return undefined;
  return (
    <div className='flex flex-col gap-4px'>
      {rows.map(([k, v]) => (
        <div key={k} className='flex flex-col gap-2px'>
          <span className='text-[var(--control-subtle)]'>{k}</span>
          <span className='break-all text-[var(--control-text)]'>{v}</span>
        </div>
      ))}
    </div>
  );
}

export default function SandboxesPage() {
  const [pageNumber, setPageNumber] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [editor, setEditor] = useState<{ mode: 'create' | 'edit'; value?: SandboxConfigDTO } | null>(null);
  const query = useSWR(['sandboxes', pageNumber, pageSize], () =>
    controlClient.sandboxes.list({ pageSize, pageNumber }),
  );

  async function handleSubmit(name: string, body: SandboxConfigUpsertRequestDTO) {
    try {
      await controlClient.sandboxes.upsert(name, body);
      Message.success(`sandbox ${name} saved`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to save sandbox');
      throw error;
    }
  }

  async function handleDelete(name: string) {
    try {
      await controlClient.sandboxes.delete(name);
      Message.success(`sandbox ${name} deleted`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to delete sandbox');
    }
  }

  return (
    <>
      <RegistryResourcePage
        title='Sandboxes'
        description='Manage reusable sandbox configs and attach them to agents via `sandbox_ref`.'
        resourceType={RESOURCE_TYPE}
        actions={
          <Button type='primary' onClick={() => setEditor({ mode: 'create' })}>
            Create Sandbox
          </Button>
        }
        loading={query.isLoading}
        pageNumber={pageNumber}
        pageSize={pageSize}
        totalSize={query.data?.total_size}
        onPageChange={(nextPageNumber, nextPageSize) => {
          setPageNumber(nextPageNumber);
          setPageSize(nextPageSize);
        }}
        items={(query.data?.sandboxes ?? []).map((item, index) => ({
          key: item.name ?? `sandbox-${pageNumber}-${index}`,
          name: item.name ?? 'unnamed-sandbox',
          description: item.description,
          status: item.status,
          updatedAt: item.updated_at,
          subtitle: describeBackend(item) !== 'n/a' ? `${describeBackend(item)} / ${describeImage(item)}` : undefined,
          stats: buildStats(item),
          expandedContent: buildExpanded(item),
          details: [
            { label: 'backend', value: describeBackend(item) },
            { label: 'image', value: describeImage(item) },
            { label: 'setup', value: String(item.spec?.setup_commands?.length ?? 0) },
          ],
          actions: item.name ? (
            <>
              <Button onClick={() => setEditor({ mode: 'edit', value: item })}>Edit</Button>
              <Popconfirm
                title={`Delete sandbox ${item.name}?`}
                content='The backend will reject deletion if any agent still references this sandbox.'
                onOk={() => void handleDelete(item.name!)}
              >
                <Button status='danger'>Delete</Button>
              </Popconfirm>
            </>
          ) : null,
        }))}
      />
      <SandboxEditorDrawer
        visible={editor !== null}
        mode={editor?.mode ?? 'create'}
        value={editor?.value}
        onClose={() => setEditor(null)}
        onSubmit={handleSubmit}
      />
    </>
  );
}

function describeBackend(item: SandboxConfigDTO): string {
  if (item.spec?.docker) return 'docker';
  if (item.spec?.kubernetes) return 'kubernetes';
  if (item.spec?.local) return 'local';
  return 'n/a';
}

function describeImage(item: SandboxConfigDTO): string {
  return item.spec?.docker?.image?.reference ?? item.spec?.kubernetes?.image?.reference ?? 'n/a';
}
