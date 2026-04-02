import { LinkOne, Send, Pause } from '@icon-park/react';
import { Button, Input, Typography } from '@arco-design/web-react';
import type { ChangeEvent, RefObject } from 'react';
import type { RunStatusVM } from '@/features/chat/runtimeEventParser';

const { TextArea } = Input;
const CYAN = '#00f0ff';

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
    <div
      className='shrink-0 px-24px pb-16px pt-12px'
      style={{ borderTop: '1px solid var(--control-border)', background: 'rgba(12,16,36,0.97)' }}
    >
      <div>
        {/* Uploaded file tags */}
        {uploadedWorkspaceFiles.length > 0 ? (
          <div className='mb-8px flex flex-wrap items-center gap-6px'>
            {uploadedWorkspaceFiles.map((path) => (
              <span
                key={path}
                className='rd-full px-8px py-2px text-11px font-mono border border-solid'
                style={{ color: CYAN, borderColor: `${CYAN}30`, background: `${CYAN}08` }}
              >
                {path}
              </span>
            ))}
          </div>
        ) : null}

        {/* Input area */}
        <div
          className='rd-16px px-4px py-4px transition-all duration-200'
          style={{
            border: '1px solid rgba(0,240,255,0.15)',
            background: 'var(--control-panel-muted)',
            boxShadow: composerValue.trim() ? '0 0 12px rgba(0,240,255,0.06)' : 'none',
          }}
        >
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
              <button
                type='button'
                className='flex-center h-30px w-30px rd-full border-none cursor-pointer transition-all duration-200'
                disabled={disabled || !composerValue.trim()}
                style={{
                  background: disabled || !composerValue.trim() ? 'rgba(0,240,255,0.08)' : CYAN,
                  color: disabled || !composerValue.trim() ? 'var(--control-subtle)' : '#0a0e1a',
                  boxShadow: disabled || !composerValue.trim() ? 'none' : '0 0 10px rgba(0,240,255,0.3)',
                }}
                onClick={onSend}
              >
                <Send theme='outline' size='14' fill='currentColor' />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
