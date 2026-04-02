import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import { Brain, CloudStorage, LinkOne } from '@icon-park/react';
import useSWR from 'swr';
import ModelEditorDrawer from '@/features/registry/ModelEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import type { ResourceTypeConfig, StatBadge } from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';
import type { ModelConfigDTO, ModelConfigUpsertRequestDTO } from '@/shared/types/api';

const RESOURCE_TYPE: ResourceTypeConfig = {
  kind: 'model',
  icon: <Brain size={28} fill={['#00f0ff']} />,
  accent: '#00f0ff',
  glowColor: 'rgba(0,240,255,0.20)',
  headerTint: 'rgba(0,240,255,0.04)',
  categoryLabel: 'MODEL',
};

function buildStats(item: ModelConfigDTO): StatBadge[] {
  return [
    { icon: 'CloudStorage', label: 'provider', value: item.provider ?? 'n/a' },
    { icon: 'Brain', label: 'model', value: item.model ?? 'n/a' },
    { icon: 'LinkOne', label: 'endpoint', value: item.base_url ? 'custom' : 'default' },
  ];
}

function buildExpanded(item: ModelConfigDTO) {
  const rows: Array<[string, string]> = [];
  if (item.base_url) rows.push(['base_url', item.base_url]);
  if (item.api_key) rows.push(['api_key', item.api_key]);
  if (item.api_key_env) rows.push(['api_key_env', item.api_key_env]);
  if (item.extra_params) {
    for (const [k, v] of Object.entries(item.extra_params)) {
      rows.push([`extra.${k}`, v]);
    }
  }
  if (rows.length === 0) return undefined;
  return (
    <div className='flex flex-col gap-4px'>
      {rows.map(([k, v]) => (
        <div key={k} className='flex items-center justify-between gap-8px'>
          <span className='text-[var(--control-subtle)]'>{k}</span>
          <span className='truncate text-[var(--control-text)]'>{v}</span>
        </div>
      ))}
    </div>
  );
}

export default function ModelsPage() {
  const [pageNumber, setPageNumber] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [editor, setEditor] = useState<{ mode: 'create' | 'edit'; value?: ModelConfigDTO } | null>(null);
  const query = useSWR(['models', pageNumber, pageSize], () => controlClient.models.list({ pageSize, pageNumber }));

  async function handleSubmit(name: string, body: ModelConfigUpsertRequestDTO) {
    try {
      await controlClient.models.upsert(name, body);
      Message.success(`model ${name} saved`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to save model');
      throw error;
    }
  }

  async function handleDelete(name: string) {
    try {
      await controlClient.models.delete(name);
      Message.success(`model ${name} deleted`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to delete model');
    }
  }

  return (
    <>
      <RegistryResourcePage
        title='Models'
        description='Manage model configs in the control-plane registry.'
        resourceType={RESOURCE_TYPE}
        actions={
          <Button type='primary' onClick={() => setEditor({ mode: 'create' })}>
            Create Model
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
        items={(query.data?.models ?? []).map((item, index) => ({
          key: item.name ?? `model-${pageNumber}-${index}`,
          name: item.name ?? 'unnamed-model',
          description: item.description,
          status: item.status,
          updatedAt: item.updated_at,
          subtitle: [item.provider, item.model].filter(Boolean).join(' / ') || undefined,
          stats: buildStats(item),
          expandedContent: buildExpanded(item),
          details: [
            { label: 'provider', value: item.provider ?? 'n/a' },
            { label: 'model', value: item.model ?? 'n/a' },
            { label: 'base_url', value: item.base_url ?? 'default' },
          ],
          actions: item.name ? (
            <>
              <Button onClick={() => setEditor({ mode: 'edit', value: item })}>Edit</Button>
              <Popconfirm
                title={`Delete model ${item.name}?`}
                content='The backend will reject deletion if any agent still references this model.'
                onOk={() => void handleDelete(item.name!)}
              >
                <Button status='danger'>Delete</Button>
              </Popconfirm>
            </>
          ) : null,
        }))}
      />
      <ModelEditorDrawer
        visible={editor !== null}
        mode={editor?.mode ?? 'create'}
        value={editor?.value}
        onClose={() => setEditor(null)}
        onSubmit={handleSubmit}
      />
    </>
  );
}
