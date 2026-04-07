import type { HTTPTelemetryStepDTO } from '@/shared/types/api';

export type TelemetryEventVM = {
  id: string;
  runId?: string;
  agentName?: string;
  timestamp?: string;
  namespace: string[];
  streamMode: string;
  eventType: string;
  metadata?: unknown;
  payload?: unknown;
  publicEvent?: {
    type?: string;
    text?: string;
    thread_id?: string;
    tool_name?: string;
    tool_call_id?: string;
    reason?: string;
  };
};

export type TraceSpanStatus = 'running' | 'completed' | 'failed' | 'interrupted' | 'observed';

export type TraceSpanVM = {
  id: string;
  parentStepId?: string;
  kind: string;
  nodeName: string;
  namespace: string[];
  depth: number;
  status: TraceSpanStatus;
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
  step?: number;
  input?: unknown;
  output?: unknown;
  error?: string;
  triggers: string[];
  reasoning: string[];
  messages: string[];
  updates: unknown[];
  custom: unknown[];
  events: TelemetryEventVM[];
  relatedEventIDs: string[];
  order: number;
  synthetic: boolean;
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function parseDate(value?: string): number | undefined {
  if (!value) return undefined;
  const time = Date.parse(value);
  return Number.isNaN(time) ? undefined : time;
}

function namespaceLabel(namespace: string[]): string {
  return namespace.length > 0 ? namespace.join(' / ') : 'root';
}

function lastNamespaceSegment(namespace: string[]): string | undefined {
  const raw = namespace.at(-1);
  if (!raw) return undefined;
  const [, tail] = raw.split(':');
  return tail || raw;
}

function traceNodeName(event: TelemetryEventVM): string {
  if (event.streamMode === 'lifecycle') return 'run';
  const metadata = asRecord(event.metadata);
  const payload = asRecord(event.payload);
  return (
    asString(metadata?.langgraph_node)
    ?? asString(payload?.name)
    ?? asString(event.publicEvent?.tool_name)
    ?? lastNamespaceSegment(event.namespace)
    ?? 'root'
  );
}

function traceStep(event: TelemetryEventVM): number | undefined {
  const metadata = asRecord(event.metadata);
  return asNumber(metadata?.langgraph_step) ?? asNumber(metadata?.step);
}

function traceNamespaceKey(namespace: string[], nodeName: string): string {
  return `${namespaceLabel(namespace)}::${nodeName}`;
}

type ReasoningChunk = {
  key: string;
  text: string;
};

function reasoningChunks(payload: unknown): ReasoningChunk[] {
  const record = asRecord(payload);
  if (!record) return [];

  const blockID = asString(record.id) ?? String(asNumber(record.index) ?? 'root');
  const summary = record.summary;
  if (Array.isArray(summary)) {
    return summary
      .map((item, index) => {
        const summaryItem = asRecord(item);
        const text = asString(summaryItem?.text);
        if (!text) return undefined;
        const itemIndex = asNumber(summaryItem?.index) ?? index;
        return {
          key: `summary:${blockID}:${itemIndex}`,
          text,
        };
      })
      .filter((value): value is ReasoningChunk => Boolean(value));
  }

  const reasoning = asString(record.reasoning);
  return reasoning ? [{ key: `reasoning:${blockID}`, text: reasoning }] : [];
}

function appendReasoning(span: TraceSpanVM, payload: unknown, indexByKey: Map<string, number>): void {
  for (const chunk of reasoningChunks(payload)) {
    const existingIndex = indexByKey.get(chunk.key);
    if (existingIndex === undefined) {
      indexByKey.set(chunk.key, span.reasoning.length);
      span.reasoning.push(chunk.text);
      continue;
    }
    span.reasoning[existingIndex] = `${span.reasoning[existingIndex]}${chunk.text}`;
  }
}

function reasoningIndex(indexBySpan: Map<string, Map<string, number>>, spanID: string): Map<string, number> {
  const existing = indexBySpan.get(spanID);
  if (existing) return existing;
  const created = new Map<string, number>();
  indexBySpan.set(spanID, created);
  return created;
}

function textPayload(payload: unknown): string | undefined {
  const record = asRecord(payload);
  if (!record) return undefined;
  return asString(record.text) ?? asString(record.content) ?? asString(record.name);
}

function makeSyntheticSpan(event: TelemetryEventVM, nodeName: string, order: number): TraceSpanVM {
  return {
    id: `trace-${event.id}`,
    kind: event.streamMode === 'lifecycle' ? 'run' : 'node',
    nodeName,
    namespace: event.namespace,
    depth: event.namespace.length,
    status: event.streamMode === 'lifecycle' ? 'running' : 'observed',
    startedAt: event.timestamp,
    triggers: [],
    reasoning: [],
    messages: [],
    updates: [],
    custom: [],
    events: [],
    relatedEventIDs: [],
    order,
    synthetic: true,
  };
}

function finalizeStatus(span: TraceSpanVM, event: TelemetryEventVM, payload: Record<string, unknown> | undefined) {
  if (event.eventType === 'error') {
    span.status = 'failed';
    span.error = asString(payload?.error) ?? asString(payload?.message) ?? span.error;
    span.finishedAt = event.timestamp ?? span.finishedAt;
    return;
  }

  if (event.eventType === 'task_result') {
    span.finishedAt = event.timestamp ?? span.finishedAt;
    span.error = asString(payload?.error) ?? span.error;
    span.output = payload?.result ?? span.output;
    const interrupts = payload?.interrupts;
    if (span.error) {
      span.status = 'failed';
    } else if (Array.isArray(interrupts) && interrupts.length > 0) {
      span.status = 'interrupted';
    } else {
      span.status = 'completed';
    }
    return;
  }

  if (event.eventType === 'run_ended') {
    span.status = span.status === 'failed' ? span.status : 'completed';
    span.finishedAt = event.timestamp ?? span.finishedAt;
    return;
  }

  if (event.eventType === 'run_canceled') {
    span.status = 'interrupted';
    span.finishedAt = event.timestamp ?? span.finishedAt;
  }
}

export function buildTraceSpans(events: TelemetryEventVM[]): TraceSpanVM[] {
  const spans: TraceSpanVM[] = [];
  const spanByID = new Map<string, TraceSpanVM>();
  const activeTaskToSpan = new Map<string, string>();
  const latestByNode = new Map<string, string>();
  const reasoningIndexBySpan = new Map<string, Map<string, number>>();

  const sorted = [...events].sort((left, right) => {
    const lt = parseDate(left.timestamp) ?? Number.MAX_SAFE_INTEGER;
    const rt = parseDate(right.timestamp) ?? Number.MAX_SAFE_INTEGER;
    if (lt !== rt) return lt - rt;
    return left.id.localeCompare(right.id);
  });

  for (const event of sorted) {
    const nodeName = traceNodeName(event);
    const payload = asRecord(event.payload);
    const taskID = asString(payload?.id);
    let span: TraceSpanVM | undefined;

    if (event.eventType === 'task' && taskID) {
      span = {
        id: `trace-task-${taskID}`,
        kind: 'node',
        nodeName: asString(payload?.name) ?? nodeName,
        namespace: event.namespace,
        depth: event.namespace.length,
        status: 'running',
        startedAt: event.timestamp,
        step: traceStep(event),
        input: payload?.input,
        triggers: Array.isArray(payload?.triggers)
          ? payload.triggers.map((value) => String(value))
          : [],
        reasoning: [],
        messages: [],
        updates: [],
        custom: [],
        events: [],
        relatedEventIDs: [],
        order: spans.length,
        synthetic: false,
      };
      spans.push(span);
      spanByID.set(span.id, span);
      reasoningIndexBySpan.set(span.id, new Map());
      activeTaskToSpan.set(taskID, span.id);
      latestByNode.set(traceNamespaceKey(event.namespace, span.nodeName), span.id);
    } else if (event.eventType === 'task_result' && taskID) {
      const spanID = activeTaskToSpan.get(taskID);
      span = spanID ? spanByID.get(spanID) : undefined;
    } else {
      const spanID = latestByNode.get(traceNamespaceKey(event.namespace, nodeName));
      span = spanID ? spanByID.get(spanID) : undefined;
      if (!span) {
        span = makeSyntheticSpan(event, nodeName, spans.length);
        spans.push(span);
        spanByID.set(span.id, span);
        reasoningIndexBySpan.set(span.id, new Map());
        latestByNode.set(traceNamespaceKey(event.namespace, nodeName), span.id);
      }
    }

    if (!span) continue;

    span.events.push(event);
    span.relatedEventIDs.push(event.id);
    span.step = span.step ?? traceStep(event);

    if (event.eventType === 'reasoning') {
      appendReasoning(
        span,
        event.payload,
        reasoningIndex(reasoningIndexBySpan, span.id),
      );
    }

    const text = textPayload(event.payload) ?? asString(event.publicEvent?.text);
    if (text && (event.eventType === 'text' || event.eventType === 'text_done' || event.eventType === 'tool_result')) {
      span.messages.push(text);
    }

    if (event.eventType === 'state_update') {
      span.updates.push(event.payload);
    }
    if (event.eventType === 'custom') {
      span.custom.push(event.payload);
    }

    if (!span.input && event.eventType === 'task') {
      span.input = payload?.input;
    }

    finalizeStatus(span, event, payload);

    if (!span.synthetic && span.finishedAt && taskID) {
      activeTaskToSpan.delete(taskID);
    }
  }

  for (const span of spans) {
    const start = parseDate(span.startedAt);
    const end = parseDate(span.finishedAt);
    if (start !== undefined && end !== undefined && end >= start) {
      span.durationMs = end - start;
    }
  }

  return spans.sort((left, right) => {
    const ls = parseDate(left.startedAt) ?? Number.MAX_SAFE_INTEGER;
    const rs = parseDate(right.startedAt) ?? Number.MAX_SAFE_INTEGER;
    if (ls !== rs) return ls - rs;
    if ((left.step ?? Number.MAX_SAFE_INTEGER) !== (right.step ?? Number.MAX_SAFE_INTEGER)) {
      return (left.step ?? Number.MAX_SAFE_INTEGER) - (right.step ?? Number.MAX_SAFE_INTEGER);
    }
    return left.order - right.order;
  });
}

export function buildTraceSpansFromSteps(
  steps: HTTPTelemetryStepDTO[],
  events: TelemetryEventVM[],
): TraceSpanVM[] {
  const eventByID = new Map(events.map((event) => [event.id, event]));

  return [...steps]
    .map((step, index) => {
      const relatedEventIDs = step.related_event_ids ?? [];
      const relatedEvents = relatedEventIDs
        .map((eventID) => eventByID.get(eventID))
        .filter((event): event is TelemetryEventVM => Boolean(event));
      const start = parseDate(step.started_at);
      const end = parseDate(step.finished_at);

      return {
        id: step.step_id ?? `telemetry-step-${index}`,
        parentStepId: step.parent_step_id,
        kind: step.kind ?? 'node',
        nodeName: step.title ?? 'step',
        namespace: step.namespace ?? [],
        depth: step.depth ?? ((step.namespace ?? []).length),
        status: (step.status as TraceSpanStatus | undefined) ?? 'observed',
        startedAt: step.started_at,
        finishedAt: step.finished_at,
        durationMs: start !== undefined && end !== undefined && end >= start ? end - start : undefined,
        step: step.step,
        input: step.input,
        output: step.output,
        error: step.error,
        triggers: step.triggers ?? [],
        reasoning: step.reasoning ?? [],
        messages: step.messages ?? [],
        updates: step.updates ?? [],
        custom: step.custom ?? [],
        events: relatedEvents,
        relatedEventIDs,
        order: step.order ?? index,
        synthetic: step.synthetic ?? false,
      } satisfies TraceSpanVM;
    })
    .sort((left, right) => {
      const ls = parseDate(left.startedAt) ?? Number.MAX_SAFE_INTEGER;
      const rs = parseDate(right.startedAt) ?? Number.MAX_SAFE_INTEGER;
      if (ls !== rs) return ls - rs;
      return left.order - right.order;
    });
}
