import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import useSWR from 'swr';
import SkillEditorDrawer from '@/features/registry/SkillEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';
import type { SkillDTO, SkillUpsertRequestDTO } from '@/shared/types/api';

export default function SkillsPage() {
  const [pageNumber, setPageNumber] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [editor, setEditor] = useState<{ mode: 'create' | 'edit'; value?: SkillDTO } | null>(null);
  const query = useSWR(['skills', pageNumber, pageSize], () => controlClient.skills.list({ pageSize, pageNumber }));

  async function handleSubmit(name: string, body: SkillUpsertRequestDTO) {
    try {
      await controlClient.skills.upsert(name, body);
      Message.success(`skill ${name} saved`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to save skill');
      throw error;
    }
  }

  async function handleDelete(name: string) {
    try {
      await controlClient.skills.delete(name);
      Message.success(`skill ${name} deleted`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to delete skill');
    }
  }

  return (
    <>
      <RegistryResourcePage
        title='Skills'
        description='Manage skills and their extra files, including scripts and references.'
        actions={
          <Button type='primary' onClick={() => setEditor({ mode: 'create' })}>
            Create Skill
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
        items={(query.data?.skills ?? []).map((item, index) => ({
          key: item.name ?? `skill-${pageNumber}-${index}`,
          name: item.name ?? 'unnamed-skill',
          description: item.description,
          status: item.status,
          updatedAt: item.updated_at,
          tags: item.tags,
          details: [
            { label: 'content', value: item.content ? `${item.content.length} chars` : 'empty' },
            { label: 'files', value: String(item.files?.length ?? 0) },
          ],
          actions: item.name ? (
            <>
              <Button onClick={() => setEditor({ mode: 'edit', value: item })}>Edit</Button>
              <Popconfirm
                title={`Delete skill ${item.name}?`}
                content='The backend will reject deletion if any agent still references this skill.'
                onOk={() => void handleDelete(item.name!)}
              >
                <Button status='danger'>Delete</Button>
              </Popconfirm>
            </>
          ) : null,
        }))}
      />
      <SkillEditorDrawer
        visible={editor !== null}
        mode={editor?.mode ?? 'create'}
        value={editor?.value}
        onClose={() => setEditor(null)}
        onSubmit={handleSubmit}
      />
    </>
  );
}
