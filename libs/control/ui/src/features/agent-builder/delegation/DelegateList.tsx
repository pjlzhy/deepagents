import { useCallback } from 'react';
import { Button, Typography } from '@arco-design/web-react';
import type { FormInstance } from '@arco-design/web-react';
import DelegateCard from '@/features/agent-builder/delegation/DelegateCard';
import type { BuilderFormValues, SubagentFormValues } from '@/features/agent-builder/builderForm';

type DelegateListProps = {
  form: FormInstance<BuilderFormValues>;
};

const EMPTY_DELEGATE: SubagentFormValues = {
  name: '',
  description: '',
  systemPrompt: '',
  modelRef: '',
  skillRefs: [],
};

export default function DelegateList(props: DelegateListProps) {
  const subagents = (props.form.getFieldValue('subagents') as SubagentFormValues[] | undefined) ?? [];

  const handleAdd = useCallback(() => {
    const current = (props.form.getFieldValue('subagents') as SubagentFormValues[] | undefined) ?? [];
    props.form.setFieldsValue({
      subagents: [...current, { ...EMPTY_DELEGATE }],
    });
  }, [props.form]);

  const handleDelete = useCallback(
    (index: number) => {
      const current = (props.form.getFieldValue('subagents') as SubagentFormValues[] | undefined) ?? [];
      const updated = current.filter((_, i) => i !== index);
      props.form.setFieldsValue({ subagents: updated });
    },
    [props.form],
  );

  return (
    <div>
      {subagents.map((_, index) => (
        <DelegateCard
          key={index}
          index={index}
          form={props.form}
          onDelete={handleDelete}
        />
      ))}

      {subagents.length === 0 && (
        <div className='control-muted-card mb-16px flex-center flex-col gap-8px py-32px'>
          <Typography.Text className='text-13px text-[var(--control-subtle)]'>
            No delegates configured. Add one to enable task delegation.
          </Typography.Text>
        </div>
      )}

      <Button
        type='outline'
        onClick={handleAdd}
        className='w-full'
      >
        + Add Delegate
      </Button>
    </div>
  );
}
