import type { TelemetryEventVM, TraceSpanVM } from '@/features/telemetry/traceModel';
import type {
  GraphEdgeVM,
  GraphFocusVM,
  GraphNodeVM,
} from '@/features/telemetry/graphModel';
import type {
  HTTPTelemetryEventDTO,
  HTTPActionRequestDTO,
  HTTPReviewConfigDTO,
  SessionMessageDTO,
} from '@/shared/types/api';

// ─── Color constants ───

export const CYAN = '#00f0ff';
export const GREEN = '#39ff14';
export const ORANGE = '#ff9f1a';
export const MAGENTA = '#ff2d95';
export const RED = '#ff3b5c';

// ─── Types ───

export type TelemetryStatus = 'idle' | 'starting' | 'streaming' | 'waiting_hitl' | 'canceling' | 'completed' | 'canceled' | 'failed';

export type PendingTelemetryInterrupt = {
  interruptId: string;
  actionRequests: HTTPActionRequestDTO[];
  reviewConfigs: HTTPReviewConfigDTO[];
};

export type SnapshotTab = 'after' | 'before';
export type TelemetryGroupMode = 'flat' | 'namespace' | 'stream_mode' | 'event_type';
export type TelemetryViewMode = 'trace' | 'graph' | 'debug';
export type TraceStatusFilter = 'all' | 'running' | 'completed' | 'failed' | 'interrupted' | 'observed';
export type TraceDetailTab = 'io' | 'reasoning' | 'events';
export type GraphDetailTab = 'data' | 'metadata' | 'trace';
export type DebugDetailTab = 'payload' | 'metadata' | 'public_event';
export type GraphPathDirection = 'focus' | 'upstream' | 'downstream' | 'muted' | 'default';
export type GraphNodePosition = { x: number; y: number };

// ─── Formatting / status helpers ───

export function formatTelemetryStatus(status: TelemetryStatus): { text: string; color: string } {
  switch (status) {
    case 'starting': return { text: 'starting', color: CYAN };
    case 'streaming': return { text: 'streaming', color: GREEN };
    case 'waiting_hitl': return { text: 'waiting', color: ORANGE };
    case 'canceling': return { text: 'canceling', color: ORANGE };
    case 'completed': return { text: 'completed', color: GREEN };
    case 'canceled': return { text: 'canceled', color: 'var(--control-subtle)' };
    case 'failed': return { text: 'failed', color: RED };
    default: return { text: 'idle', color: 'var(--control-subtle)' };
  }
}

export function telemetryStatusFromRun(status?: string): TelemetryStatus {
  switch ((status ?? '').trim()) {
    case 'running': return 'streaming';
    case 'completed': return 'completed';
    case 'canceled': return 'canceled';
    case 'failed': return 'failed';
    default: return 'idle';
  }
}

// ─── Event utilities ───

export function isTelemetryEvent(payload: unknown): payload is HTTPTelemetryEventDTO {
  return typeof payload === 'object' && payload !== null && ('event_type' in payload || 'stream_mode' in payload || 'public_event' in payload);
}

export function normalizeTelemetryEvent(
  payload: HTTPTelemetryEventDTO,
  fallbackId: string,
): TelemetryEventVM {
  return {
    id: payload.event_id ?? fallbackId,
    runId: payload.run_id ?? payload.public_event?.run_id,
    agentName: payload.agent_name ?? payload.public_event?.agent_name,
    timestamp: payload.timestamp ?? payload.public_event?.timestamp,
    namespace: payload.namespace ?? [],
    streamMode: payload.stream_mode ?? (payload.public_event ? 'lifecycle' : 'unknown'),
    eventType: payload.event_type ?? 'unknown',
    metadata: payload.metadata,
    payload: payload.payload,
    publicEvent: payload.public_event,
  };
}

// ─── String helpers ───

