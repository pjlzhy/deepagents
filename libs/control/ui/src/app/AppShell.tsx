import { DataAll, HistoryQuery, RobotOne } from '@icon-park/react';
import { Layout, Menu, Tag, Typography } from '@arco-design/web-react';
import { useLocation, useNavigate } from 'react-router-dom';
import AppRouter from '@/app/router';
import { links } from '@/app/links';

function resolveSelectedKey(pathname: string): string {
  if (pathname.startsWith('/registry/models')) {
    return links.models();
  }
  if (pathname.startsWith('/registry/skills')) {
    return links.skills();
  }
  if (pathname.startsWith('/registry/mcps')) {
    return links.mcps();
  }
  if (pathname.startsWith('/registry/sandboxes')) {
    return links.sandboxes();
  }
  if (pathname.startsWith('/registry/agents')) {
    return links.agents();
  }
  if (pathname.startsWith('/chat')) {
    return links.chatRoot();
  }
  if (pathname.startsWith('/history')) {
    return links.history();
  }
  return links.overview();
}

export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const selectedKey = resolveSelectedKey(location.pathname);

  return (
    <Layout className='h-screen overflow-hidden bg-transparent'>
      <Layout.Sider
        width={256}
        className='m-18px mr-0 flex flex-col overflow-hidden rd-24px border border-solid border-[var(--control-border)] bg-[var(--control-panel)] shadow-[var(--control-shadow)]'
      >
        <div className='px-18px py-18px'>
          <div className='control-muted-card p-14px'>
            {/*<Typography.Text className='block text-12px uppercase tracking-[0.28em] text-[var(--control-subtle)]'>*/}
            {/*  DeepAgents*/}
            {/*</Typography.Text>*/}
            <Typography.Title heading={4} className='!mb-6px !mt-8px !text-[var(--control-text)]'>
              agents control
            </Typography.Title>
            {/*<Typography.Text className='text-[var(--control-subtle)]'>*/}
            {/*  基于 AionUi renderer 风格构建的 control plane 控制台*/}
            {/*</Typography.Text>*/}
          </div>
        </div>
        <Menu
          selectedKeys={[selectedKey]}
          defaultOpenKeys={['registry']}
          className='border-none bg-transparent px-10px'
          onClickMenuItem={(key) => {
            void navigate(key);
          }}
        >
          <Menu.Item key={links.overview()}>
            <div className='flex items-center gap-10px'>
              <DataAll theme='outline' size='18' fill='var(--control-text)' />
              <span>概览</span>
            </div>
          </Menu.Item>
          <Menu.SubMenu
            key='registry'
            title={
              <div className='flex items-center gap-10px'>
                <DataAll theme='outline' size='18' fill='var(--control-text)' />
                <span>Registry</span>
              </div>
            }
          >
            <Menu.Item key={links.models()}>Models</Menu.Item>
            <Menu.Item key={links.skills()}>Skills</Menu.Item>
            <Menu.Item key={links.mcps()}>MCPs</Menu.Item>
            <Menu.Item key={links.sandboxes()}>Sandboxes</Menu.Item>
            <Menu.Item key={links.agents()}>Agents</Menu.Item>
          </Menu.SubMenu>
          <Menu.Item key={links.chatRoot()}>
            <div className='flex items-center gap-10px'>
              <RobotOne theme='outline' size='18' fill='var(--control-text)' />
              <span>Chat Workspace</span>
            </div>
          </Menu.Item>
          <Menu.Item key={links.history()}>
            <div className='flex items-center gap-10px'>
              <HistoryQuery theme='outline' size='18' fill='var(--control-text)' />
              <span>History</span>
            </div>
          </Menu.Item>
        </Menu>
        <div className='mt-auto px-18px py-16px'>
          <div className='control-muted-card flex items-center justify-between px-14px py-12px'>
            <div className='flex flex-col gap-2px'>
              <Typography.Text className='text-12px text-[var(--control-subtle)]'>southbound</Typography.Text>
              <Typography.Text className='text-[var(--control-text)]'>single default_target</Typography.Text>
            </div>
            <Tag color='arcoblue'>runtime</Tag>
          </div>
        </div>
      </Layout.Sider>
      <Layout className='min-h-0 flex-1 bg-transparent'>
        <Layout.Content className='m-18px flex min-h-0 flex-1 flex-col overflow-hidden rd-24px border border-solid border-[var(--control-border)] bg-[var(--control-panel)] p-24px shadow-[var(--control-shadow)]'>
          <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
            <AppRouter />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
