import { LinkOne, Send, Pause } from '@icon-park/react';
import { Button, Input, Tag, Typography } from '@arco-design/web-react';
import type { ChangeEvent, RefObject } from 'react';
import type { RunStatusVM } from '@/features/chat/runtimeEventParser';

const { TextArea } = Input;

function isRunActive(status: RunStatusVM): boolean {
  return ['starting', 'streaming', 'waiting_hitl', 'canceling'].includes(status);
}

export type ChatComposerProps = {
  composerValue: string;
  runStatus: RunStatusVM;
  selectedAgentName?: string;
  uploadingFiles: boolean;
  uploadedWorkspaceFiles: string[];
  runSessionId?: string;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onComposerChange: (value: string) => void;
  onSend: () => void;
  onCancel: () => void;
  onUploadClick: () => void;
  onFilesSelected: (event: ChangeEvent<HTMLInputElement>) => void;
};

export default function ChatComposer(props: ChatComposerProps) {
  const {
    composerValue,
    runStatus,
    selectedAgentName,
    uploadingFiles,
    uploadedWorkspaceFiles,
    runSessionId,
    fileInputRef,
    onComposerChange,
    onSend,
    onCancel,
    onUploadClick,
    onFilesSelected,
  } = props;

  const active = isRunActive(runStatus);
  const disabled = !selectedAgentName || active || uploadingFiles;

  const statusText = uploadingFiles
    ? 'Uploading files...'
    : runStatus === 'waiting_hitl'
      ? 'Waiting for approval'
      : active
        ? 'Agent is working...'
        : undefined;

  return (
    <div className='shrink-0 border-t border-solid border-[var(--control-border)] bg-[var(--control-panel)] px-24px pb-16px pt-12px'>
      <div>
        {/* Uploaded file tags */}
        {uploadedWorkspaceFiles.length > 0 ? (
          <div className='mb-8px flex flex-wrap items-center gap-6px'>
            {uploadedWorkspaceFiles.map((path) => (
              <Tag key={path} size='small' color='arcoblue'>
                {path}
              </Tag>
            ))}
          </div>
        ) : null}

        {/* Input area */}
        <div className='rd-16px border border-solid border-[var(--control-border)] bg-[var(--control-panel-muted)] px-4px py-4px'>
          <TextArea
            autoSize={{ minRows: 1, maxRows: 8 }}
            placeholder={selectedAgentName ? 'Message...' : 'Select an agent to start'}
            value={composerValue}
            disabled={disabled}
            className='!border-none !bg-transparent !shadow-none'
            style={{ resize: 'none' }}
            onChange={onComposerChange}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                onSend();
              }
            }}
          />

          {/* Bottom toolbar */}
          <div className='flex items-center justify-between px-8px pb-4px pt-2px'>
            <div className='flex items-center gap-4px'>
              <input
                ref={fileInputRef}
                type='file'
                multiple
                className='hidden'
                onChange={onFilesSelected}
              />
              <Button
                type='text'
                size='mini'
                className='control-quiet-icon-button'
                icon={<LinkOne theme='outline' size='16' fill='var(--control-subtle)' />}
                disabled={!selectedAgentName || active}
                loading={uploadingFiles}
                onClick={onUploadClick}
              />
              {statusText ? (
                <Typography.Text className='ml-4px text-12px text-[var(--control-subtle)]'>{statusText}</Typography.Text>
              ) : null}
            </div>

            <div className='flex items-center gap-6px'>
              {active && runSessionId ? (
                <Button
                  type='text'
                  size='mini'
                  className='control-quiet-icon-button'
                  icon={<Pause theme='outline' size='16' fill='var(--control-danger)' />}
                  onClick={onCancel}
                />
              ) : null}
              <Button
                type='primary'
                size='small'
                shape='circle'
                icon={<Send theme='outline' size='14' fill='currentColor' />}
                disabled={disabled || !composerValue.trim()}
                onClick={onSend}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
