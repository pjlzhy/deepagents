import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import useSWR from 'swr';
import SkillDetailDrawer from '@/features/registry/SkillDetailDrawer';
import SkillEditorDrawer from '@/features/registry/SkillEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';
import type { SkillDTO, SkillDetailDTO } from '@/shared/types/api';

export default function SkillsPage() {
  const [pageNumber, setPageNumber] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [editor, setEditor] = useState<{ mode: 'create' | 'replace'; value?: SkillDTO } | null>(null);
  const [viewerName, setViewerName] = useState<string | null>(null);
  const query = useSWR(['skills', pageNumber, pageSize], () => controlClient.skills.list({ pageSize, pageNumber }));
  const detailQuery = useSWR(viewerName ? ['skill-detail', viewerName] : null, () =>
    controlClient.skills.get(viewerName!),
  );

  async function handleSubmit(file: File) {
    try {
      if (editor?.mode === 'replace' && editor.value?.name) {
        await controlClient.skills.replacePackage(editor.value.name, file);
        Message.success(`skill ${editor.value.name} replaced`);
        setViewerName(editor.value.name);
      } else {
        const detail = await controlClient.skills.createPackage(file);
        Message.success(`skill ${detail.name ?? file.name} uploaded`);
        setViewerName(detail.name ?? null);
      }
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to upload skill package');
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

  async function handleDownload(name: string) {
    try {
      const blob = await controlClient.skills.downloadPackage(name);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${name}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
      Message.success(`skill ${name} downloaded`);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to download skill');
    }
  }

  return (
    <>
      <RegistryResourcePage
        title='Skills'
        description='Manage uploaded skill snapshots. Skills are created and replaced with zip packages, then inspected in read-only detail.'
        accent='#39ff14'
        actions={
          <Button type='primary' onClick={() => setEditor({ mode: 'create' })}>
            Upload Skill
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
          details: [
            { label: 'files', value: String(item.file_count ?? 0) },
            { label: 'license', value: formatSkillCardValue(item.license) },
            { label: 'digest', value: formatDigest(item.snapshot_digest) },
          ],
          actions: item.name ? (
            <>
              <Button onClick={() => setViewerName(item.name ?? null)}>View</Button>
              <Button onClick={() => setEditor({ mode: 'replace', value: item })}>Replace</Button>
              <Button onClick={() => void handleDownload(item.name!)}>Download</Button>
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
      <SkillDetailDrawer
        visible={viewerName !== null}
        loading={detailQuery.isLoading}
        value={detailQuery.data}
        onClose={() => setViewerName(null)}
        onDownload={() => {
          if (viewerName) {
            void handleDownload(viewerName);
          }
        }}
        onReplace={() => {
          setEditor({
            mode: 'replace',
            value: detailQuery.data ? skillDetailToSummary(detailQuery.data) : { name: viewerName ?? undefined },
          });
          setViewerName(null);
        }}
      />
    </>
  );
}

function formatSkillCardValue(value: unknown): string {
  if (value === null || value === undefined) {
    return 'n/a';
  }
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value);
}

function formatDigest(value?: string): string {
  if (!value) {
    return 'n/a';
  }
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

function skillDetailToSummary(value: SkillDetailDTO): SkillDTO {
  return {
    name: value.name,
    description: value.description,
    status: value.status,
    created_at: value.created_at,
    updated_at: value.updated_at,
    license: value.license,
    compatibility: value.compatibility,
    metadata: value.metadata,
    allowed_tools: value.allowed_tools,
    file_count: value.file_count,
    snapshot_digest: value.snapshot_digest,
  };
}
