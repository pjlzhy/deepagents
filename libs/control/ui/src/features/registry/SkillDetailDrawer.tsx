import { useState, useMemo } from 'react';
import { Button, Drawer, Spin } from '@arco-design/web-react';
import { Lightning, FolderCode, Shield, Fingerprint, Code, Terminal, Time } from '@icon-park/react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { SkillDetailDTO, SkillFileManifestDTO } from '@/shared/types/api';

/* ── Types ── */

type SkillDetailDrawerProps = {
  visible: boolean;
  loading: boolean;
  value?: SkillDetailDTO;
  onClose: () => void;
  onDownload: () => void;
  onReplace: () => void;
};

type FileTreeNode = {
  name: string;
  /** Full path for leaf files */
  path?: string;
  entry?: SkillFileManifestDTO;
  children: Map<string, FileTreeNode>;
};

/* ── Constants ── */

const ACCENT = '#39ff14';

/** Frontmatter keys already shown in the hero header — skip in the grid. */
const HERO_KEYS = new Set(['name', 'description', 'version', 'status']);

/* ── Helpers ── */

function fileIcon(path?: string) {
  if (!path) return <FolderCode size={16} fill={[ACCENT]} />;
  const ext = path.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'md':
      return <Lightning size={16} fill={[ACCENT]} />;
    case 'sh':
    case 'bash':
      return <Terminal size={16} fill={[ACCENT]} />;
    case 'py':
    case 'ts':
    case 'js':
    case 'json':
    case 'yaml':
    case 'yml':
      return <Code size={16} fill={[ACCENT]} />;
    default:
      return <FolderCode size={16} fill={[ACCENT]} />;
  }
}

function formatDigest(value?: string): string {
  if (!value) return 'n/a';
  return value.length > 12 ? `${value.slice(0, 12)}..` : value;
}

function formatDate(value?: string): string {
  if (!value) return 'n/a';
  try {
    const d = new Date(value);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  } catch {
    return value.slice(0, 10);
  }
}

