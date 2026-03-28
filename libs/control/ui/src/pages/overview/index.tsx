import { DocDetail, HistoryQuery, PlayOne, RobotOne } from '@icon-park/react';
import { Button, Card, Grid, List, Space, Spin, Statistic, Tag, Typography } from '@arco-design/web-react';
import useSWR from 'swr';
import { useNavigate } from 'react-router-dom';
import { links } from '@/app/links';
import { controlClient } from '@/shared/api/controlClient';
import PageHeader from '@/shared/ui/PageHeader';

const { Row, Col } = Grid;

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

  return (
    <div>
      <PageHeader
        title='Overview'
        description='A compact entry point for health status, registry inventory, and the latest recoverable session.'
        actions={
          <>
            <Button
              type='secondary'
              icon={<HistoryQuery theme='outline' size='16' fill='currentColor' />}
              onClick={() => void navigate(links.history())}
            >
              Open History
            </Button>
            <Button
              type='primary'
              icon={<RobotOne theme='outline' size='16' fill='currentColor' />}
              onClick={() => void navigate(links.chatRoot())}
            >
              Open Chat
            </Button>
          </>
        }
      />
      <Spin loading={healthQuery.isLoading || countsQuery.isLoading}>
        <Row gutter={[18, 18]}>
          <Col xs={24} lg={8}>
            <Card className='control-card h-full'>
              <Statistic
                title='Service Status'
                value={healthQuery.data?.status ?? 'unknown'}
                extra={
                  <Space wrap>
                    <Tag color={healthQuery.data?.ready ? 'green' : 'orange'}>
                      {healthQuery.data?.ready ? 'ready' : 'not ready'}
                    </Tag>
                    <Typography.Text className='text-[var(--control-subtle)]'>
                      uptime {Math.round(healthQuery.data?.uptime_seconds ?? 0)}s
                    </Typography.Text>
                  </Space>
                }
              />
            </Card>
          </Col>
          <Col xs={12} lg={4}>
            <Card className='control-card h-full'>
              <Statistic title='Models' value={countsQuery.data?.models ?? 0} />
            </Card>
          </Col>
          <Col xs={12} lg={4}>
            <Card className='control-card h-full'>
              <Statistic title='Skills' value={countsQuery.data?.skills ?? 0} />
            </Card>
          </Col>
          <Col xs={12} lg={4}>
            <Card className='control-card h-full'>
              <Statistic title='MCPs' value={countsQuery.data?.mcps ?? 0} />
            </Card>
          </Col>
          <Col xs={12} lg={4}>
            <Card className='control-card h-full'>
              <Statistic title='Agents' value={countsQuery.data?.agents ?? 0} />
            </Card>
          </Col>
        </Row>

        <Row gutter={[18, 18]} className='mt-18px'>
          <Col xs={24} lg={14}>
            <Card className='control-card h-full'>
              <Typography.Title heading={5} className='!mt-0'>
                Quick Actions
              </Typography.Title>
              <Space wrap size='large'>
                <Button
                  icon={<DocDetail theme='outline' size='16' fill='currentColor' />}
                  onClick={() => void navigate(links.models())}
                >
                  Browse Models
                </Button>
                <Button
                  icon={<PlayOne theme='outline' size='16' fill='currentColor' />}
                  onClick={() => void navigate(links.agents())}
                >
                  Browse Agents
                </Button>
                <Button
                  icon={<RobotOne theme='outline' size='16' fill='currentColor' />}
                  onClick={() => void navigate(links.chatRoot())}
                >
                  Open Chat Workspace
                </Button>
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card className='control-card h-full'>
              <Typography.Title heading={5} className='!mt-0'>
                Latest Session
              </Typography.Title>
              {latestSessionQuery.data?.thread_id ? (
                <div className='flex flex-col gap-8px'>
                  <Typography.Text className='text-[var(--control-text)]'>
                    {latestSessionQuery.data.agent_name} / {latestSessionQuery.data.thread_id}
                  </Typography.Text>
                  <Typography.Text className='text-[var(--control-subtle)]'>
                    {latestSessionQuery.data.updated_at ?? 'no updated_at'}
                  </Typography.Text>
                  <Button
                    type='primary'
                    onClick={() => {
                      if (!latestSessionQuery.data?.agent_name || !latestSessionQuery.data.thread_id) {
                        return;
                      }
                      void navigate(links.chatThread(latestSessionQuery.data.agent_name, latestSessionQuery.data.thread_id));
                    }}
                  >
                    Resume Session
                  </Button>
                </div>
              ) : (
                <Typography.Text className='text-[var(--control-subtle)]'>
                  No recoverable session is available yet.
                </Typography.Text>
              )}
            </Card>
          </Col>
        </Row>

        <Card className='control-card mt-18px'>
          <Typography.Title heading={5} className='!mt-0'>
            Runtime Snapshot
          </Typography.Title>
          <List
            dataSource={[
              `assembled_agent_count = ${healthQuery.data?.assembled_agent_count ?? 0}`,
              `installed_agent_count = ${healthQuery.data?.installed_agent_count ?? 0}`,
              `running_agent_count = ${healthQuery.data?.running_agent_count ?? 0}`,
            ]}
            render={(item) => (
              <List.Item>
                <Typography.Text>{item}</Typography.Text>
              </List.Item>
            )}
          />
        </Card>
      </Spin>
    </div>
  );
}
