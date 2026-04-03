import { useState } from 'react';
import useSWR from 'swr';
import { DownloadOne, Close, Code, FileText, FolderOne } from '@icon-park/react';
import { Button, Message, Spin, Typography } from '@arco-design/web-react';
import { controlClient } from '@/shared/api/controlClient';
import type { ThreadArtifactDTO, WorkspaceFileInfoDTO } from '@/shared/types/api';

const CYAN = '#00f0ff';
const GREEN = '#39ff14';

const LANGUAGE_COLORS: Record<string, string> = {
  python: '#3572A5',
  javascript: '#f1e05a',
  typescript: '#3178c6',
  go: '#00ADD8',
  rust: '#dea584',
  java: '#b07219',
  html: '#e34c26',
  css: '#563d7c',
  markdown: '#083fa1',
  shell: '#89e051',
  sql: '#e38c00',
  json: '#292929',
  yaml: '#cb171e',
};

function langColor(lang?: string): string {
  return LANGUAGE_COLORS[lang ?? ''] ?? CYAN;
}

function extToLang(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  const map: Record<string, string> = {
    py: 'python', js: 'javascript', ts: 'typescript', tsx: 'typescript', jsx: 'javascript',
    go: 'go', rs: 'rust', java: 'java', html: 'html', css: 'css', md: 'markdown',
    sh: 'shell', sql: 'sql', json: 'json', yaml: 'yaml', yml: 'yaml', xml: 'xml',
    toml: 'toml', proto: 'protobuf', rb: 'ruby', php: 'php', c: 'c', cpp: 'cpp',
    h: 'c', hpp: 'cpp', cs: 'csharp', swift: 'swift', kt: 'kotlin', txt: '',
  };
  return map[ext] ?? '';
}

