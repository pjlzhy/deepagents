import { DataAll, HamburgerButton, HistoryQuery, RobotOne } from '@icon-park/react';
import { Button, Layout, Menu, Tag, Typography } from '@arco-design/web-react';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import AppRouter from '@/app/router';
import { links } from '@/app/links';

function resolveSelectedKey(pathname: string): string {
  if (pathname.startsWith('/registry/models')) return links.models();
  if (pathname.startsWith('/registry/skills')) return links.skills();
  if (pathname.startsWith('/registry/mcps')) return links.mcps();
  if (pathname.startsWith('/registry/sandboxes')) return links.sandboxes();
  if (pathname.startsWith('/registry/agents')) return links.agents();
  if (pathname.startsWith('/chat')) return links.chatRoot();
  if (pathname.startsWith('/history')) return links.history();
  return links.overview();
}

export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const selectedKey = resolveSelectedKey(location.pathname);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <Layout className='h-screen overflow-hidden bg-transparent'>
      <Layout.Sider
        width={256}
        collapsedWidth={56}
        collapsed={collapsed}
        className='m-18px mr-0 flex flex-col overflow-hidden rd-24px border border-solid border-[var(--control-border)] bg-[var(--control-panel)] shadow-[var(--control-shadow)] transition-all duration-200'
      >
        {/* Collapse toggle */}
        <div className={`flex shrink-0 items-center px-14px py-12px ${collapsed ? 'justify-center' : 'justify-between'}`}>
          {!collapsed ? (
            <Typography.Text className='text-14px font-semibold text-[var(--control-text)]'>
              agents control
            </Typography.Text>
          ) : null}
          <Button
            type='text'
            size='small'
            className='control-quiet-icon-button'
            icon={<HamburgerButton theme='outline' size='18' fill='var(--control-subtle)' />}
            onClick={() => setCollapsed((prev) => !prev)}
          />
        </div>

        <Menu
          selectedKeys={[selectedKey]}
          defaultOpenKeys={collapsed ? [] : ['registry']}
          collapse={collapsed}
          className='border-none bg-transparent px-10px'
          onClickMenuItem={(key) => { void navigate(key); }}
        >
          <Menu.Item key={links.overview()}>
            <DataAll theme='outline' size='18' fill='var(--control-text)' />
            <span>概览</span>
          </Menu.Item>
          <Menu.SubMenu
            key='registry'
            title={
              <>
                <DataAll theme='outline' size='18' fill='var(--control-text)' />
                <span>Registry</span>
              </>
            }
          >
            <Menu.Item key={links.models()}>Models</Menu.Item>
            <Menu.Item key={links.skills()}>Skills</Menu.Item>
            <Menu.Item key={links.mcps()}>MCPs</Menu.Item>
            <Menu.Item key={links.sandboxes()}>Sandboxes</Menu.Item>
            <Menu.Item key={links.agents()}>Agents</Menu.Item>
          </Menu.SubMenu>
          <Menu.Item key={links.chatRoot()}>
            <RobotOne theme='outline' size='18' fill='var(--control-text)' />
            <span>Chat Workspace</span>
          </Menu.Item>
          <Menu.Item key={links.history()}>
            <HistoryQuery theme='outline' size='18' fill='var(--control-text)' />
            <span>History</span>
          </Menu.Item>
        </Menu>

        {!collapsed ? (
          <div className='mt-auto px-14px py-14px'>
            <div className='control-muted-card flex items-center justify-between px-12px py-10px'>
              <div className='flex flex-col gap-2px'>
                <Typography.Text className='text-12px text-[var(--control-subtle)]'>southbound</Typography.Text>
                <Typography.Text className='text-[var(--control-text)]'>single default_target</Typography.Text>
              </div>
              <Tag color='arcoblue'>runtime</Tag>
            </div>
          </div>
        ) : null}
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
