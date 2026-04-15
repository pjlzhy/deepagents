import type {
  HTTPActionRequestDTO,
  HTTPAgentEventDTO,
  HTTPReviewConfigDTO,
  HTTPTelemetryEventDTO,
  SessionMessageDTO,
} from '@/shared/types/api';
import { v4 as uuidv4 } from 'uuid';

export type RunStatusVM =
  | 'idle'
  | 'starting'
  | 'streaming'
  | 'waiting_hitl'
  | 'canceling'
  | 'completed'
  | 'canceled'
  | 'failed';

export type TimelineItemVM =
  | {
      kind: 'user_message';
      id: string;
      text: string;
      createdAt?: string;
    }
  | {
      kind: 'assistant_message';
      id: string;
      text: string;
      createdAt?: string;
    }
  | {
      kind: 'assistant_draft';
      id: string;
      text: string;
      createdAt?: string;
    }
  | {
      kind: 'tool_event';
      id: string;
      toolCallId?: string;
      toolName?: string;
      phase: 'start' | 'done' | 'result';
      text?: string;
      isError?: boolean;
      payload?: unknown;
      createdAt?: string;
    }
  | {
      kind: 'hitl_request';
      id: string;
      interruptId: string;
      title: string;
      actionRequests: HTTPActionRequestDTO[];
      reviewConfigs: HTTPReviewConfigDTO[];
      createdAt?: string;
    }
  | {
      kind: 'system_event';
      id: string;
      event: 'run_started' | 'run_ended' | 'run_canceled' | 'error';
      message?: string;
      createdAt?: string;
    };

export type ConversationTimelineItemVM =
  | Extract<TimelineItemVM, { kind: 'user_message' | 'assistant_message' | 'assistant_draft' | 'hitl_request' | 'system_event' }>
  | {
      kind: 'assistant_tool_call';
      id: string;
      toolCallId?: string;
      toolName?: string;
      arguments?: unknown;
      output?: string;
      isError?: boolean;
      status: 'running' | 'completed';
      createdAt?: string;
      updatedAt?: string;
    };

export type PendingInterruptVM = {
  interruptId: string;
  title: string;
  actionRequests: HTTPActionRequestDTO[];
  reviewConfigs: HTTPReviewConfigDTO[];
};

export type RuntimeState = {
  runStatus: RunStatusVM;
  timeline: TimelineItemVM[];
  pendingInterrupts: PendingInterruptVM[];
};

const draftItemId = 'assistant-draft';

function createId(prefix: string): string {
  return `${prefix}-${uuidv4()}`;
}

function finalizeDraft(timeline: TimelineItemVM[], fallbackText?: string, createdAt?: string): TimelineItemVM[] {
  const draft = timeline.find((item) => item.kind === 'assistant_draft');
  const nextTimeline = timeline.filter((item) => item.kind !== 'assistant_draft');
  const text = fallbackText ?? draft?.text ?? '';
  if (!text.trim()) {
    return nextTimeline;
  }
  return [
    ...nextTimeline,
    {
      kind: 'assistant_message',
      id: createId('assistant'),
      text,
      createdAt,
    },
  ];
}

function upsertDraft(timeline: TimelineItemVM[], textFragment: string): TimelineItemVM[] {
  const nextTimeline = [...timeline];
  const existingIndex = nextTimeline.findIndex((item) => item.kind === 'assistant_draft');
  if (existingIndex >= 0) {
    const existing = nextTimeline[existingIndex];
    if (existing.kind === 'assistant_draft') {
      nextTimeline[existingIndex] = {
        ...existing,
        text: `${existing.text}${textFragment}`,
      };
    }
    return nextTimeline;
  }

  return [
    ...nextTimeline,
    {
      kind: 'assistant_draft',
      id: draftItemId,
      text: textFragment,
    },
  ];
}

