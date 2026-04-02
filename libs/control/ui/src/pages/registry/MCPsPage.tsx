import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import { PlugOne, Terminal, Exchange, Code } from '@icon-park/react';
import useSWR from 'swr';
import MCPEditorDrawer from '@/features/registry/MCPEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import type { ResourceTypeConfig, StatBadge } from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';
import type { MCPConfigDTO, MCPConfigUpsertRequestDTO } from '@/shared/types/api';

const RESOURCE_TYPE: ResourceTypeConfig = {
  kind: 'mcp',
  icon: <PlugOne size={28} fill={['#ff9f1a']} />,
  accent: '#ff9f1a',
  glowColor: 'rgba(255,159,26,0.20)',
  headerTint: 'rgba(255,159,26,0.04)',
  categoryLabel: 'MCP',
};

function buildStats(item: MCPConfigDTO): StatBadge[] {
  return [
    { icon: 'Terminal', label: 'command', value: item.command ?? 'n/a' },
    { icon: 'Exchange', label: 'transport', value: item.transport ?? 'stdio' },
    { icon: 'Code', label: 'args', value: item.args?.length ?? 0 },
  ];
}

function buildExpanded(item: MCPConfigDTO) {
  const rows: Array<[string, string]> = [];
  if (item.args && item.args.length > 0) {
    rows.push(['args', item.args.join(' ')]);
  }
  if (item.env && Object.keys(item.env).length > 0) {
    rows.push(['env keys', Object.keys(item.env).join(', ')]);
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

export default function MCPsPage() {
  const [pageNumber, setPageNumber] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [editor, setEditor] = useState<{ mode: 'create' | 'edit'; value?: MCPConfigDTO } | null>(null);
  const query = useSWR(['mcps', pageNumber, pageSize], () => controlClient.mcps.list({ pageSize, pageNumber }));

  async function handleSubmit(name: string, body: MCPConfigUpsertRequestDTO) {
    try {
      await controlClient.mcps.upsert(name, body);
      Message.success(`mcp ${name} saved`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to save mcp');
      throw error;
    }
  }

  async function handleDelete(name: string) {
    try {
      await controlClient.mcps.delete(name);
      Message.success(`mcp ${name} deleted`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to delete mcp');
    }
  }

  return (
    <>
      <RegistryResourcePage
        title='MCPs'
        description='Manage MCP server configs, including command, args, env, and transport.'
        resourceType={RESOURCE_TYPE}
        actions={
          <Button type='primary' onClick={() => setEditor({ mode: 'create' })}>
            Create MCP
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
        items={(query.data?.mcps ?? []).map((item, index) => ({
          key: item.name ?? `mcp-${pageNumber}-${index}`,
          name: item.name ?? 'unnamed-mcp',
          description: item.description,
          status: item.status,
          updatedAt: item.updated_at,
          subtitle: item.command ? `${item.command}` : undefined,
          stats: buildStats(item),
          expandedContent: buildExpanded(item),
          details: [
            { label: 'command', value: item.command ?? 'n/a' },
            { label: 'transport', value: item.transport ?? 'stdio' },
            { label: 'args', value: String(item.args?.length ?? 0) },
          ],
          actions: item.name ? (
            <>
              <Button onClick={() => setEditor({ mode: 'edit', value: item })}>Edit</Button>
              <Popconfirm
                title={`Delete mcp ${item.name}?`}
                content='The backend will reject deletion if any agent still references this mcp.'
                onOk={() => void handleDelete(item.name!)}
              >
                <Button status='danger'>Delete</Button>
              </Popconfirm>
            </>
          ) : null,
        }))}
      />
      <MCPEditorDrawer
        visible={editor !== null}
        mode={editor?.mode ?? 'create'}
        value={editor?.value}
        onClose={() => setEditor(null)}
        onSubmit={handleSubmit}
      />
    </>
  );
}
