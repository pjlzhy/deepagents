import { useEffect, useRef, useState } from 'react';
import { Button, Drawer, Space, Typography } from '@arco-design/web-react';
import type { SkillDTO } from '@/shared/types/api';

type SkillEditorDrawerProps = {
  visible: boolean;
  mode: 'create' | 'replace';
  value?: SkillDTO;
  onClose: () => void;
  onSubmit: (file: File) => Promise<void>;
};

export default function SkillEditorDrawer(props: SkillEditorDrawerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!props.visible) {
      setFile(null);
      setSubmitting(false);
    }
  }, [props.visible]);

  async function handleSubmit() {
    if (!file) {
      return;
    }

    setSubmitting(true);
    try {
      await props.onSubmit(file);
      props.onClose();
    } finally {
      setSubmitting(false);
    }
  }

  function triggerFilePicker() {
    fileInputRef.current?.click();
  }

  return (
    <Drawer
      width={640}
      title={props.mode === 'create' ? 'Upload Skill' : `Replace Skill / ${props.value?.name ?? ''}`}
      visible={props.visible}
      unmountOnExit
      onCancel={props.onClose}
      footer={
        <Space>
          <Button onClick={props.onClose}>Cancel</Button>
          <Button type='primary' disabled={!file} loading={submitting} onClick={() => void handleSubmit()}>
            {props.mode === 'create' ? 'Upload' : 'Replace'}
          </Button>
        </Space>
      }
    >
      <input
        ref={fileInputRef}
        type='file'
        accept='.zip,application/zip'
        className='hidden'
        onChange={(event) => {
          setFile(event.target.files?.[0] ?? null);
        }}
      />
      <Space direction='vertical' size='large' className='w-full'>
        <div className='rounded-16px border border-[var(--control-border)] bg-[var(--control-panel-2)] p-16px'>
          <Typography.Title heading={6} className='!mt-0 !mb-8px'>
            Upload Rules
          </Typography.Title>
          <Typography.Paragraph className='!mb-0 text-[var(--control-subtle)]'>
            Upload one skill snapshot zip. The server reads the skill name from `SKILL.md`
            frontmatter, validates the directory structure, and stores the snapshot as `SKILL.md`
            plus extra text files.
          </Typography.Paragraph>
        </div>

        <div className='rounded-16px border border-dashed border-[var(--control-border)] bg-[var(--control-panel)] p-20px'>
          <Space direction='vertical' size='medium' className='w-full'>
            <Typography.Title heading={6} className='!mt-0 !mb-0'>
              {props.mode === 'create' ? 'Select Skill Package' : 'Select Replacement Package'}
            </Typography.Title>
            <Typography.Paragraph className='!mb-0 text-[var(--control-subtle)]'>
              {props.mode === 'create'
                ? 'The uploaded zip must contain a valid `SKILL.md` frontmatter. The saved registry key comes from frontmatter `name`.'
                : `The replacement zip must keep the skill name aligned with ${props.value?.name ?? 'the target skill'}.`}
            </Typography.Paragraph>
            <Space wrap>
              <Button type='secondary' onClick={triggerFilePicker}>
                Choose Zip
              </Button>
              <Typography.Text>{file?.name ?? 'No file selected'}</Typography.Text>
            </Space>
            {file ? (
              <Typography.Text className='text-[var(--control-subtle)]'>
                {(file.size / 1024).toFixed(1)} KB
              </Typography.Text>
            ) : null}
          </Space>
        </div>
      </Space>
    </Drawer>
  );
}