function formatLicense(value: unknown): string {
  if (value === null || value === undefined) return 'n/a';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function formatBytes(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function stripFrontmatter(md: string): string {
  const trimmed = md.trimStart();
  if (!trimmed.startsWith('---')) return md;
  const end = trimmed.indexOf('---', 3);
  if (end === -1) return md;
  return trimmed.slice(end + 3).trimStart();
}

/** Flatten a value for display — arrays become tag pills, objects become JSON. */
function flattenValue(value: unknown): { kind: 'text'; text: string } | { kind: 'tags'; tags: string[] } {
  if (Array.isArray(value)) {
    return { kind: 'tags', tags: value.map((v) => (typeof v === 'string' ? v : JSON.stringify(v))) };
  }
  if (value === null || value === undefined) return { kind: 'text', text: 'n/a' };
  if (typeof value === 'string') return { kind: 'text', text: value };
  if (typeof value === 'number' || typeof value === 'boolean') return { kind: 'text', text: String(value) };
  return { kind: 'text', text: JSON.stringify(value) };
}

/* ── File tree builder ── */

function buildFileTree(files: SkillFileManifestDTO[]): FileTreeNode {
  const root: FileTreeNode = { name: '', children: new Map() };
  for (const entry of files) {
    const parts = (entry.path ?? 'unknown').split('/');
    let cur = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      if (!cur.children.has(part)) {
        cur.children.set(part, { name: part, children: new Map() });
      }
      cur = cur.children.get(part)!;
      if (i === parts.length - 1) {
        cur.path = entry.path;
        cur.entry = entry;
      }
    }
  }
  return root;
}

function countFiles(node: FileTreeNode): number {
  if (node.entry) return 1;
  let n = 0;
  for (const child of node.children.values()) n += countFiles(child);
  return n;
}

function sumSize(node: FileTreeNode): number {
  if (node.entry) return node.entry.size ?? 0;
  let s = 0;
  for (const child of node.children.values()) s += sumSize(child);
  return s;
}

/* ── Sub-components ── */

function HeroHeader({ skill }: { skill: SkillDetailDTO }) {
  const fm = skill.frontmatter ?? {};
  const version = fm['version'] as string | undefined;

  /** Collect frontmatter rows that aren't already in the hero. */
  const fmRows = useMemo(() => {
    const rows: Array<{ key: string; value: unknown }> = [];

    /** Recursively flatten nested objects with dot-key notation. */
    function collect(obj: Record<string, unknown>, prefix: string) {
      for (const [k, v] of Object.entries(obj)) {
        const fullKey = prefix ? `${prefix}.${k}` : k;
        if (HERO_KEYS.has(fullKey)) continue;
        if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
          collect(v as Record<string, unknown>, fullKey);
        } else {
          rows.push({ key: fullKey, value: v });
        }
      }
    }

    collect(fm, '');
    return rows;
  }, [fm]);

  return (
    <div className='skill-drawer-hero'>
      <div className='skill-drawer-hero-icon'>
        <Lightning size={24} fill={[ACCENT]} />
      </div>
      <div className='flex-1 min-w-0'>
        {/* Title row */}
        <div className='flex items-center gap-10px flex-wrap'>
          <span className='text-18px font-700 text-[var(--control-text,#e5edf7)]'>
            {skill.name ?? 'unnamed-skill'}
          </span>
          {version && (
            <span className='text-12px text-[var(--control-subtle)]'>v{version}</span>
          )}
          {skill.status && (
            <span className='flex items-center gap-6px text-12px text-[var(--control-subtle)]'>
              <span
                className={`inline-block w-8px h-8px rounded-full ${
                  skill.status === 'published'
                    ? 'registry-status-dot--published bg-[#39ff14]'
                    : 'bg-[var(--control-subtle)]'
                }`}
              />
              {skill.status}
            </span>
          )}
          <span className='skill-section-chip'>SKILL</span>
        </div>

        {/* Description */}
        {skill.description && (
          <p className='mt-6px mb-0 text-13px text-[var(--control-subtle)] line-clamp-2'>
            {skill.description}
          </p>
        )}

        {/* Stat badges */}
        <div className='skill-drawer-stats'>
          <span className='skill-drawer-stat'>
            <FolderCode size={14} fill={[ACCENT]} />
            {skill.file_count ?? 0} files
          </span>
          <span className='skill-drawer-stat'>
            <Shield size={14} fill={[ACCENT]} />
            {formatLicense(skill.license)}
          </span>
          <span className='skill-drawer-stat'>
            <Fingerprint size={14} fill={[ACCENT]} />
            {formatDigest(skill.snapshot_digest)}
          </span>
          <span className='skill-drawer-stat'>
            <Time size={14} fill={[ACCENT]} />
            {formatDate(skill.updated_at)}
          </span>
        </div>

        {/* Frontmatter property grid */}
        {fmRows.length > 0 && (
          <div className='skill-frontmatter-grid'>
            {fmRows.map(({ key, value }) => {
              const flat = flattenValue(value);
              return (
                <Fragment key={key}>
                  <span className='skill-fm-key'>{key}</span>
                  <span className='skill-fm-value'>
                    {flat.kind === 'tags' ? (
                      <span className='flex flex-wrap'>
                        {flat.tags.map((t, i) => (
                          <span key={i} className='skill-fm-tag'>{t}</span>
                        ))}
                      </span>
                    ) : (
                      flat.text
                    )}
                  </span>
                </Fragment>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function SectionCard({
  icon,
  title,
  chip,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  chip: string;
  children: React.ReactNode;
}) {
  return (
    <div className='skill-section'>
      <div className='skill-section-header'>
        {icon}
        <span className='text-14px font-600 text-[var(--control-text,#e5edf7)]'>{title}</span>
        <span className='skill-section-chip'>{chip}</span>
      </div>
      {children}
    </div>
  );
}

/* ── File tree components ── */

function FolderNode({ node, depth, defaultOpen }: { node: FileTreeNode; depth: number; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const childNodes = Array.from(node.children.values());
  const files = childNodes.filter((c) => c.entry);
  const folders = childNodes.filter((c) => !c.entry);
  const n = countFiles(node);
  const size = sumSize(node);

  return (
    <div style={{ paddingLeft: depth > 0 ? 16 : 0 }}>
      <div className='skill-folder-row' onClick={() => setOpen((v) => !v)}>
        <span className={`skill-folder-chevron${open ? ' skill-folder-chevron--open' : ''}`}>
          <svg width='12' height='12' viewBox='0 0 12 12' fill='none'>
            <path d='M4.5 2.5L8 6L4.5 9.5' stroke={ACCENT} strokeWidth='1.5' strokeLinecap='round' strokeLinejoin='round' />
          </svg>
        </span>
        <FolderCode size={16} fill={[ACCENT]} />
        <span className='text-13px font-600' style={{ color: ACCENT }}>{node.name}/</span>
        <span className='text-11px text-[var(--control-subtle)]'>
          {n} file{n !== 1 ? 's' : ''} &middot; {formatBytes(size)}
        </span>
      </div>
      <div className={`skill-folder-children${open ? ' skill-folder-children--open' : ''}`}>
        <div className='skill-folder-children-inner'>
          {folders.map((f) => (
            <FolderNode key={f.name} node={f} depth={depth + 1} defaultOpen={false} />
          ))}
          <div className='flex flex-col gap-4px' style={{ paddingLeft: 16 }}>
            {files.map((f) => (
              <FileLeafCard key={f.path ?? f.name} node={f} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function FileLeafCard({ node }: { node: FileTreeNode }) {
  const entry = node.entry!;
  return (
    <div className='skill-file-card'>
      <div className='skill-file-card-icon'>
        {fileIcon(entry.path)}
      </div>
      <span className='text-13px font-600' style={{ color: ACCENT }}>{node.name}</span>
      <span className='text-11px text-[var(--control-subtle)] ml-auto whitespace-nowrap'>
        {formatBytes(entry.size)}
      </span>
      <span className='text-11px text-[var(--control-subtle)] break-all'>
        {entry.sha256 ? entry.sha256.slice(0, 10) + '...' : ''}
      </span>
    </div>
  );
}

function FileManifestTree({ files }: { files: SkillFileManifestDTO[] }) {
  const root = useMemo(() => buildFileTree(files), [files]);
  const childNodes = Array.from(root.children.values());
  const rootFiles = childNodes.filter((c) => c.entry);
  const rootFolders = childNodes.filter((c) => !c.entry);

  return (
    <div className='flex flex-col gap-4px p-12px'>
      {/* Folders first (default open at depth 0) */}
      {rootFolders.map((f) => (
        <FolderNode key={f.name} node={f} depth={0} defaultOpen={true} />
      ))}
      {/* Root-level files */}
      {rootFiles.length > 0 && (
        <div className='flex flex-col gap-4px'>
          {rootFiles.map((f) => (
            <FileLeafCard key={f.path ?? f.name} node={f} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main Component ── */

import { Fragment } from 'react';

export default function SkillDetailDrawer(props: SkillDetailDrawerProps) {
  const skill = props.value;
  const mdBody = useMemo(() => (skill?.skill_md ? stripFrontmatter(skill.skill_md) : ''), [skill?.skill_md]);

  return (
    <Drawer
      width={1080}
      title={null}
      visible={props.visible}
      unmountOnExit
      headerStyle={{ display: 'none' }}
      onCancel={props.onClose}
      footer={
        <div className='skill-drawer-footer flex justify-end gap-10px'>
          <Button className='skill-drawer-btn-download' onClick={props.onDownload} disabled={!skill}>
            Download
          </Button>
          <Button type='secondary' onClick={props.onReplace} disabled={!skill}>
            Replace
          </Button>
          <Button className='skill-drawer-btn-close' onClick={props.onClose}>
            Close
          </Button>
        </div>
      }
    >
      <Spin loading={props.loading}>
        {!skill ? null : (
          <div className='flex flex-col gap-20px'>
            {/* Hero Header + Frontmatter */}
            <HeroHeader skill={skill} />

            {/* SKILL.md — rendered markdown */}
            {mdBody && (
              <SectionCard
                icon={<Lightning size={18} fill={[ACCENT]} />}
                title='SKILL.md'
                chip='MARKDOWN'
              >
                <div className='skill-markdown'>
                  <Markdown remarkPlugins={[remarkGfm]}>{mdBody}</Markdown>
                </div>
              </SectionCard>
            )}

            {/* File Manifest — collapsible tree */}
            {(skill.file_manifest ?? []).length > 0 && (
              <SectionCard
                icon={<FolderCode size={18} fill={[ACCENT]} />}
                title={`File Manifest (${skill.file_manifest.length} files)`}
                chip='FILES'
              >
                <FileManifestTree files={skill.file_manifest} />
              </SectionCard>
            )}
          </div>
        )}
      </Spin>
    </Drawer>
  );
}
