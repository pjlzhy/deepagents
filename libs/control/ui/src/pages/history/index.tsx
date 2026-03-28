import { Delete, PreviewOpen } from '@icon-park/react';
import { Button, Card, Empty, Message, Popconfirm, Select, Space, Spin, Typography } from '@arco-design/web-react';
import useSWR from 'swr';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { links } from '@/app/links';
import { controlClient } from '@/shared/api/controlClient';
import PageHeader from '@/shared/ui/PageHeader';

export default function HistoryPage() {
  const navigate = useNavigate();
  const [agentName, setAgentName] = useState<string | undefined>(undefined);
  const [pageToken, setPageToken] = useState<string | undefined>(undefined);
  const [tokenHistory, setTokenHistory] = useState<string[]>([]);

  const agentsQuery = useSWR('history-agent-options', () => controlClient.agents.list({ pageSize: 100, pageNumber: 1 }));
  const sessionsQuery = useSWR(['history-sessions', agentName, pageToken], () =>
    controlClient.sessions.list({ agentName, pageSize: 20, pageToken }),
  );

  const agentOptions = useMemo(
    () => (agentsQuery.data?.agents ?? []).map((item) => ({ label: item.name ?? 'unnamed-agent', value: item.name ?? '' })),
    [agentsQuery.data?.agents],
  );

  return (
    <div>
      <PageHeader
        title='History'
        description='Search, inspect, and reopen existing sessions without duplicating the main chat workflow.'
        actions={
          <Select
            allowClear
            placeholder='Filter by agent'
            className='min-w-220px'
            options={agentOptions}
            value={agentName}
            onChange={(value) => {
              setAgentName(typeof value === 'string' && value ? value : undefined);
              setPageToken(undefined);
              setTokenHistory([]);
            }}
          />
        }
      />
      <Spin loading={sessionsQuery.isLoading}>
        {(sessionsQuery.data?.sessions?.length ?? 0) === 0 ? (
          <Card className='control-card'>
            <Empty description='No sessions found.' />
          </Card>
        ) : (
          <div className='grid grid-cols-1 gap-18px xl:grid-cols-2'>
            {(sessionsQuery.data?.sessions ?? []).map((item) => (
              <Card key={`${item.agent_name}-${item.thread_id}`} className='control-card'>
                <div className='mb-10px flex items-start justify-between gap-12px'>
                  <div>
                    <Typography.Title heading={5} className='!mb-6px !mt-0'>
                      {item.agent_name ?? 'unknown-agent'}
                    </Typography.Title>
                    <Typography.Text className='block text-[var(--control-subtle)]'>{item.thread_id}</Typography.Text>
                  </div>
                  <Typography.Text className='text-[var(--control-subtle)]'>{item.updated_at ?? 'n/a'}</Typography.Text>
                </div>
                <Space direction='vertical' size='small' className='w-full'>
                  <div className='flex items-center justify-between gap-12px'>
                    <Typography.Text className='text-[var(--control-subtle)]'>message_count</Typography.Text>
                    <Typography.Text>{item.message_count ?? 0}</Typography.Text>
                  </div>
                  <div className='flex items-center justify-between gap-12px'>
                    <Typography.Text className='text-[var(--control-subtle)]'>checkpoint_count</Typography.Text>
                    <Typography.Text>{item.checkpoint_count ?? 0}</Typography.Text>
                  </div>
                  <div className='flex items-center justify-between gap-12px'>
                    <Typography.Text className='text-[var(--control-subtle)]'>history_mode</Typography.Text>
                    <Typography.Text>{item.history_mode ?? 'resume_view'}</Typography.Text>
                  </div>
                </Space>
                <div className='mt-16px flex flex-wrap justify-end gap-10px'>
                  <Button
                    icon={<PreviewOpen theme='outline' size='16' fill='currentColor' />}
                    onClick={() => {
                      if (!item.agent_name || !item.thread_id) {
                        return;
                      }
                      void navigate(links.chatThread(item.agent_name, item.thread_id));
                    }}
                  >
                    Open
                  </Button>
                  <Popconfirm
                    title='Delete this session?'
                    onOk={async () => {
                      if (!item.agent_name || !item.thread_id) {
                        return;
                      }
                      try {
                        await controlClient.sessions.delete(item.agent_name, item.thread_id);
                        Message.success('session deleted');
                        await sessionsQuery.mutate();
                      } catch (error) {
                        Message.error(error instanceof Error ? error.message : 'failed to delete session');
                      }
                    }}
                  >
                    <Button status='danger' icon={<Delete theme='outline' size='16' fill='currentColor' />}>
                      Delete
                    </Button>
                  </Popconfirm>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Spin>
      <div className='mt-18px flex justify-end gap-12px'>
        <Button
          disabled={tokenHistory.length === 0}
          onClick={() => {
            if (tokenHistory.length === 0) {
              return;
            }
            const history = [...tokenHistory];
            const previousToken = history.pop();
            setTokenHistory(history);
            setPageToken(previousToken);
          }}
        >
          Previous
        </Button>
        <Button
          type='primary'
          disabled={!sessionsQuery.data?.next_page_token}
          onClick={() => {
            if (!sessionsQuery.data?.next_page_token) {
              return;
            }
            setTokenHistory((previous) => [...previous, pageToken ?? '']);
            setPageToken(sessionsQuery.data.next_page_token);
          }}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
