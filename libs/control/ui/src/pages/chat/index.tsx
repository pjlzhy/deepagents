import { RobotOne, FolderOpen } from '@icon-park/react';
import { Button, Spin, Typography } from '@arco-design/web-react';
import { useMemo } from 'react';
import {
  createConversationTimeline,
  createRuntimeStateFromHistory,
  type ConversationTimelineItemVM,
  type PendingInterruptVM,
} from '@/features/chat/runtimeEventParser';
import '@/styles/registry-cards.css';

import ThreadSidebar from './ThreadSidebar';
import { UserBubble, AssistantBubble, HitlRequestBubble } from './MessageBubble';
import ToolCallCard from './ToolCallCard';
import ChatComposer from './ChatComposer';
import ArtifactsPanel from './ArtifactsPanel';
import SegmentedTabs from '@/shared/components/telemetry/SegmentedTabs';
import SnapshotBanner from './SnapshotBanner';
import RunsView from './RunsView';
import { useChatWorkspaceState } from './useChatWorkspaceState';

const CYAN = '#00f0ff';

function renderTimelineItem(
  item: ConversationTimelineItemVM,
  opts: {
    pendingInterrupts: PendingInterruptVM[];
    onSubmitDecision: (interrupt: PendingInterruptVM, type: 'approve' | 'reject') => void;
  },
) {
  if (item.kind === 'user_message') return <UserBubble item={item} />;
  if (item.kind === 'assistant_message' || item.kind === 'assistant_draft') return <AssistantBubble item={item} />;
  if (item.kind === 'assistant_tool_call') {
    return <ToolCallCard item={item} />;
  }
  if (item.kind === 'hitl_request') {
    const pending = opts.pendingInterrupts.find((p) => p.interruptId === item.interruptId);
    return (
      <HitlRequestBubble
        item={item}
        resolved={!pending}
        onApprove={pending ? () => opts.onSubmitDecision(pending, 'approve') : undefined}
        onReject={pending ? () => opts.onSubmitDecision(pending, 'reject') : undefined}
      />
    );
  }
  return null;
}

