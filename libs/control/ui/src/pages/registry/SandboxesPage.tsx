import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import useSWR from 'swr';
import SandboxEditorDrawer from '@/features/registry/SandboxEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';
import type { SandboxConfigDTO, SandboxConfigUpsertRequestDTO } from '@/shared/types/api';

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
        accent='#ff2d95'
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
  if (item.spec?.docker) {
    return 'docker';
  }
  if (item.spec?.kubernetes) {
    return 'kubernetes';
  }
  if (item.spec?.local) {
    return 'local';
  }
  return 'n/a';
}

function describeImage(item: SandboxConfigDTO): string {
  return item.spec?.docker?.image?.reference ?? item.spec?.kubernetes?.image?.reference ?? 'n/a';
}