export function formatCompactDateTime(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : date.toLocaleString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function stringifyValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function truncate(value?: string, max = 72): string {
  if (!value) return '';
  return value.length <= max ? value : `${value.slice(0, max - 1)}...`;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

// ─── Event display helpers ───

export function summarizeEvent(event: TelemetryEventVM): string {
  const publicText = typeof event.publicEvent?.text === 'string' ? event.publicEvent.text : '';
  if (publicText.trim()) return truncate(publicText.trim());
  if (event.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)) {
    const payload = event.payload as Record<string, unknown>;
    if (typeof payload.content === 'string' && payload.content.trim()) return truncate(payload.content.trim());
    if (typeof payload.reason === 'string' && payload.reason.trim()) return truncate(payload.reason.trim());
    if (typeof payload.name === 'string') return truncate(payload.name);
  }
  return truncate(event.eventType.replaceAll('_', ' '));
}

export function eventAccent(event: TelemetryEventVM): string {
  switch (event.streamMode) {
    case 'messages': return CYAN;
    case 'updates': return ORANGE;
    case 'debug': return MAGENTA;
    case 'custom': return GREEN;
    case 'lifecycle': return event.eventType === 'error' ? RED : CYAN;
    default: return 'var(--control-subtle)';
  }
}

export function namespaceLabel(event: TelemetryEventVM): string {
  return event.namespace.length > 0 ? event.namespace.join(' / ') : 'root';
}

// ─── Trace helpers ───

export function traceAccent(status: TraceSpanVM['status']): string {
  switch (status) {
    case 'running': return CYAN;
    case 'completed': return GREEN;
    case 'failed': return RED;
    case 'interrupted': return ORANGE;
    default: return MAGENTA;
  }
}

export function traceStatusLabel(status: TraceSpanVM['status']): string {
  return status === 'observed' ? 'observed' : status;
}

export function traceNamespaceLabel(span: TraceSpanVM): string {
  return span.namespace.length > 0 ? span.namespace.join(' / ') : 'root';
}

export function traceSummary(span: TraceSpanVM): string {
  if (span.error) return truncate(span.error);
  // Filter out meaningless single-char messages like "?"
  const lastMessage = span.messages.at(-1);
  if (lastMessage && lastMessage.trim().length > 1) return truncate(lastMessage);
  // Prefer full joined reasoning over single fragment
  if (span.reasoning.length > 0) {
    const fullReasoning = span.reasoning.join('').trim();
    if (fullReasoning.length > 1) return truncate(fullReasoning);
  }
  if (typeof span.output === 'string' && span.output.trim()) return truncate(span.output);
  if (typeof span.input === 'string' && span.input.trim()) return truncate(span.input);
  return truncate(`${span.nodeName} ${span.synthetic ? 'observed' : 'executed'}`);
}

export function traceDurationLabel(span: TraceSpanVM): string {
  if (span.durationMs === undefined) return span.status === 'running' ? 'live' : '-';
  if (span.durationMs < 1000) return `${span.durationMs}ms`;
  return `${(span.durationMs / 1000).toFixed(2)}s`;
}

export function traceReasoningMarkdown(span: TraceSpanVM): string | undefined {
  const text = span.reasoning.join(' ').trim();
  return text || undefined;
}

// ─── Graph helpers ───

export function graphNodeRelatedSpans(node: GraphNodeVM, spans: TraceSpanVM[]): TraceSpanVM[] {
  const relatedIDs = new Set(node.relatedSpanIDs);
  return spans.filter((span) => relatedIDs.has(span.id));
}

export function graphNodeStatus(node: GraphNodeVM, spans: TraceSpanVM[]): TraceSpanVM['status'] {
  const related = graphNodeRelatedSpans(node, spans);
  if (related.some((span) => span.status === 'failed')) return 'failed';
  if (related.some((span) => span.status === 'running')) return 'running';
  if (related.some((span) => span.status === 'interrupted')) return 'interrupted';
  if (related.some((span) => span.status === 'completed')) return 'completed';
  return 'observed';
}

export function graphNodeSummary(node: GraphNodeVM, spans: TraceSpanVM[]): string {
  const related = graphNodeRelatedSpans(node, spans);
  if (related.length === 0) {
    if (node.isCluster) return truncate(`${node.memberCount} nodes inside ${node.graphID}`);
    return truncate(node.label);
  }
  const failed = related.find((span) => span.status === 'failed');
  if (failed?.error) return truncate(failed.error);
  const completed = related.find((span) => span.messages.length > 0 || span.reasoning.length > 0);
  if (completed) return traceSummary(completed);
  return truncate(`${related.length} related span${related.length === 1 ? '' : 's'}`);
}

export function graphNodeScopeLabel(node: GraphNodeVM): string {
  if (node.isCluster) return node.graphID;
  return node.clusterAncestors.length > 0 ? node.clusterAncestors.join(' / ') : 'root';
}

export function graphNodeBadgeTone(state: GraphPathDirection): { border: string; glow?: string; opacity: number } {
  switch (state) {
    case 'focus':
      return { border: `${MAGENTA}55`, glow: `0 0 16px ${MAGENTA}24`, opacity: 1 };
    case 'upstream':
      return { border: `${ORANGE}55`, glow: `0 0 16px ${ORANGE}18`, opacity: 1 };
    case 'downstream':
      return { border: `${CYAN}55`, glow: `0 0 16px ${CYAN}18`, opacity: 1 };
    case 'muted':
      return { border: 'rgba(0,240,255,0.06)', opacity: 0.38 };
    default:
      return { border: 'rgba(0,240,255,0.08)', opacity: 1 };
  }
}

export function graphEdgeTone(edge: GraphEdgeVM, focus: GraphFocusVM): { stroke: string; opacity: number; width: number } {
  if (!focus.nodeID) {
    return { stroke: 'rgba(0,240,255,0.18)', opacity: 1, width: 1.5 };
  }
  if (focus.upstreamEdgeIDs.has(edge.id) && focus.downstreamEdgeIDs.has(edge.id)) {
    return { stroke: MAGENTA, opacity: 1, width: 2.6 };
  }
  if (focus.upstreamEdgeIDs.has(edge.id)) {
    return { stroke: ORANGE, opacity: 1, width: 2.4 };
  }
  if (focus.downstreamEdgeIDs.has(edge.id)) {
    return { stroke: CYAN, opacity: 1, width: 2.4 };
  }
  return { stroke: 'rgba(0,240,255,0.12)', opacity: 0.28, width: 1.2 };
}

export function graphNodePathState(node: GraphNodeVM, focus: GraphFocusVM): GraphPathDirection {
  if (!focus.nodeID) return 'default';
  if (node.id === focus.nodeID) return 'focus';
  if (focus.upstreamNodeIDs.has(node.id)) return 'upstream';
  if (focus.downstreamNodeIDs.has(node.id)) return 'downstream';
  return 'muted';
}

// ─── Layout helpers ───

export function lineClampStyle(lines: number): React.CSSProperties {
  return {
    display: '-webkit-box',
    WebkitLineClamp: lines,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  };
}

// ─── Group / collection helpers ───

export function groupLabel(event: TelemetryEventVM, groupBy: TelemetryGroupMode): string {
  switch (groupBy) {
    case 'namespace': return namespaceLabel(event);
    case 'stream_mode': return event.streamMode;
    case 'event_type': return event.eventType;
    default: return 'all events';
  }
}

export function collectInterrupt(
  payload: unknown,
  fallback?: HTTPTelemetryEventDTO['public_event'],
): PendingTelemetryInterrupt | null {
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    const value = payload as Record<string, unknown>;
    if (typeof value.interrupt_id === 'string') {
      return {
        interruptId: value.interrupt_id,
        actionRequests: Array.isArray(value.action_requests) ? value.action_requests as HTTPActionRequestDTO[] : [],
        reviewConfigs: Array.isArray(value.review_configs) ? value.review_configs as HTTPReviewConfigDTO[] : [],
      };
    }
  }
  if (fallback?.type === 'hitl_request' && typeof fallback.interrupt_id === 'string') {
    return {
      interruptId: fallback.interrupt_id,
      actionRequests: fallback.action_requests ?? [],
      reviewConfigs: fallback.review_configs ?? [],
    };
  }
  return null;
}

// ─── Snapshot helpers ───

export function snapshotRoleColor(role?: string): 'green' | 'arcoblue' | 'purple' | 'orange' {
  switch ((role ?? '').toLowerCase()) {
    case 'human': return 'green';
    case 'ai': return 'arcoblue';
    case 'tool': return 'orange';
    default: return 'purple';
  }
}

export function snapshotMessageText(message: SessionMessageDTO): string {
  return (message.content ?? message.text ?? '').trim() || '(empty)';
}
