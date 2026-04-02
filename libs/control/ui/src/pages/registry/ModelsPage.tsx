import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import useSWR from 'swr';
import ModelEditorDrawer from '@/features/registry/ModelEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';
import type { ModelConfigDTO, ModelConfigUpsertRequestDTO } from '@/shared/types/api';

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
        accent='#00f0ff'
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