function removeInterrupt(pendingInterrupts: PendingInterruptVM[], interruptId: string): PendingInterruptVM[] {
  return pendingInterrupts.filter((item) => item.interruptId !== interruptId);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function extractToolArguments(item: Extract<TimelineItemVM, { kind: 'tool_event' }>): unknown {
  if (item.phase === 'start') {
    return item.payload;
  }
  if (isRecord(item.payload) && 'args' in item.payload) {
    return item.payload.args;
  }
  return undefined;
}

function createAssistantToolCall(item: Extract<TimelineItemVM, { kind: 'tool_event' }>): Extract<ConversationTimelineItemVM, { kind: 'assistant_tool_call' }> {
  return {
    kind: 'assistant_tool_call',
    id: createId('assistant-tool'),
    toolCallId: item.toolCallId,
    toolName: item.toolName,
    arguments: extractToolArguments(item),
    output: item.text?.trim() || undefined,
    isError: item.isError,
    status: item.phase === 'result' ? 'completed' : 'running',
    createdAt: item.createdAt,
    updatedAt: item.createdAt,
  };
}

function toolCallMatches(
  toolCall: Extract<ConversationTimelineItemVM, { kind: 'assistant_tool_call' }>,
  event: Extract<TimelineItemVM, { kind: 'tool_event' }>,
): boolean {
  if (toolCall.toolCallId && event.toolCallId) {
    return toolCall.toolCallId === event.toolCallId;
  }

  if (!toolCall.toolCallId && !event.toolCallId && toolCall.toolName && event.toolName) {
    return toolCall.toolName === event.toolName && toolCall.status !== 'completed';
  }

  return false;
}

export function createConversationTimeline(timeline: TimelineItemVM[]): ConversationTimelineItemVM[] {
  const conversation: ConversationTimelineItemVM[] = [];

  for (const item of timeline) {
    if (item.kind === 'tool_event') {
      const lastItem = conversation.at(-1);
      if (lastItem?.kind === 'assistant_tool_call' && toolCallMatches(lastItem, item)) {
        const nextArguments = extractToolArguments(item);
        const nextOutput = item.text?.trim() || undefined;
        lastItem.toolCallId = lastItem.toolCallId ?? item.toolCallId;
        lastItem.toolName = lastItem.toolName ?? item.toolName;
        lastItem.arguments = lastItem.arguments ?? nextArguments;
        lastItem.output = nextOutput ?? lastItem.output;
        lastItem.isError = item.isError ?? lastItem.isError;
        lastItem.status = item.phase === 'result' ? 'completed' : lastItem.status;
        lastItem.updatedAt = item.createdAt ?? lastItem.updatedAt;
      } else {
        conversation.push(createAssistantToolCall(item));
      }
      continue;
    }

    conversation.push(item);
  }
  return conversation;
}

export function createRuntimeStateFromHistory(messages: SessionMessageDTO[]): RuntimeState {
  const timeline: TimelineItemVM[] = messages.map((message) => {
    const role = message.role?.toLowerCase();
    if (role === 'human') {
      return {
        kind: 'user_message',
        id: createId('history-user'),
        text: message.content ?? message.text ?? '',
        createdAt: message.created_at,
      };
    }
    if (role === 'tool') {
      return {
        kind: 'tool_event',
        id: createId('history-tool'),
        toolCallId: message.tool_call_id,
        toolName: message.tool_name,
        phase: 'result',
        text: message.content ?? message.text ?? '',
        isError: message.is_error,
        payload: message.raw,
        createdAt: message.created_at,
      };
    }
    return {
      kind: 'assistant_message',
      id: createId('history-assistant'),
      text: message.content ?? message.text ?? '',
      createdAt: message.created_at,
    };
  });

  return {
    runStatus: 'idle',
    timeline,
    pendingInterrupts: [],
  };
}

export function appendUserMessage(state: RuntimeState, text: string): RuntimeState {
  return {
    ...state,
    runStatus: 'starting',
    timeline: [
      ...state.timeline,
      {
        kind: 'user_message',
        id: createId('user'),
        text,
        createdAt: new Date().toISOString(),
      },
    ],
  };
}

export function markInterruptResolved(state: RuntimeState, interruptId: string): RuntimeState {
  return {
    ...state,
    runStatus: state.runStatus === 'waiting_hitl' ? 'streaming' : state.runStatus,
    pendingInterrupts: removeInterrupt(state.pendingInterrupts, interruptId),
  };
}

export function markRunCanceling(state: RuntimeState): RuntimeState {
  return {
    ...state,
    runStatus: 'canceling',
  };
}

export function reduceRuntimeEvent(state: RuntimeState, event: HTTPAgentEventDTO): RuntimeState {
  switch (event.type) {
    case 'run_started':
      return {
        ...state,
        runStatus: 'streaming',
        timeline: [
          ...state.timeline,
          {
            kind: 'system_event',
            id: createId('system'),
            event: 'run_started',
            message: event.thread_id ? `thread_id: ${event.thread_id}` : 'run started',
            createdAt: event.timestamp,
          },
        ],
      };
    case 'text_delta':
      return {
        ...state,
        runStatus: 'streaming',
        timeline: upsertDraft(state.timeline, event.text ?? ''),
      };
    case 'text_done':
      return {
        ...state,
        runStatus: 'streaming',
        timeline: finalizeDraft(state.timeline, event.text, event.timestamp),
      };
    case 'tool_call_start':
      return {
        ...state,
        runStatus: 'streaming',
        timeline: [
          ...state.timeline,
          {
            kind: 'tool_event',
            id: createId('tool'),
            toolCallId: event.tool_call_id,
            toolName: event.tool_name,
            phase: 'start',
            payload: event.payload,
            createdAt: event.timestamp,
          },
        ],
      };
    case 'tool_call_done':
      return {
        ...state,
        runStatus: 'streaming',
        timeline: [
          ...state.timeline,
          {
            kind: 'tool_event',
            id: createId('tool'),
            toolCallId: event.tool_call_id,
            toolName: event.tool_name,
            phase: 'done',
            payload: event.payload,
            createdAt: event.timestamp,
          },
        ],
      };
    case 'tool_result':
      return {
        ...state,
        runStatus: 'streaming',
        timeline: [
          ...state.timeline,
          {
            kind: 'tool_event',
            id: createId('tool'),
            toolCallId: event.tool_call_id,
            toolName: event.tool_name,
            phase: 'result',
            text: event.text,
            payload: event.payload,
            createdAt: event.timestamp,
          },
        ],
      };
    case 'hitl_request': {
      const interruptId = event.interrupt_id ?? createId('interrupt');
      const title =
        event.action_requests?.map((action) => action.name).join(', ') || 'human approval required';
      const pendingItem: PendingInterruptVM = {
        interruptId,
        title,
        actionRequests: event.action_requests ?? [],
        reviewConfigs: event.review_configs ?? [],
      };
      return {
        ...state,
        runStatus: 'waiting_hitl',
        pendingInterrupts: [...state.pendingInterrupts, pendingItem],
        timeline: [
          ...state.timeline,
          {
            kind: 'hitl_request',
            id: createId('hitl'),
            interruptId,
            title,
            actionRequests: event.action_requests ?? [],
            reviewConfigs: event.review_configs ?? [],
            createdAt: event.timestamp,
          },
        ],
      };
    }
    case 'run_ended':
      return {
        ...state,
        runStatus: 'completed',
        pendingInterrupts: [],
        timeline: [
          ...finalizeDraft(state.timeline, event.text, event.timestamp),
          {
            kind: 'system_event',
            id: createId('system'),
            event: 'run_ended',
            message: 'run ended',
            createdAt: event.timestamp,
          },
        ],
      };
    case 'run_canceled':
      return {
        ...state,
        runStatus: 'canceled',
        pendingInterrupts: [],
        timeline: [
          ...finalizeDraft(state.timeline, undefined, event.timestamp),
          {
            kind: 'system_event',
            id: createId('system'),
            event: 'run_canceled',
            message: event.reason ?? 'run canceled',
            createdAt: event.timestamp,
          },
        ],
      };
    case 'error':
      return {
        ...state,
        runStatus: 'failed',
        pendingInterrupts: [],
        timeline: [
          ...finalizeDraft(state.timeline, undefined, event.timestamp),
          {
            kind: 'system_event',
            id: createId('system'),
            event: 'error',
            message: event.error_message ?? 'runtime error',
            createdAt: event.timestamp,
          },
        ],
      };
    default:
      return state;
  }
}

export function telemetryEventToRuntimeEvent(event: HTTPTelemetryEventDTO): HTTPAgentEventDTO | null {
  const fallbackType = event.event_type?.trim();
  if (!fallbackType) {
    return null;
  }

  const payload = (
    typeof event.payload === 'object' && event.payload !== null && !Array.isArray(event.payload)
      ? event.payload as Record<string, unknown>
      : undefined
  );

  const payloadText = typeof payload?.text === 'string'
    ? payload.text
    : typeof payload?.content === 'string'
      ? payload.content
      : undefined;
  const toolName = typeof event.node_name === 'string' && event.node_name.trim()
    ? event.node_name
    : typeof payload?.tool_name === 'string'
      ? payload.tool_name
      : undefined;
  const toolCallId = typeof event.tool_call_id === 'string' && event.tool_call_id.trim()
    ? event.tool_call_id
    : typeof payload?.tool_call_id === 'string'
      ? payload.tool_call_id
      : undefined;

  switch (fallbackType) {
    case 'run_started':
      return {
        type: 'run_started',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        thread_id: event.thread_id ?? (typeof payload?.thread_id === 'string' ? payload.thread_id : undefined),
      };
    case 'text':
      return {
        type: 'text_delta',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        text: payloadText,
      };
    case 'text_done':
      return {
        type: 'text_done',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        text: payloadText,
      };
    case 'tool_call_start':
      return {
        type: 'tool_call_start',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        tool_name: toolName,
        tool_call_id: toolCallId,
        payload: payload?.args ?? event.payload,
      };
    case 'tool_call_done':
      return {
        type: 'tool_call_done',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        tool_name: toolName,
        tool_call_id: toolCallId,
      };
    case 'tool_result':
      return {
        type: 'tool_result',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        tool_name: toolName,
        tool_call_id: toolCallId,
        text: payloadText,
        payload: payload?.data ?? payload?.payload ?? event.payload,
      };
    case 'hitl_request':
      return {
        type: 'hitl_request',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        interrupt_id: typeof event.interrupt_id === 'string' && event.interrupt_id.trim()
          ? event.interrupt_id
          : typeof payload?.interrupt_id === 'string'
            ? payload.interrupt_id
            : undefined,
        action_requests: Array.isArray(payload?.action_requests) ? payload.action_requests as HTTPActionRequestDTO[] : [],
        review_configs: Array.isArray(payload?.review_configs) ? payload.review_configs as HTTPReviewConfigDTO[] : [],
      };
    case 'run_ended':
      return {
        type: 'run_ended',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
      };
    case 'run_canceled':
      return {
        type: 'run_canceled',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        reason: typeof payload?.reason === 'string' ? payload.reason : undefined,
      };
    case 'error':
      return {
        type: 'error',
        run_id: event.run_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        error_message: typeof payload?.message === 'string' ? payload.message : undefined,
      };
    default:
      return null;
  }
}
