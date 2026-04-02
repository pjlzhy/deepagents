import { useState, type ReactNode } from 'react';
import { Empty, Pagination, Tag, Typography } from '@arco-design/web-react';
import { REGISTRY_ICONS } from './registryIcons';
import '@/styles/registry-cards.css';

/* ── Types ── */

export type StatBadge = {
  icon: keyof typeof REGISTRY_ICONS;
  label: string;
  value: string | number;
  color?: string;
};

export type ResourceTypeConfig = {
  kind: 'model' | 'skill' | 'mcp' | 'sandbox' | 'agent';
  icon: ReactNode;
  accent: string;
  glowColor: string;
  headerTint: string;
  categoryLabel: string;
};

export type RegistryCardItem = {
  key: string;
  name: string;
  description?: string;
  status?: string;
  updatedAt?: string;
  details: Array<{ label: string; value: string }>;
  tags?: string[];
  actions?: ReactNode;
  stats?: StatBadge[];
  subtitle?: string;
  expandedContent?: ReactNode;
};

type RegistryResourcePageProps = {
  title: string;
  description: string;
  /** @deprecated Use resourceType.accent instead — kept for backward-compat */
  accent?: string;
  resourceType?: ResourceTypeConfig;
  actions?: ReactNode;
  loading: boolean;
  pageNumber: number;
  pageSize: number;
  totalSize?: number;
  items: RegistryCardItem[];
  onPageChange: (pageNumber: number, pageSize: number) => void;
};

/* ── Status helpers ── */

const statusDot: Record<string, string> = {
  published: 'var(--control-success)',
  draft: 'var(--control-warning)',
  deleted: 'var(--control-danger)',
};

/* ── Component ── */