export default function ChatWorkspacePage() {
  const state = useChatWorkspaceState();

  // Snapshot mode: render snapshot messages instead of live timeline
  const snapshotTimelineItems = useMemo(() => {
    if (!state.snapshotView.active) return [];
    const runtimeState = createRuntimeStateFromHistory(state.snapshotView.messages);
    return createConversationTimeline(runtimeState.timeline).filter((item) => item.kind !== 'system_event');
  }, [state.snapshotView]);

  const showChat = state.activeTab === 'chat';
  const showRuns = state.activeTab === 'runs';
  const isSnapshot = state.snapshotView.active;
  const timelineItems = isSnapshot ? snapshotTimelineItems : state.chatTimelineItems;
  const hideComposer = isSnapshot;

  return (
    <div className='flex h-full min-h-0 overflow-hidden rd-4px'>
      {/* Thread sidebar */}
      <ThreadSidebar
        agentOptions={state.agentOptions}
        selectedAgentName={state.selectedAgentName}
        selectedThreadId={state.selectedThreadId}
        sessions={state.sessionItems}
        disabled={state.runActive}
        collapsed={state.sidebarCollapsed}
        onAgentChange={state.handleAgentChange}
        onThreadSelect={state.handleThreadSelect}
        onNewChat={state.handleNewConversation}
        onToggleCollapse={() => state.setSidebarCollapsed((prev) => !prev)}
      />

      {/* Main area + artifacts panel */}
      <div className='flex min-w-0 flex-1 min-h-0'>
        <div className='flex min-w-0 flex-1 flex-col bg-[var(--control-panel)]'>
          {/* Top bar */}
          <div
            className='flex shrink-0 items-center justify-between px-20px py-10px'
            style={{
              borderBottom: '1px solid var(--control-border)',
              background: 'rgba(0,240,255,0.02)',
            }}
          >
            <div className='flex items-center gap-10px'>
              <div
                className='w-28px h-28px rd-8px flex-center shrink-0'
                style={{ background: 'rgba(0,240,255,0.08)' }}
              >
                <RobotOne size={16} fill={[CYAN]} />
              </div>
              <Typography.Text className='font-semibold text-[var(--control-text)]'>
                {state.selectedAgentName || 'No agent selected'}
              </Typography.Text>
              {/* Tab switcher */}
              <SegmentedTabs
                value={state.activeTab}
                tabs={[
                  { value: 'chat', label: 'Chat' },
                  { value: 'runs', label: 'Runs' },
                ]}
                onChange={(value) => state.setActiveTab(value as 'chat' | 'runs')}
              />
              {/* Status chip */}
              <span
                className='flex items-center gap-5px rd-full px-8px py-2px text-11px font-semibold border border-solid'
                style={{
                  color: state.statusView.color,
                  borderColor: `${state.statusView.color}40`,
                  background: `${state.statusView.color}0a`,
                }}
              >
                <span className='inline-block w-6px h-6px rd-full' style={{ background: state.statusView.dot }} />
                {state.statusView.text}
              </span>
              {state.selectedThreadId ? (
                <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                  {state.selectedThreadId}
                </Typography.Text>
              ) : null}
            </div>
            <div className='flex items-center gap-6px'>
              {state.selectedThreadId && (state.artifactsQuery.data?.artifacts?.length ?? 0) > 0 ? (
                <Button
                  type='text'
                  size='mini'
                  className='control-quiet-icon-button'
                  icon={<FolderOpen theme='outline' size='16' fill={state.artifactsPanelOpen ? CYAN : 'var(--control-subtle)'} />}
                  onClick={() => state.setArtifactsPanelOpen((prev) => !prev)}
                />
              ) : null}
            </div>
          </div>

          {/* Main content area: Chat Tab or Runs Tab */}
          {showChat ? (
            <div className='min-h-0 flex-1 flex flex-col overflow-hidden'>
              {/* Snapshot banner */}
              {isSnapshot && state.snapshotView.active ? (
                <SnapshotBanner
                  runLabel={state.snapshotView.runLabel}
                  onBackToLatest={state.clearSnapshot}
                />
              ) : null}

              {/* Message area */}
              <div className='min-h-0 flex-1 overflow-hidden'>
                {state.messagesQuery.isLoading && !state.runActive ? (
                  <div className='flex h-full items-center justify-center'>
                    <Spin />
                  </div>
                ) : timelineItems.length === 0 ? (
                  <div className='flex h-full flex-col items-center justify-center gap-16px px-24px'>
                    <div
                      className='w-56px h-56px rd-14px flex-center'
                      style={{ background: 'rgba(0,240,255,0.08)', border: '1px solid rgba(0,240,255,0.18)' }}
                    >
                      <RobotOne theme='outline' size='28' fill={CYAN} />
                    </div>
                    <Typography.Text className='text-16px font-semibold text-[var(--control-text)]'>
                      {state.selectedAgentName ? 'Start a new conversation' : 'Select an agent to begin'}
                    </Typography.Text>
                    <Typography.Text className='text-center text-13px text-[var(--control-subtle)]'>
                      {state.selectedAgentName
                        ? 'Type a message below to get started.'
                        : 'Choose an agent from the sidebar, then start chatting.'}
                    </Typography.Text>
                  </div>
                ) : (
                  <div
                    ref={state.timelineViewportRef}
                    className='control-scroll flex h-full min-h-0 flex-col gap-16px overflow-auto px-24px py-16px'
                  >
                    <div className='flex w-full flex-col gap-12px'>
                      {timelineItems.map((item) => (
                        <div key={item.id}>
                          {renderTimelineItem(item, {
                            pendingInterrupts: state.runtimeState.pendingInterrupts,
                            onSubmitDecision: (interrupt, type) => { void state.submitInterruptDecision(interrupt, type); },
                          })}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Composer - hidden in snapshot mode */}
              {!hideComposer ? (
                <ChatComposer
                  composerValue={state.composerValue}
                  runStatus={state.runtimeState.runStatus}
                  selectedAgentName={state.selectedAgentName}
                  uploadingFiles={state.uploadingFiles}
                  uploadedWorkspaceFiles={state.uploadedWorkspaceFiles}
                  runSessionId={state.runSessionId}
                  fileInputRef={state.fileInputRef}
                  onComposerChange={state.setComposerValue}
                  onSend={() => { void state.startRun(); }}
                  onCancel={() => { void state.cancelRun(); }}
                  onUploadClick={state.openWorkspaceUploadPicker}
                  onFilesSelected={(e) => { void state.handleWorkspaceFilesSelected(e); }}
                />
              ) : null}
            </div>
          ) : null}

          {showRuns ? (
            <div className='min-h-0 flex-1 overflow-hidden'>
              {state.selectedAgentName && state.selectedThreadId ? (
                <RunsView
                  agentName={state.selectedAgentName}
                  threadId={state.selectedThreadId}
                  liveRunId={state.currentRunId}
                  liveEvents={state.liveEvents}
                  selectedRunId={state.selectedRunId}
                  onSelectRun={state.selectRun}
                  onViewSnapshot={(runId, runLabel) => { void state.loadSnapshot(runId, runLabel); }}
                />
              ) : (
                <div className='flex h-full items-center justify-center'>
                  <Typography.Text className='text-13px text-[var(--control-subtle)]'>
                    Select a conversation to view Run history
                  </Typography.Text>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Artifacts panel */}
        {state.artifactsPanelOpen && state.selectedAgentName && state.selectedThreadId ? (
          <ArtifactsPanel
            agentName={state.selectedAgentName}
            threadId={state.selectedThreadId}
            artifacts={state.artifactsQuery.data?.artifacts ?? []}
            loading={state.artifactsQuery.isLoading}
            onClose={() => state.setArtifactsPanelOpen(false)}
          />
        ) : null}
      </div>
    </div>
  );
}
