import { Button, Drawer, Space, Spin, Typography } from '@arco-design/web-react';
import type { SkillDetailDTO } from '@/shared/types/api';

type SkillDetailDrawerProps = {
  visible: boolean;
  loading: boolean;
  value?: SkillDetailDTO;
  onClose: () => void;
  onDownload: () => void;
  onReplace: () => void;
};

export default function SkillDetailDrawer(props: SkillDetailDrawerProps) {
  const skill = props.value;

  return (
    <Drawer
      width={820}
      title={skill?.name ? `Skill / ${skill.name}` : 'Skill Detail'}
      visible={props.visible}
      unmountOnExit
      onCancel={props.onClose}
      footer={
        <Space>
          <Button onClick={props.onDownload} disabled={!skill}>
            Download
          </Button>
          <Button type='secondary' onClick={props.onReplace} disabled={!skill}>
            Replace
          </Button>
          <Button type='primary' onClick={props.onClose}>
            Close
          </Button>
        </Space>
      }
    >
      <Spin loading={props.loading}>
        {!skill ? null : (
          <Space direction='vertical' size='large' className='w-full'>
            <section className='rounded-16px border border-[var(--control-border)] bg-[var(--control-panel-2)] p-16px'>
              <Typography.Title heading={6} className='!mt-0 !mb-12px'>
                Metadata
              </Typography.Title>
              <div className='grid grid-cols-1 gap-12px md:grid-cols-2'>
                <DetailRow label='name' value={skill.name} />
                <DetailRow label='status' value={skill.status} />
                <DetailRow label='license' value={formatUnknown(skill.license)} />
                <DetailRow label='files' value={String(skill.file_count ?? 0)} />
                <DetailRow label='updated_at' value={skill.updated_at} />
                <DetailRow label='created_at' value={skill.created_at} />
              </div>
            </section>

            <section className='rounded-16px border border-[var(--control-border)] bg-[var(--control-panel)] p-16px'>
              <Typography.Title heading={6} className='!mt-0 !mb-12px'>
                Frontmatter
              </Typography.Title>
              <pre className='max-h-240px overflow-auto whitespace-pre-wrap rounded-12px bg-[#111827] p-14px text-12px text-[#e5edf7]'>
                {JSON.stringify(skill.frontmatter ?? {}, null, 2)}
              </pre>
            </section>

            <section className='rounded-16px border border-[var(--control-border)] bg-[var(--control-panel)] p-16px'>
              <Typography.Title heading={6} className='!mt-0 !mb-12px'>
                SKILL.md
              </Typography.Title>
              <pre className='max-h-320px overflow-auto whitespace-pre-wrap rounded-12px bg-[#111827] p-14px text-12px text-[#e5edf7]'>
                {skill.skill_md ?? ''}
              </pre>
            </section>

            <section className='rounded-16px border border-[var(--control-border)] bg-[var(--control-panel)] p-16px'>
              <Typography.Title heading={6} className='!mt-0 !mb-12px'>
                File Manifest
              </Typography.Title>
              <div className='max-h-320px overflow-auto rounded-12px border border-[var(--control-border)]'>
                {(skill.file_manifest ?? []).map((entry) => (
                  <div
                    key={`${entry.path ?? 'unknown'}-${entry.sha256 ?? 'nohash'}`}
                    className='border-b border-[var(--control-border)] px-14px py-12px last:border-b-0'
                  >
                    <Typography.Text className='block font-600'>{entry.path ?? 'unknown'}</Typography.Text>
                    <Typography.Text className='block text-[var(--control-subtle)]'>
                      size: {entry.size ?? 0} bytes
                    </Typography.Text>
                    <Typography.Text className='block break-all text-[var(--control-subtle)]'>
                      sha256: {entry.sha256 ?? 'n/a'}
                    </Typography.Text>
                  </div>
                ))}
              </div>
            </section>
          </Space>
        )}
      </Spin>
    </Drawer>
  );
}

function DetailRow(props: { label: string; value?: string }) {
  return (
    <div className='rounded-12px border border-[var(--control-border)] bg-[var(--control-panel)] px-14px py-12px'>
      <Typography.Text className='block text-[var(--control-subtle)]'>{props.label}</Typography.Text>
      <Typography.Text className='block'>{props.value || 'n/a'}</Typography.Text>
    </div>
  );
}

function formatUnknown(value: unknown): string {
  if (value === null || value === undefined) {
    return 'n/a';
  }
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value);
}