function formatRelativeTime(iso?: string): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatSize(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function downloadFile(agentName: string, threadId: string, path: string, filename: string): Promise<void> {
  const response = await controlClient.agents.downloadWorkspaceFiles(agentName, threadId, [path]);
  const file = response.files?.[0];
  if (!file || file.error) {
    throw new Error(file?.error ?? 'download failed');
  }
  if (!file.content_base64) {
    throw new Error('empty file content');
  }
  const binary = atob(file.content_base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const blob = new Blob([bytes]);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------

type ActiveTab = 'artifacts' | 'workspace';

export type ArtifactsPanelProps = {
  agentName: string;
  threadId: string;
  artifacts: ThreadArtifactDTO[];
  loading?: boolean;
  onClose: () => void;
};

export default function ArtifactsPanel(props: ArtifactsPanelProps) {
  const { agentName, threadId, artifacts, loading, onClose } = props;
  const [activeTab, setActiveTab] = useState<ActiveTab>('artifacts');
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null);

  const workspaceQuery = useSWR(
    activeTab === 'workspace' ? ['workspace-files', agentName, threadId] : null,
    () => controlClient.agents.listWorkspaceFiles(agentName, threadId),
  );

  async function handleDownload(path: string, filename: string): Promise<void> {
    setDownloadingPath(path);
    try {
      await downloadFile(agentName, threadId, path, filename);
      Message.success(`downloaded ${filename}`);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'download failed');
    } finally {
      setDownloadingPath(null);
    }
  }

  const tabStyle = (tab: ActiveTab) => ({
    color: activeTab === tab ? CYAN : 'var(--control-subtle)',
    borderBottom: activeTab === tab ? `2px solid ${CYAN}` : '2px solid transparent',
    cursor: 'pointer' as const,
  });

  return (
    <div
      className='flex h-full w-260px shrink-0 flex-col'
      style={{
        borderLeft: '1px solid var(--control-border)',
        background: 'var(--control-panel)',
      }}
    >
      {/* Header */}
      <div
        className='flex shrink-0 items-center justify-between px-16px py-10px'
        style={{ borderBottom: '1px solid var(--control-border)' }}
      >
        <div className='flex items-center gap-12px'>
          <span
            className='pb-2px text-12px font-semibold'
            style={tabStyle('artifacts')}
            onClick={() => setActiveTab('artifacts')}
          >
            Artifacts
            <span
              className='ml-4px rd-full px-5px py-0px text-10px font-bold'
              style={{ background: activeTab === 'artifacts' ? `${CYAN}15` : 'transparent' }}
            >
              {artifacts.length}
            </span>
          </span>
          <span
            className='pb-2px text-12px font-semibold'
            style={tabStyle('workspace')}
            onClick={() => setActiveTab('workspace')}
          >
            Workspace
          </span>
        </div>
        <Button
          type='text'
          size='mini'
          className='control-quiet-icon-button'
          icon={<Close theme='outline' size='14' fill='var(--control-subtle)' />}
          onClick={onClose}
        />
      </div>

      {/* Content */}
      <div className='control-scroll min-h-0 flex-1 overflow-auto px-12px py-12px'>
        {activeTab === 'artifacts' ? (
          <ArtifactsList
            artifacts={artifacts}
            loading={loading}
            downloadingPath={downloadingPath}
            onDownload={handleDownload}
          />
        ) : (
          <WorkspaceFilesList
            files={workspaceQuery.data?.files ?? []}
            loading={workspaceQuery.isLoading}
            downloadingPath={downloadingPath}
            onDownload={handleDownload}
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Artifacts tab
// ---------------------------------------------------------------------------

function ArtifactsList(props: {
  artifacts: ThreadArtifactDTO[];
  loading?: boolean;
  downloadingPath: string | null;
  onDownload: (path: string, filename: string) => void;
}) {
  const { artifacts, loading, downloadingPath, onDownload } = props;

  if (loading) {
    return (
      <div className='flex h-80px items-center justify-center'>
        <Spin size={20} />
      </div>
    );
  }

  if (artifacts.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center py-24px'>
        <Typography.Text className='text-12px text-[var(--control-subtle)]'>
          No artifacts yet
        </Typography.Text>
      </div>
    );
  }

  return (
    <div className='flex flex-col gap-8px'>
      {artifacts.map((artifact) => {
        const path = artifact.path ?? artifact.id ?? '';
        const lc = langColor(artifact.language);

        return (
          <div
            key={artifact.id ?? path}
            className='rd-10px px-12px py-10px transition-all duration-200'
            style={{
              background: 'rgba(16,22,48,0.80)',
              border: '1px solid rgba(0,240,255,0.08)',
            }}
          >
            <div className='flex items-center gap-6px'>
              <Code theme='outline' size='14' fill={lc} />
              <span className='min-w-0 flex-1 truncate text-12px font-semibold' style={{ color: 'var(--control-text)' }}>
                {artifact.title ?? path}
              </span>
              <Button
                type='text'
                size='mini'
                className='control-quiet-icon-button'
                loading={downloadingPath === path}
                icon={<DownloadOne theme='outline' size='14' fill={GREEN} />}
                onClick={() => onDownload(path, artifact.title ?? path.split('/').pop() ?? 'download')}
              />
            </div>
            {/* Directory path — shown when path differs from title */}
            {path && path !== (artifact.title ?? '') ? (
              <div className='mt-2px truncate text-10px font-mono text-[var(--control-subtle)]' style={{ opacity: 0.7 }}>
                {path}
              </div>
            ) : null}
            <div className='mt-4px flex items-center gap-6px'>
              {artifact.language ? (
                <span
                  className='rd-4px px-5px py-1px text-10px font-mono'
                  style={{ color: lc, background: `${lc}15`, border: `1px solid ${lc}25` }}
                >
                  {artifact.language}
                </span>
              ) : null}
              {artifact.content_type ? (
                <span
                  className='rd-4px px-5px py-1px text-10px font-mono'
                  style={{ color: 'var(--control-subtle)', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}
                >
                  {artifact.content_type}
                </span>
              ) : null}
              {artifact.created_by_tool ? (
                <span className='text-10px text-[var(--control-subtle)]'>{artifact.created_by_tool}</span>
              ) : null}
              {artifact.size ? (
                <span className='text-10px text-[var(--control-subtle)]'>{formatSize(artifact.size)}</span>
              ) : null}
              {artifact.modified_at ? (
                <span className='ml-auto text-10px text-[var(--control-subtle)]'>{formatRelativeTime(artifact.modified_at)}</span>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workspace tab
// ---------------------------------------------------------------------------

function WorkspaceFilesList(props: {
  files: WorkspaceFileInfoDTO[];
  loading?: boolean;
  downloadingPath: string | null;
  onDownload: (path: string, filename: string) => void;
}) {
  const { files, loading, downloadingPath, onDownload } = props;

  if (loading) {
    return (
      <div className='flex h-80px items-center justify-center'>
        <Spin size={20} />
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center py-24px'>
        <Typography.Text className='text-12px text-[var(--control-subtle)]'>
          Workspace is empty
        </Typography.Text>
      </div>
    );
  }

  const sorted = [...files].sort((a, b) => {
    if (a.is_dir && !b.is_dir) return -1;
    if (!a.is_dir && b.is_dir) return 1;
    return (a.path ?? '').localeCompare(b.path ?? '');
  });

  return (
    <div className='flex flex-col gap-4px'>
      {sorted.map((file) => {
        const path = file.path ?? '';
        const name = path.replace(/\/$/, '').split('/').pop() ?? path;
        const isDir = file.is_dir ?? false;
        const lang = isDir ? '' : extToLang(path);
        const ic = isDir ? 'var(--control-subtle)' : langColor(lang || undefined);

        return (
          <div
            key={path}
            className='flex items-center gap-8px rd-8px px-10px py-6px transition-all duration-150'
            style={{
              background: 'rgba(16,22,48,0.50)',
              border: '1px solid rgba(0,240,255,0.05)',
            }}
          >
            {isDir ? (
              <FolderOne theme='outline' size='14' fill={ic} />
            ) : (
              <FileText theme='outline' size='13' fill={ic} />
            )}
            <span className='min-w-0 flex-1 truncate text-12px font-mono' style={{ color: 'var(--control-text)' }}>
              {name}
            </span>
            {!isDir && file.size !== undefined ? (
              <span className='shrink-0 text-10px text-[var(--control-subtle)]'>{formatSize(file.size)}</span>
            ) : null}
            {!isDir ? (
              <Button
                type='text'
                size='mini'
                className='control-quiet-icon-button'
                loading={downloadingPath === path}
                icon={<DownloadOne theme='outline' size='13' fill={GREEN} />}
                onClick={() => onDownload(path, name)}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
