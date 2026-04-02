import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import { RobotOne, Brain, Lightning, PlugOne, HardDisk, Peoples } from '@icon-park/react';
import useSWR from 'swr';
import { useMatch, useNavigate, useParams } from 'react-router-dom';
import { links } from '@/app/links';
import AgentEditorDrawer from '@/features/registry/AgentEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import type { ResourceTypeConfig, StatBadge } from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';
import type { AgentSpecDTO } from '@/shared/types/api';

const RESOURCE_TYPE: ResourceTypeConfig = {
  kind: 'agent',
  icon: <RobotOne size={28} fill={['#a855f7']} />,
  accent: '#a855f7',
  glowColor: 'rgba(168,85,247,0.20)',
  headerTint: 'rgba(168,85,247,0.04)',
  categoryLabel: 'AGENT',
};

function buildStats(item: AgentSpecDTO): StatBadge[] {
  const stats: StatBadge[] = [
    { icon: 'Brain', label: 'model', value: item.model_ref ?? 'n/a' },
    { icon: 'Lightning', label: 'skills', value: item.skill_refs?.length ?? 0 },
    { icon: 'PlugOne', label: 'mcps', value: item.mcp_refs?.length ?? 0 },
  ];
  if (item.sandbox_ref) {
    stats.push({ icon: 'HardDisk', label: 'sandbox', value: item.sandbox_ref });
  }
  if (item.subagents && item.subagents.length > 0) {
    stats.push({ icon: 'Peoples', label: 'delegates', value: item.subagents.length });
  }
  return stats;
}

function buildExpanded(item: AgentSpecDTO) {
  const rows: Array<[string, string]> = [];
  if (item.skill_refs && item.skill_refs.length > 0) {
    rows.push(['skill_refs', item.skill_refs.join(', ')]);
  }
  if (item.mcp_refs && item.mcp_refs.length > 0) {
    rows.push(['mcp_refs', item.mcp_refs.join(', ')]);
  }
  if (item.subagents && item.subagents.length > 0) {
    rows.push(['subagents', item.subagents.map((s) => `${s.name ?? '?'} (${s.model_ref ?? '?'})`).join(', ')]);
  }
  if (item.interrupt_on && item.interrupt_on.length > 0) {
    rows.push(['interrupt_on', item.interrupt_on.join(', ')]);
  }
  if (item.sandbox_ref) {
    rows.push(['sandbox_ref', item.sandbox_ref]);
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

export default function AgentsPage() {
  const navigate = useNavigate();
  const params = useParams<{ agentName?: string }>();
  const createMatch = useMatch('/registry/agents/new');
  const [pageNumber, setPageNumber] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const query = useSWR(['agents', pageNumber, pageSize], () => controlClient.agents.list({ pageSize, pageNumber }));
  const editor = createMatch
    ? { mode: 'create' as const, agentName: undefined }
    : params.agentName
      ? { mode: 'edit' as const, agentName: params.agentName }
      : null;

  async function handleDelete(agentName: string) {
    try {
      await controlClient.agents.delete(agentName);
      Message.success(`agent ${agentName} deleted`);
      await query.mutate();
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'failed to delete agent');
    }
  }

  return (
    <>
      <RegistryResourcePage
        title='Agents'
        description='Manage authored agent specs and jump into editing or chat.'
        resourceType={RESOURCE_TYPE}
        actions={
          <Button type='primary' onClick={() => void navigate(links.buildAgent())}>
            Create Agent
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
        items={(query.data?.agents ?? []).map((item, index) => ({
          key: item.name ?? `agent-${pageNumber}-${index}`,
          name: item.name ?? 'unnamed-agent',
          description: item.description,
          status: item.status,
          updatedAt: item.updated_at,
          tags: item.tags,
          subtitle: item.model_ref ? `${item.model_ref}` : undefined,
          stats: buildStats(item),
          expandedContent: buildExpanded(item),
          details: [
            { label: 'model_ref', value: item.model_ref ?? 'n/a' },
            { label: 'skills', value: String(item.skill_refs?.length ?? 0) },
            { label: 'mcps', value: String(item.mcp_refs?.length ?? 0) },
            { label: 'sandbox_ref', value: item.sandbox_ref ?? 'n/a' },
          ],
          actions: (
            <>
              <Button
                onClick={() => {
                  if (!item.name) {
                    Message.warning('agent name is empty');
                    return;
                  }
                  void navigate(links.buildAgentEdit(item.name));
                }}
              >
                Edit
              </Button>
              <Button
                type='primary'
                onClick={() => {
                  if (!item.name) {
                    Message.warning('agent name is empty');
                    return;
                  }
                  void navigate(links.chatAgent(item.name));
                }}
              >
                Chat
              </Button>
              {item.name ? (
                <Popconfirm
                  title={`Delete agent ${item.name}?`}
                  content='This removes the authored spec from the registry.'
                  onOk={() => void handleDelete(item.name!)}
                >
                  <Button status='danger'>Delete</Button>
                </Popconfirm>
              ) : null}
            </>
          ),
        }))}
      />
      <AgentEditorDrawer
        visible={editor !== null}
        mode={editor?.mode ?? 'create'}
        agentName={editor?.agentName}
        onClose={() => void navigate(links.agents(), { replace: true })}
        onSaved={async () => {
          await query.mutate();
        }}
      />
    </>
  );
}
