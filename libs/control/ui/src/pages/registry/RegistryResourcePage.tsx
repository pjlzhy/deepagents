import type { ReactNode } from 'react';
import { Card, Empty, Pagination, Space, Tag, Typography } from '@arco-design/web-react';
import PageHeader from '@/shared/ui/PageHeader';

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
  actions?: ReactNode;
  loading: boolean;
  pageNumber: number;
  pageSize: number;
  totalSize?: number;
  items: RegistryCardItem[];
  onPageChange: (pageNumber: number, pageSize: number) => void;
};

export default function RegistryResourcePage(props: RegistryResourcePageProps) {
  return (
    <div>
      <PageHeader title={props.title} description={props.description} actions={props.actions} />
      {props.items.length === 0 && !props.loading ? (
        <Card className='control-card'>
          <Empty description='No data' />
        </Card>
      ) : (
        <div className='grid grid-cols-1 gap-18px xl:grid-cols-2'>
          {props.items.map((item) => (
            <Card key={item.key} className='control-card' loading={props.loading}>
              <div className='mb-12px flex items-start justify-between gap-12px'>
                <div>
                  <Typography.Title heading={5} className='!mb-6px !mt-0'>
                    {item.name}
                  </Typography.Title>
                  <Typography.Paragraph className='!mb-0 !text-[var(--control-subtle)]'>
                    {item.description || 'no description'}
                  </Typography.Paragraph>
                </div>
                {item.status ? <Tag color='gray'>{item.status}</Tag> : null}
              </div>
              <Space direction='vertical' size='small' className='w-full'>
                {item.details.map((detail) => (
                  <div key={`${item.key}-${detail.label}`} className='flex items-center justify-between gap-12px'>
                    <Typography.Text className='text-[var(--control-subtle)]'>{detail.label}</Typography.Text>
                    <Typography.Text className='text-right'>{detail.value}</Typography.Text>
                  </div>
                ))}
                {item.tags && item.tags.length > 0 ? (
                  <div className='flex flex-wrap gap-8px pt-6px'>
                    {item.tags.map((tag) => (
                      <Tag key={`${item.key}-${tag}`} color='arcoblue'>
                        {tag}
                      </Tag>
                    ))}
                  </div>
                ) : null}
              </Space>
              <div className='mt-16px flex flex-col gap-10px'>
                {item.actions ? <div className='flex flex-wrap justify-end gap-8px'>{item.actions}</div> : null}
                <Typography.Text className='text-[var(--control-subtle)]'>
                  updated_at: {formatUpdatedAt(item.updatedAt)}
                </Typography.Text>
              </div>
            </Card>
          ))}
        </div>
      )}
      <div className='mt-18px flex justify-end'>
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
  if (!value) {
    return 'n/a';
  }

  const trimmed = value.trim();
  const match = trimmed.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
  if (match) {
    return `${match[1]} ${match[2]}`;
  }

  const date = new Date(trimmed);
  if (Number.isNaN(date.getTime())) {
    return trimmed;
  }

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