export default function RegistryResourcePage(props: RegistryResourcePageProps) {
  const rt = props.resourceType;
  const accent = rt?.accent ?? props.accent ?? 'var(--control-primary)';
  const glowColor = rt?.glowColor ?? 'rgba(0,240,255,0.15)';
  const headerTint = rt?.headerTint ?? 'rgba(0,240,255,0.04)';

  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  return (
    <div className='flex flex-col gap-18px'>
      {/* Header */}
      <div className='flex flex-wrap items-center justify-between gap-12px'>
        <div className='flex items-center gap-12px'>
          {rt?.icon ? (
            <div
              className='registry-card-icon'
              style={{ background: headerTint, color: accent }}
            >
              {rt.icon}
            </div>
          ) : null}
          <div>
            <Typography.Title heading={3} className='!mb-4px !mt-0 !text-[var(--control-text)]'>
              {props.title}
            </Typography.Title>
            <Typography.Text className='text-13px text-[var(--control-subtle)]'>
              {props.description}
            </Typography.Text>
          </div>
        </div>
        {props.actions ? <div className='flex gap-8px'>{props.actions}</div> : null}
      </div>

      {/* Grid */}
      {props.items.length === 0 && !props.loading ? (
        <div className='control-card flex-center py-40px'>
          <Empty description='No data' />
        </div>
      ) : (
        <div className='grid grid-cols-1 gap-14px lg:grid-cols-2 xl:grid-cols-3'>
          {props.items.map((item) => {
            const isExpanded = expandedKey === item.key;
            return (
              <div
                key={item.key}
                className='registry-card control-card cursor-pointer overflow-hidden'
                style={{
                  '--card-accent': accent,
                  '--card-glow': glowColor,
                } as React.CSSProperties}
                onClick={() => {
                  if (item.expandedContent) {
                    setExpandedKey(isExpanded ? null : item.key);
                  }
                }}
              >
                <div className='flex flex-col px-16px py-14px'>
                  {/* Top row: icon + name + status + category */}
                  <div className='mb-8px flex items-start gap-10px'>
                    {/* Icon zone */}
                    {rt?.icon ? (
                      <div
                        className='registry-card-icon registry-card-icon-zone'
                        style={{ background: headerTint, color: accent }}
                      >
                        {rt.icon}
                      </div>
                    ) : null}

                    {/* Name + subtitle + status */}
                    <div className='min-w-0 flex-1'>
                      <div className='flex items-center gap-8px'>
                        <Typography.Text className='truncate text-15px font-semibold text-[var(--control-text)]'>
                          {item.name}
                        </Typography.Text>
                        {item.status ? (
                          <span className='flex shrink-0 items-center gap-4px text-12px text-[var(--control-subtle)]'>
                            <span
                              className={`inline-block h-7px w-7px rd-full${item.status === 'published' ? ' registry-status-dot--published' : ''}`}
                              style={{ background: statusDot[item.status] ?? 'var(--control-subtle)' }}
                            />
                            {item.status}
                          </span>
                        ) : null}
                      </div>
                      {item.subtitle ? (
                        <Typography.Text className='mt-2px text-12px text-[var(--control-subtle)]'>
                          {item.subtitle}
                        </Typography.Text>
                      ) : null}
                    </div>

                    {/* Category chip */}
                    {rt?.categoryLabel ? (
                      <span
                        className='registry-category-chip shrink-0 rd-6px border border-solid px-6px py-2px text-10px font-bold tracking-wider'
                        style={{
                          color: accent,
                          borderColor: accent,
                          background: headerTint,
                        }}
                      >
                        {rt.categoryLabel}
                      </span>
                    ) : null}
                  </div>

                  {/* Description — 3 lines */}
                  <Typography.Text className='mb-10px line-clamp-3 text-13px text-[var(--control-subtle)]'>
                    {item.description || 'no description'}
                  </Typography.Text>

                  {/* Stat badges */}
                  {item.stats && item.stats.length > 0 ? (
                    <div className='mb-8px flex flex-wrap gap-6px'>
                      {item.stats.map((stat) => {
                        const IconComp = REGISTRY_ICONS[stat.icon];
                        return (
                          <span
                            key={`${item.key}-stat-${stat.label}`}
                            className='registry-stat-badge registry-stat-pill'
                            style={{ color: stat.color ?? accent }}
                          >
                            {IconComp ? <IconComp size={14} fill={[stat.color ?? accent]} /> : null}
                            <span className='text-[var(--control-subtle)]'>{stat.value}</span>
                          </span>
                        );
                      })}
                    </div>
                  ) : (
                    /* Fallback: legacy detail rows */
                    item.details.length > 0 ? (
                      <div className='mb-8px rd-8px bg-[rgba(0,240,255,0.03)] px-10px py-6px'>
                        {item.details.map((detail) => (
                          <div
                            key={`${item.key}-${detail.label}`}
                            className='flex items-center justify-between py-3px text-13px'
                          >
                            <span className='font-mono text-12px text-[var(--control-subtle)]'>{detail.label}</span>
                            <span className='truncate pl-12px text-right font-mono text-12px text-[var(--control-text)]'>
                              {detail.value}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : null
                  )}

                  {/* Tags */}
                  {item.tags && item.tags.length > 0 ? (
                    <div className='mb-8px flex flex-wrap gap-6px'>
                      {item.tags.map((tag) => (
                        <Tag key={`${item.key}-${tag}`} size='small' color='arcoblue'>
                          {tag}
                        </Tag>
                      ))}
                    </div>
                  ) : null}

                  {/* Footer: timestamp + actions */}
                  <div className='flex items-center justify-between'>
                    <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                      {formatUpdatedAt(item.updatedAt)}
                    </Typography.Text>
                    {item.actions ? (
                      <div
                        className='flex gap-6px'
                        onClick={(e) => e.stopPropagation()}
                      >
                        {item.actions}
                      </div>
                    ) : null}
                  </div>
                </div>

                {/* Expandable detail panel */}
                {item.expandedContent ? (
                  <div className={`registry-expand-body${isExpanded ? ' registry-expand-body--open' : ''}`}>
                    <div className='registry-expand-inner'>
                      <div
                        className='border-t border-solid border-[var(--control-border)] px-16px py-12px text-12px font-mono text-[var(--control-subtle)]'
                        onClick={(e) => e.stopPropagation()}
                      >
                        {item.expandedContent}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      <div className='flex justify-end'>
        <Pagination
          current={props.pageNumber}
          pageSize={props.pageSize}
          total={props.totalSize ?? props.items.length}
          sizeCanChange
          onChange={(pageNumber, pageSize) => {
            props.onPageChange(pageNumber, pageSize);
          }}
        />
      </div>
    </div>
  );
}

/* ── Helpers ── */

function formatUpdatedAt(value?: string): string {
  if (!value) return 'n/a';
  const trimmed = value.trim();
  const match = trimmed.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
  if (match) return `${match[1]} ${match[2]}`;
  const date = new Date(trimmed);
  if (Number.isNaN(date.getTime())) return trimmed;
  return [
    date.getFullYear().toString().padStart(4, '0'),
    (date.getMonth() + 1).toString().padStart(2, '0'),
    date.getDate().toString().padStart(2, '0'),
  ].join('-') + ` ${[
    date.getHours().toString().padStart(2, '0'),
    date.getMinutes().toString().padStart(2, '0'),
    date.getSeconds().toString().padStart(2, '0'),
  ].join(':')}`;
}
