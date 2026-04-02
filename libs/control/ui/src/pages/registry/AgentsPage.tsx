import { useState } from 'react';
import { Button, Message, Popconfirm } from '@arco-design/web-react';
import useSWR from 'swr';
import { useMatch, useNavigate, useParams } from 'react-router-dom';
import { links } from '@/app/links';
import AgentEditorDrawer from '@/features/registry/AgentEditorDrawer';
import RegistryResourcePage from '@/pages/registry/RegistryResourcePage';
import { controlClient } from '@/shared/api/controlClient';

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
        accent='#a855f7'
        actions={
          <Button type='primary' onClick={() => void navigate(links.newAgent())}>
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
                  void navigate(links.agentDetail(item.name));
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
