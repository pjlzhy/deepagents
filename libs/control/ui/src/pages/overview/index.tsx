import {
  Brain,
  Lightning,
  PlugOne,
  RobotOne,
  PlayOne,
  Server,
  SettingConfig,
  Box,
  DataAll,
  MessageOne,
  Time,
  HardDisk,
} from '@icon-park/react';
import { Button, Spin, Typography } from '@arco-design/web-react';
import useSWR from 'swr';
import { useNavigate } from 'react-router-dom';
import { links } from '@/app/links';
import { controlClient } from '@/shared/api/controlClient';
import '@/styles/registry-cards.css';

const CYAN = '#00f0ff';
const GREEN = '#39ff14';
const MAGENTA = '#ff2d95';
const ORANGE = '#ff9f1a';

/* ── Helpers ── */

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function formatRelativeTime(value?: string): string {
  if (!value) return '';
  try {
    const d = new Date(value);
    const diff = Date.now() - d.getTime();
    if (diff < 60_000) return 'just now';
    if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`;
    return `${Math.floor(diff / 86400_000)}d ago`;
  } catch {
    return '';
  }
}

function truncate(value?: string, max = 40): string {
  if (!value) return '';
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

/* ── Sub-components ── */

type StatCardProps = {
  icon: React.ReactNode;
  title: string;
  value: string | number;
  accent?: string;
  glow?: string;
  onClick?: () => void;
};

function StatCard({ icon, title, value, accent = CYAN, glow = 'rgba(0,240,255,0.15)', onClick }: StatCardProps) {
  return (
    <div
      className='registry-card control-card cursor-pointer flex flex-col items-center gap-8px py-24px px-16px'
      style={{ '--card-accent': accent, '--card-glow': glow } as React.CSSProperties}
      onClick={onClick}
    >
      <div
        className='registry-card-icon-zone registry-card-icon'
        style={{ background: `${accent}10`, color: accent }}
      >
        {icon}
      </div>
      <Typography.Text className='text-32px font-bold' style={{ color: accent }}>
        {value}
      </Typography.Text>
      <Typography.Text className='text-13px text-[var(--control-subtle)]'>{title}</Typography.Text>
    </div>
  );
}

function SectionCard({
  icon,
  chip,
  chipColor,
  action,
  children,
}: {
  icon: React.ReactNode;
  chip: string;
  chipColor?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  const color = chipColor ?? CYAN;
  return (
    <div className='control-card overflow-hidden'>
      <div
        className='flex items-center gap-10px px-16px py-10px border-b border-solid border-[var(--control-border)]'
        style={{ background: `${color}08` }}
      >
        {icon}
        <span
          className='rd-full px-8px py-1px text-10px font-bold tracking-wider uppercase border border-solid'
          style={{ color, borderColor: `${color}40`, background: `${color}0a` }}
        >
          {chip}
        </span>
        {action ? <div className='ml-auto'>{action}</div> : null}
      </div>
      <div className='px-16px py-14px'>{children}</div>
    </div>
  );
}

/* ── Main ── */

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
  const recentAgentsQuery = useSWR('overview-recent-agents', () =>
    controlClient.agents.list({ pageSize: 4, pageNumber: 1 }),
  );
  const recentSessionsQuery = useSWR('overview-recent-sessions', () =>
    controlClient.sessions.list({ pageSize: 5 }),
  );
  const recentModelsQuery = useSWR('overview-recent-models', () =>
    controlClient.models.list({ pageSize: 4, pageNumber: 1 }),
  );

  const ready = healthQuery.data?.ready;
  const uptime = Math.round(healthQuery.data?.uptime_seconds ?? 0);

  return (
    <Spin loading={healthQuery.isLoading || countsQuery.isLoading}>
      <div className='flex flex-col gap-20px'>
        {/* Hero header */}
        <div className='flex items-center justify-between'>
          <div className='flex items-center gap-14px'>
            <div className='registry-card-icon' style={{ background: 'rgba(0,240,255,0.08)', color: CYAN }}>
              <DataAll size={22} fill={[CYAN]} />
            </div>
            <div>
              <Typography.Title heading={3} className='!mb-2px !mt-0 !text-[var(--control-text)]'>
                Overview
              </Typography.Title>
              <div className='flex items-center gap-8px'>
                <span className='flex items-center gap-6px text-12px text-[var(--control-subtle)]'>
                  <span
                    className={`inline-block w-7px h-7px rd-full ${ready ? 'registry-status-dot--published bg-[#39ff14]' : 'bg-[var(--control-warning)]'}`}
                  />
                  {ready ? 'ready' : 'not ready'}
                </span>
                <span className='text-12px text-[var(--control-subtle)]'>uptime {formatUptime(uptime)}</span>
              </div>
            </div>
          </div>
          <Button
            type='primary'
            size='small'
            icon={<RobotOne theme='outline' size='14' fill='currentColor' />}
            onClick={() => void navigate(links.chatRoot())}
          >
            Chat
          </Button>
        </div>

        {/* Registry counts */}
        <div className='grid grid-cols-2 gap-14px lg:grid-cols-4'>
          <StatCard
            icon={<Brain size={22} fill={[CYAN]} />}
            title='Models'
            value={countsQuery.data?.models ?? 0}
            onClick={() => void navigate(links.models())}
          />
          <StatCard
            icon={<Lightning size={22} fill={[GREEN]} />}
            title='Skills'
            value={countsQuery.data?.skills ?? 0}
            accent={GREEN}
            glow='rgba(57,255,20,0.15)'
            onClick={() => void navigate(links.skills())}
          />
          <StatCard
            icon={<PlugOne size={22} fill={[ORANGE]} />}
            title='MCPs'
            value={countsQuery.data?.mcps ?? 0}
            accent={ORANGE}
            glow='rgba(255,159,26,0.15)'
            onClick={() => void navigate(links.mcps())}
          />
          <StatCard
            icon={<RobotOne size={22} fill={[MAGENTA]} />}
            title='Agents'
            value={countsQuery.data?.agents ?? 0}
            accent={MAGENTA}
            glow='rgba(255,45,149,0.15)'
            onClick={() => void navigate(links.agents())}
          />
        </div>

        {/* Row 2: Latest session + Runtime */}
        <div className='grid grid-cols-1 gap-14px lg:grid-cols-2'>
          <SectionCard
            icon={<PlayOne size={16} fill={[CYAN]} />}
            chip='LATEST SESSION'
            action={
              latestSessionQuery.data?.thread_id ? (
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
              ) : null
            }
          >
            {latestSessionQuery.data?.thread_id ? (
              <div className='flex flex-col gap-4px'>
                <div className='flex items-center gap-8px'>
                  <RobotOne size={14} fill={[CYAN]} />
                  <Typography.Text className='font-semibold text-[var(--control-text)]'>
                    {latestSessionQuery.data.agent_name}
                  </Typography.Text>
                  <span className='text-11px text-[var(--control-subtle)]'>
                    {formatRelativeTime(latestSessionQuery.data.updated_at)}
                  </span>
                </div>
                <Typography.Text className='truncate text-12px text-[var(--control-subtle)] pl-22px'>
                  {latestSessionQuery.data.initial_prompt
                    ? truncate(latestSessionQuery.data.initial_prompt, 60)
                    : latestSessionQuery.data.thread_id}
                </Typography.Text>
              </div>
            ) : (
              <Typography.Text className='text-[var(--control-subtle)]'>
                No recoverable session
              </Typography.Text>
            )}
          </SectionCard>

          <SectionCard
            icon={<Server size={16} fill={[MAGENTA]} />}
            chip='RUNTIME'
            chipColor={MAGENTA}
          >
            <div className='flex flex-col gap-8px'>
              {[
                { label: 'Assembled', value: healthQuery.data?.assembled_agent_count ?? 0, icon: <SettingConfig size={14} fill={[CYAN]} /> },
                { label: 'Installed', value: healthQuery.data?.installed_agent_count ?? 0, icon: <Box size={14} fill={[GREEN]} /> },
                { label: 'Running', value: healthQuery.data?.running_agent_count ?? 0, icon: <PlayOne size={14} fill={[ORANGE]} /> },
              ].map((item) => (
                <div key={item.label} className='flex items-center justify-between'>
                  <span className='flex items-center gap-8px text-[var(--control-subtle)]'>
                    {item.icon}
                    {item.label}
                  </span>
                  <Typography.Text className='font-semibold text-[var(--control-text)]'>{item.value}</Typography.Text>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>

        {/* Row 3: Recent Agents + Recent Models */}
        <div className='grid grid-cols-1 gap-14px lg:grid-cols-2'>
          <SectionCard
            icon={<RobotOne size={16} fill={[MAGENTA]} />}
            chip='AGENTS'
            chipColor={MAGENTA}
            action={
              <Button size='mini' type='text' onClick={() => void navigate(links.agents())}>
                View All
              </Button>
            }
          >
            {(recentAgentsQuery.data?.agents ?? []).length === 0 ? (
              <Typography.Text className='text-[var(--control-subtle)]'>No agents registered</Typography.Text>
            ) : (
              <div className='flex flex-col gap-6px'>
                {(recentAgentsQuery.data?.agents ?? []).map((agent) => (
                  <div
                    key={agent.name}
                    className='flex items-center gap-10px rd-10px px-10px py-8px cursor-pointer transition-all duration-200 hover:bg-[rgba(255,45,149,0.04)]'
                    style={{ border: '1px solid transparent' }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'rgba(255,45,149,0.15)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'transparent'; }}
                    onClick={() => agent.name && void navigate(links.agentDetail(agent.name))}
                  >
                    <div
                      className='w-28px h-28px rd-8px flex-center shrink-0'
                      style={{ background: `${MAGENTA}10`, border: `1px solid ${MAGENTA}20` }}
                    >
                      <RobotOne size={14} fill={[MAGENTA]} />
                    </div>
                    <div className='min-w-0 flex-1'>
                      <div className='text-13px font-semibold text-[var(--control-text)] truncate'>
                        {agent.name}
                      </div>
                      <div className='text-11px text-[var(--control-subtle)] truncate'>
                        {agent.model_ref ?? 'no model'}{agent.skill_refs?.length ? ` · ${agent.skill_refs.length} skills` : ''}
                      </div>
                    </div>
                    {agent.status && (
                      <span className='flex items-center gap-4px text-11px text-[var(--control-subtle)] shrink-0'>
                        <span
                          className={`inline-block w-6px h-6px rd-full ${agent.status === 'published' ? 'registry-status-dot--published bg-[#39ff14]' : 'bg-[var(--control-subtle)]'}`}
                        />
                        {agent.status}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard
            icon={<Brain size={16} fill={[CYAN]} />}
            chip='MODELS'
            action={
              <Button size='mini' type='text' onClick={() => void navigate(links.models())}>
                View All
              </Button>
            }
          >
            {(recentModelsQuery.data?.models ?? []).length === 0 ? (
              <Typography.Text className='text-[var(--control-subtle)]'>No models registered</Typography.Text>
            ) : (
              <div className='flex flex-col gap-6px'>
                {(recentModelsQuery.data?.models ?? []).map((model) => (
                  <div
                    key={model.name}
                    className='flex items-center gap-10px rd-10px px-10px py-8px transition-all duration-200 hover:bg-[rgba(0,240,255,0.04)]'
                    style={{ border: '1px solid transparent' }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'rgba(0,240,255,0.15)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'transparent'; }}
                  >
                    <div
                      className='w-28px h-28px rd-8px flex-center shrink-0'
                      style={{ background: `${CYAN}10`, border: `1px solid ${CYAN}20` }}
                    >
                      <Brain size={14} fill={[CYAN]} />
                    </div>
                    <div className='min-w-0 flex-1'>
                      <div className='text-13px font-semibold text-[var(--control-text)] truncate'>
                        {model.name}
                      </div>
                      <div className='text-11px text-[var(--control-subtle)] truncate'>
                        {[model.provider, model.model].filter(Boolean).join(' / ') || 'no provider'}
                      </div>
                    </div>
                    {model.base_url && (
                      <span
                        className='rd-full px-6px py-1px text-10px font-mono border border-solid shrink-0'
                        style={{ color: CYAN, borderColor: `${CYAN}25`, background: `${CYAN}08` }}
                      >
                        custom
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </div>

        {/* Row 4: Recent Sessions */}
        <SectionCard
          icon={<MessageOne size={16} fill={[GREEN]} />}
          chip='RECENT SESSIONS'
          chipColor={GREEN}
          action={
            <Button size='mini' type='text' onClick={() => void navigate(links.chatRoot())}>
              Open Chat
            </Button>
          }
        >
          {(recentSessionsQuery.data?.sessions ?? []).length === 0 ? (
            <Typography.Text className='text-[var(--control-subtle)]'>No sessions yet</Typography.Text>
          ) : (
            <div className='grid grid-cols-1 gap-6px lg:grid-cols-2 xl:grid-cols-3'>
              {(recentSessionsQuery.data?.sessions ?? []).slice(0, 6).map((session) => (
                <div
                  key={session.thread_id}
                  className='flex items-center gap-10px rd-10px px-10px py-8px cursor-pointer transition-all duration-200 hover:bg-[rgba(57,255,20,0.04)]'
                  style={{ border: '1px solid transparent' }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'rgba(57,255,20,0.15)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'transparent'; }}
                  onClick={() => {
                    if (session.agent_name && session.thread_id) {
                      void navigate(links.chatThread(session.agent_name, session.thread_id));
                    }
                  }}
                >
                  <div
                    className='w-28px h-28px rd-8px flex-center shrink-0'
                    style={{ background: `${GREEN}10`, border: `1px solid ${GREEN}20` }}
                  >
                    <MessageOne size={14} fill={[GREEN]} />
                  </div>
                  <div className='min-w-0 flex-1'>
                    <div className='text-13px font-semibold text-[var(--control-text)] truncate'>
                      {session.agent_name ?? 'unknown'}
                    </div>
                    <div className='text-11px text-[var(--control-subtle)] truncate'>
                      {session.initial_prompt ? truncate(session.initial_prompt, 36) : session.thread_id}
                    </div>
                  </div>
                  <div className='flex flex-col items-end gap-2px shrink-0'>
                    <span className='text-11px text-[var(--control-subtle)]'>
                      {formatRelativeTime(session.updated_at)}
                    </span>
                    {session.message_count != null && (
                      <span className='text-10px text-[var(--control-subtle)]'>
                        {session.message_count} msgs
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        {/* Quick nav — compact */}
        <div className='flex items-center gap-8px'>
          <HardDisk size={14} fill={['var(--control-subtle)']} />
          <span className='text-11px text-[var(--control-subtle)] uppercase tracking-wider font-bold'>Quick Nav</span>
          <div className='flex-1 h-1px bg-[var(--control-border)]' />
          {[
            { label: 'Models', link: links.models(), icon: <Brain size={12} fill={[CYAN]} /> },
            { label: 'Skills', link: links.skills(), icon: <Lightning size={12} fill={[GREEN]} /> },
            { label: 'MCPs', link: links.mcps(), icon: <PlugOne size={12} fill={[ORANGE]} /> },
            { label: 'Sandboxes', link: links.sandboxes(), icon: <Server size={12} fill={[MAGENTA]} /> },
            { label: 'Agents', link: links.agents(), icon: <RobotOne size={12} fill={[MAGENTA]} /> },
            { label: 'Chat', link: links.chatRoot(), icon: <MessageOne size={12} fill={[GREEN]} /> },
          ].map((item) => (
            <Button
              key={item.label}
              size='mini'
              type='text'
              icon={item.icon}
              className='!text-11px'
              onClick={() => void navigate(item.link)}
            >
              {item.label}
            </Button>
          ))}
        </div>
      </div>
    </Spin>
  );
}
