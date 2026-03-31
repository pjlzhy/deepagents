import { Space, Typography } from '@arco-design/web-react';
import type { AgentSpecDTO } from '@/shared/types/api';

export default function AgentEditorNotes(props: { agent?: AgentSpecDTO }) {
  return (
    <>
      <Typography.Title heading={5} className='!mt-0'>
        Notes
      </Typography.Title>
      <Space direction='vertical' size='large' className='w-full'>
        <div>
          <Typography.Paragraph className='!mb-6px text-[var(--control-subtle)]'>
            Registry-backed references
          </Typography.Paragraph>
          <Typography.Paragraph className='!mb-0'>
            `model_ref`, `skill_refs`, `mcp_refs`, and `sandbox_ref` load registry options on demand in paged batches
            instead of pulling the full registry into the form upfront.
          </Typography.Paragraph>
        </div>
        <div>
          <Typography.Paragraph className='!mb-6px text-[var(--control-subtle)]'>
            Structured fields
          </Typography.Paragraph>
          <Typography.Paragraph className='!mb-0'>
            `subagents` are still edited as JSON, while reusable sandbox configs move to the dedicated `Sandboxes`
            registry page and are attached through `sandbox_ref`.
          </Typography.Paragraph>
        </div>
        {props.agent ? (
          <div>
            <Typography.Paragraph className='!mb-6px text-[var(--control-subtle)]'>
              Metadata
            </Typography.Paragraph>
            <Typography.Paragraph className='!mb-4px'>created_at: {props.agent.created_at ?? 'n/a'}</Typography.Paragraph>
            <Typography.Paragraph className='!mb-4px'>updated_at: {props.agent.updated_at ?? 'n/a'}</Typography.Paragraph>
            <Typography.Paragraph className='!mb-0'>status: {props.agent.status ?? 'n/a'}</Typography.Paragraph>
          </div>
        ) : null}
      </Space>
    </>
  );
}
