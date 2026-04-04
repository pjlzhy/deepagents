import { DataAll, HamburgerButton, RobotOne, Server } from '@icon-park/react';
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
  if (pathname.startsWith('/registry/agents/build')) return links.agents();
  if (pathname.startsWith('/registry/agents')) return links.agents();
  if (pathname.startsWith('/chat')) return links.chatRoot();
  if (pathname.startsWith('/telemetry')) return links.telemetryRoot();
  return links.overview();
}

function NavIcon(props: { icon: React.ReactNode; label: string }) {
  return (
    <div className='flex items-center gap-8px'>
      {props.icon}
      <span>{props.label}</span>
    </div>
  );
}

export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const selectedKey = resolveSelectedKey(location.pathname);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <Layout className='h-screen overflow-hidden bg-transparent'>
      <Layout.Sider
        width={200}
        collapsedWidth={52}
        collapsed={collapsed}
        className='m-14px mr-0 flex flex-col overflow-hidden rd-20px border border-solid border-[var(--control-border)] bg-[var(--control-panel)] shadow-[var(--control-shadow)] transition-all duration-200'
      >
        {/* Collapse toggle */}
        <div className={`flex shrink-0 items-center px-12px py-10px ${collapsed ? 'justify-center' : 'justify-between'}`}>
          {!collapsed ? (
            <Typography.Text className='text-13px font-semibold text-[var(--control-text)]'>
              agents control
            </Typography.Text>
          ) : null}
          <Button
            type='text'
            size='mini'
            className='control-quiet-icon-button'
            icon={<HamburgerButton theme='outline' size='16' fill='var(--control-subtle)' />}
            onClick={() => setCollapsed((prev) => !prev)}
          />
        </div>

        <Menu
          selectedKeys={[selectedKey]}
          defaultOpenKeys={collapsed ? [] : ['registry']}
          collapse={collapsed}
          className='control-nav-menu border-none bg-transparent px-6px'
          onClickMenuItem={(key) => { void navigate(key); }}
        >
          <Menu.Item key={links.overview()}>
            <NavIcon icon={<DataAll theme='outline' size='16' fill='currentColor' />} label='概览' />
          </Menu.Item>
          <Menu.SubMenu
            key='registry'
            title={<NavIcon icon={<DataAll theme='outline' size='16' fill='currentColor' />} label='Registry' />}
          >
            <Menu.Item key={links.models()}>Models</Menu.Item>
            <Menu.Item key={links.skills()}>Skills</Menu.Item>
            <Menu.Item key={links.mcps()}>MCPs</Menu.Item>
            <Menu.Item key={links.sandboxes()}>Sandboxes</Menu.Item>
            <Menu.Item key={links.agents()}>Agents</Menu.Item>
          </Menu.SubMenu>
          <Menu.Item key={links.chatRoot()}>
            <NavIcon icon={<RobotOne theme='outline' size='16' fill='currentColor' />} label='Chat' />
          </Menu.Item>
          <Menu.Item key={links.telemetryRoot()}>
            <NavIcon icon={<Server theme='outline' size='16' fill='currentColor' />} label='Telemetry' />
          </Menu.Item>
        </Menu>

        {!collapsed ? (
          <div className='mt-auto px-10px py-10px'>
            <div className='control-muted-card flex items-center justify-between px-10px py-8px'>
              <div className='flex flex-col gap-1px'>
                <Typography.Text className='text-11px text-[var(--control-subtle)]'>southbound</Typography.Text>
                <Typography.Text className='text-12px text-[var(--control-text)]'>default_target</Typography.Text>
              </div>
              <Tag size='small' color='arcoblue'>rt</Tag>
            </div>
          </div>
        ) : null}
      </Layout.Sider>
      <Layout className='min-h-0 flex-1 bg-transparent'>
        <Layout.Content className='m-14px flex min-h-0 flex-1 flex-col overflow-hidden rd-20px border border-solid border-[var(--control-border)] bg-[var(--control-panel)] p-20px shadow-[var(--control-shadow)]'>
          <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
            <AppRouter />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
