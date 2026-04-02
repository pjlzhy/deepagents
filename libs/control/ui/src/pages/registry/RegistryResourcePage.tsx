import type { ReactNode } from 'react';
import { Empty, Pagination, Tag, Typography } from '@arco-design/web-react';

type RegistryCardItem = {
  key: string;
  name: string;
  description?: string;
  status?: string;
  updatedAt?: string;
  details: Array<{
    label: string;
    value: string;
  }>;
  tags?: string[];
  actions?: ReactNode;
};

type RegistryResourcePageProps = {
  title: string;
  description: string;
  /** Accent color for the left strip on cards (CSS color value) */
  accent?: string;
  actions?: ReactNode;
  loading: boolean;
  pageNumber: number;
  pageSize: number;
  totalSize?: number;
  items: RegistryCardItem[];
  onPageChange: (pageNumber: number, pageSize: number) => void;
};

const statusDot: Record<string, string> = {
  published: 'var(--control-success)',
  draft: 'var(--control-warning)',
  deleted: 'var(--control-danger)',
};

export default function RegistryResourcePage(props: RegistryResourcePageProps) {
  const accent = props.accent ?? 'var(--control-primary)';

  return (
    <div className='flex flex-col gap-18px'>
      {/* Header */}
      <div className='flex flex-wrap items-center justify-between gap-12px'>
        <div>
          <Typography.Title heading={3} className='!mb-4px !mt-0 !text-[var(--control-text)]'>
            {props.title}
          </Typography.Title>
          <Typography.Text className='text-13px text-[var(--control-subtle)]'>
            {props.description}
          </Typography.Text>
        </div>
        {props.actions ? <div className='flex gap-8px'>{props.actions}</div> : null}
      </div>

      {/* Grid */}
      {props.items.length === 0 && !props.loading ? (
        <div className='control-card flex-center py-40px'>
          <Empty description='No data' />
        </div>
      ) : (
        <div className='grid grid-cols-1 gap-14px xl:grid-cols-2'>
          {props.items.map((item) => (
            <div
              key={item.key}
              className='control-card control-glow-hover flex overflow-hidden'
            >
              {/* Accent strip */}
              <div className='w-4px shrink-0 rd-l-18px' style={{ background: accent }} />

              {/* Content */}
              <div className='flex min-w-0 flex-1 flex-col px-16px py-14px'>
                {/* Name + status dot */}
                <div className='mb-6px flex items-center gap-8px'>
                  <Typography.Text className='truncate text-15px font-semibold text-[var(--control-text)]'>
                    {item.name}
                  </Typography.Text>
                  {item.status ? (
                    <span className='flex shrink-0 items-center gap-4px text-12px text-[var(--control-subtle)]'>
                      <span
                        className='inline-block h-7px w-7px rd-full'
                        style={{ background: statusDot[item.status] ?? 'var(--control-subtle)' }}
                      />
                      {item.status}
                    </span>
                  ) : null}
                </div>

                {/* Description */}
                <Typography.Text className='mb-10px line-clamp-1 text-13px text-[var(--control-subtle)]'>
                  {item.description || 'no description'}
                </Typography.Text>

                {/* Detail rows */}
                <div className='rd-8px bg-[rgba(0,240,255,0.03)] px-10px py-6px'>
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

                {/* Tags */}
                {item.tags && item.tags.length > 0 ? (
                  <div className='mt-8px flex flex-wrap gap-6px'>
                    {item.tags.map((tag) => (
                      <Tag key={`${item.key}-${tag}`} size='small' color='arcoblue'>
                        {tag}
                      </Tag>
                    ))}
                  </div>
                ) : null}

                {/* Footer: timestamp + actions */}
                <div className='mt-10px flex items-center justify-between'>
                  <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                    {formatUpdatedAt(item.updatedAt)}
                  </Typography.Text>
                  {item.actions ? <div className='flex gap-6px'>{item.actions}</div> : null}
                </div>
              </div>
            </div>
          ))}
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
