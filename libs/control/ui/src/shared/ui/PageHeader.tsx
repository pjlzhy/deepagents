import type { ReactNode } from 'react';
import { Space, Typography } from '@arco-design/web-react';

type PageHeaderProps = {
  title: string;
  description: string;
  actions?: ReactNode;
};

export default function PageHeader(props: PageHeaderProps) {
  return (
    <div className='mb-24px flex flex-wrap items-start justify-between gap-18px'>
      <div className='max-w-3xl'>
        <Typography.Text className='mb-8px block text-12px uppercase tracking-[0.24em] text-[var(--control-subtle)]'>
          Control Surface
        </Typography.Text>
        <Typography.Title heading={3} className='!mb-8px !mt-0 !text-[var(--control-text)]'>
          {props.title}
        </Typography.Title>
        <Typography.Paragraph className='!mb-0 !text-[var(--control-subtle)]'>
          {props.description}
        </Typography.Paragraph>
      </div>
      {props.actions ? <Space wrap>{props.actions}</Space> : null}
    </div>
  );
}
