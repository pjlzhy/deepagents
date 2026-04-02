import { DocDetail, HistoryQuery, PlayOne, RobotOne } from '@icon-park/react';
import { Button, Card, Space, Spin, Tag, Typography } from '@arco-design/web-react';
import useSWR from 'swr';
import { useNavigate } from 'react-router-dom';
import { links } from '@/app/links';
import { controlClient } from '@/shared/api/controlClient';

function StatCard(props: { title: string; value: string | number; color?: string }) {
  return (
    <Card className='control-card control-glow-hover flex flex-col items-center py-20px'>
      <Typography.Text className='text-32px font-bold' style={{ color: props.color ?? 'var(--control-primary)' }}>
        {props.value}
      </Typography.Text>
      <Typography.Text className='mt-4px text-13px text-[var(--control-subtle)]'>{props.title}</Typography.Text>
    </Card>
  );
}

export default function OverviewPage() {
  const navigate = useNavigate();
  const healthQuery = useSWR('health', () => controlClient.health.get());
  const countsQuery = useSWR('overview-counts', async () => {
    const [models, skills, mcps, agents] = await Promise.all([
      controlClient.models.list({ pageSize: 1, pageNumber: 1 }),
      controlClient.skills.list({ pageSize: 1, pageNumber: 1 }),
      controlClient.mcps.list({ pageSize: 1, pageNumber: 1 }),
      controlClient.agents.list({ pageSize: 1, pageNumber: 1 }),
    ]);
    return {
      models: models.total_size ?? models.models.length,
      skills: skills.total_size ?? skills.skills.length,
      mcps: mcps.total_size ?? mcps.mcps.length,
      agents: agents.total_size ?? agents.agents.length,
    };
  });
  const latestSessionQuery = useSWR('latest-session', () => controlClient.sessions.getLatest());

  const ready = healthQuery.data?.ready;
  const uptime = Math.round(healthQuery.data?.uptime_seconds ?? 0);

  return (
    <Spin loading={healthQuery.isLoading || countsQuery.isLoading}>
      <div className='flex flex-col gap-18px'>
        {/* Header row: status + uptime */}
        <div className='flex items-center justify-between'>
          <div className='flex items-center gap-12px'>
            <Typography.Title heading={3} className='!mb-0 !mt-0 !text-[var(--control-text)]'>
              Overview
            </Typography.Title>
            <Tag size='small' color={ready ? 'green' : 'orange'}>{ready ? 'ready' : 'not ready'}</Tag>
            <Typography.Text className='text-13px text-[var(--control-subtle)]'>
              uptime {uptime}s
            </Typography.Text>
          </div>
          <Space>
            <Button
              type='secondary'
              size='small'
              icon={<HistoryQuery theme='outline' size='14' fill='currentColor' />}
              onClick={() => void navigate(links.history())}
            >
              History
            </Button>
            <Button
              type='primary'
              size='small'
              icon={<RobotOne theme='outline' size='14' fill='currentColor' />}
              onClick={() => void navigate(links.chatRoot())}
            >
              Chat
            </Button>
          </Space>
        </div>

        {/* Registry counts */}
        <div className='grid grid-cols-2 gap-14px lg:grid-cols-4'>
          <StatCard title='Models' value={countsQuery.data?.models ?? 0} />
          <StatCard title='Skills' value={countsQuery.data?.skills ?? 0} />
          <StatCard title='MCPs' value={countsQuery.data?.mcps ?? 0} />
          <StatCard title='Agents' value={countsQuery.data?.agents ?? 0} />
        </div>

        <div className='grid grid-cols-1 gap-14px lg:grid-cols-2'>
          {/* Latest session */}
          <Card className='control-card'>
            <div className='flex items-start justify-between'>
              <Typography.Text className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>
                Latest Session
              </Typography.Text>
              {latestSessionQuery.data?.thread_id ? (
                <Button
                  size='mini'
                  type='primary'
                  onClick={() => {
                    const d = latestSessionQuery.data;
                    if (d?.agent_name && d.thread_id) void navigate(links.chatThread(d.agent_name, d.thread_id));
                  }}
                >
                  Resume
                </Button>
              ) : null}
            </div>
            {latestSessionQuery.data?.thread_id ? (
              <div className='mt-10px flex flex-col gap-4px'>
                <Typography.Text className='font-medium text-[var(--control-text)]'>
                  {latestSessionQuery.data.agent_name}
                </Typography.Text>
                <Typography.Text className='truncate text-12px text-[var(--control-subtle)]'>
                  {latestSessionQuery.data.thread_id}
                </Typography.Text>
                <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                  {latestSessionQuery.data.updated_at ?? ''}
                </Typography.Text>
              </div>
            ) : (
              <Typography.Text className='mt-10px block text-[var(--control-subtle)]'>
                No recoverable session
              </Typography.Text>
            )}
          </Card>

          {/* Runtime snapshot */}
          <Card className='control-card'>
            <Typography.Text className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>
              Runtime
            </Typography.Text>
            <div className='mt-10px flex flex-col gap-8px'>
              {[
                { label: 'Assembled', value: healthQuery.data?.assembled_agent_count ?? 0 },
                { label: 'Installed', value: healthQuery.data?.installed_agent_count ?? 0 },
                { label: 'Running', value: healthQuery.data?.running_agent_count ?? 0 },
              ].map((item) => (
                <div key={item.label} className='flex justify-between'>
                  <Typography.Text className='text-[var(--control-subtle)]'>{item.label}</Typography.Text>
                  <Typography.Text className='font-medium text-[var(--control-text)]'>{item.value}</Typography.Text>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Quick actions */}
        <div className='flex flex-wrap gap-10px'>
          <Button
            size='small'
            icon={<DocDetail theme='outline' size='14' fill='currentColor' />}
            onClick={() => void navigate(links.models())}
          >
            Models
          </Button>
          <Button
            size='small'
            icon={<PlayOne theme='outline' size='14' fill='currentColor' />}
            onClick={() => void navigate(links.agents())}
          >
            Agents
          </Button>
          <Button
            size='small'
            icon={<RobotOne theme='outline' size='14' fill='currentColor' />}
            onClick={() => void navigate(links.chatRoot())}
          >
            Chat Workspace
          </Button>
        </div>
      </div>
    </Spin>
  );
}
