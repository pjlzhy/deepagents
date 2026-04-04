import { Check, CloseOne, PlayOne, Server } from '@icon-park/react';
import { Button, Empty, Input, Message, Select, Spin, Tag, Typography } from '@arco-design/web-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import useSWR from 'swr';
import { useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { links } from '@/app/links';
import {
  buildGraphFocus,
  buildGraphModel,
  buildVisibleGraph,
  type GraphEdgeVM,
  type GraphFocusVM,
  type GraphNodeVM,
} from '@/features/telemetry/graphModel';
import { buildTraceSpans, type TelemetryEventVM, type TraceSpanVM } from '@/features/telemetry/traceModel';
import { controlClient } from '@/shared/api/controlClient';
import type {
  HTTPTelemetryEventDTO,
  HTTPActionRequestDTO,
  HTTPReviewConfigDTO,
} from '@/shared/types/api';
import '@/styles/registry-cards.css';

const CYAN = '#00f0ff';
const GREEN = '#39ff14';
const ORANGE = '#ff9f1a';
const MAGENTA = '#ff2d95';
const RED = '#ff3b5c';

const { TextArea } = Input;

type TelemetryStatus = 'idle' | 'starting' | 'streaming' | 'waiting_hitl' | 'canceling' | 'completed' | 'canceled' | 'failed';

type PendingTelemetryInterrupt = {
  interruptId: string;
  actionRequests: HTTPActionRequestDTO[];
  reviewConfigs: HTTPReviewConfigDTO[];
};

type TelemetryGroupMode = 'flat' | 'namespace' | 'stream_mode' | 'event_type';
type TelemetryViewMode = 'trace' | 'graph' | 'debug';
type TraceStatusFilter = 'all' | 'running' | 'completed' | 'failed' | 'interrupted' | 'observed';
type TraceDetailTab = 'io' | 'reasoning' | 'events';
type GraphDetailTab = 'data' | 'metadata' | 'trace';
type DebugDetailTab = 'payload' | 'metadata' | 'public_event';
type PaneDragTarget = 'left' | 'right';
type GraphPathDirection = 'focus' | 'upstream' | 'downstream' | 'muted' | 'default';
type GraphNodePosition = { x: number; y: number };

const GRAPH_BOARD_WIDTH = 5200;
const GRAPH_BOARD_HEIGHT = 3600;
const GRAPH_NODE_WIDTH = 250;
const GRAPH_NODE_HEIGHT = 132;
const GRAPH_COLUMN_GAP = 110;
const GRAPH_ROW_GAP = 32;
const GRAPH_ORIGIN_X = 180;
const GRAPH_ORIGIN_Y = 140;

function formatStatus(status: TelemetryStatus): { text: string; color: string } {
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

function isTelemetryEvent(payload: unknown): payload is HTTPTelemetryEventDTO {
  return typeof payload === 'object' && payload !== null && ('event_type' in payload || 'stream_mode' in payload || 'public_event' in payload);
}

function formatCompactDateTime(value?: string): string {
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

function stringifyValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function truncate(value?: string, max = 72): string {
  if (!value) return '';
  return value.length <= max ? value : `${value.slice(0, max - 1)}...`;
}

function sameStringList(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function summarizeEvent(event: TelemetryEventVM): string {
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

function eventAccent(event: TelemetryEventVM): string {
  switch (event.streamMode) {
    case 'messages': return CYAN;
    case 'updates': return ORANGE;
    case 'debug': return MAGENTA;
    case 'custom': return GREEN;
    case 'lifecycle': return event.eventType === 'error' ? RED : CYAN;
    default: return 'var(--control-subtle)';
  }
}

function namespaceLabel(event: TelemetryEventVM): string {
  return event.namespace.length > 0 ? event.namespace.join(' / ') : 'root';
}

function traceAccent(status: TraceSpanVM['status']): string {
  switch (status) {
    case 'running': return CYAN;
    case 'completed': return GREEN;
    case 'failed': return RED;
    case 'interrupted': return ORANGE;
    default: return MAGENTA;
  }
}

function traceStatusLabel(status: TraceSpanVM['status']): string {
  return status === 'observed' ? 'observed' : status;
}

function traceNamespaceLabel(span: TraceSpanVM): string {
  return span.namespace.length > 0 ? span.namespace.join(' / ') : 'root';
}

function traceSummary(span: TraceSpanVM): string {
  if (span.error) return truncate(span.error);
  if (span.messages.length > 0) return truncate(span.messages.at(-1));
  if (typeof span.output === 'string' && span.output.trim()) return truncate(span.output);
  if (span.reasoning.length > 0) return truncate(span.reasoning.at(-1));
  if (typeof span.input === 'string' && span.input.trim()) return truncate(span.input);
  return truncate(`${span.nodeName} ${span.synthetic ? 'observed' : 'executed'}`);
}

function traceDurationLabel(span: TraceSpanVM): string {
  if (span.durationMs === undefined) return span.status === 'running' ? 'live' : '-';
  if (span.durationMs < 1000) return `${span.durationMs}ms`;
  return `${(span.durationMs / 1000).toFixed(2)}s`;
}

function traceReasoningMarkdown(span: TraceSpanVM): string | undefined {
  const text = span.reasoning.join('\n\n').trim();
  return text || undefined;
}

function graphNodeRelatedSpans(node: GraphNodeVM, spans: TraceSpanVM[]): TraceSpanVM[] {
  const relatedIDs = new Set(node.relatedSpanIDs);
  return spans.filter((span) => relatedIDs.has(span.id));
}

function graphNodeStatus(node: GraphNodeVM, spans: TraceSpanVM[]): TraceSpanVM['status'] {
  const related = graphNodeRelatedSpans(node, spans);
  if (related.some((span) => span.status === 'failed')) return 'failed';
  if (related.some((span) => span.status === 'running')) return 'running';
  if (related.some((span) => span.status === 'interrupted')) return 'interrupted';
  if (related.some((span) => span.status === 'completed')) return 'completed';
  return related.length > 0 ? 'observed' : 'observed';
}

function graphNodeSummary(node: GraphNodeVM, spans: TraceSpanVM[]): string {
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

function graphNodeScopeLabel(node: GraphNodeVM): string {
  if (node.isCluster) return node.graphID;
  return node.clusterAncestors.length > 0 ? node.clusterAncestors.join(' / ') : 'root';
}

function graphNodeBadgeTone(state: GraphPathDirection): { border: string; glow?: string; opacity: number } {
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

function graphEdgeTone(edge: GraphEdgeVM, focus: GraphFocusVM): { stroke: string; opacity: number; width: number } {
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

function graphNodePathState(node: GraphNodeVM, focus: GraphFocusVM): GraphPathDirection {
  if (!focus.nodeID) return 'default';
  if (node.id === focus.nodeID) return 'focus';
  if (focus.upstreamNodeIDs.has(node.id)) return 'upstream';
  if (focus.downstreamNodeIDs.has(node.id)) return 'downstream';
  return 'muted';
}

function lineClampStyle(lines: number): React.CSSProperties {
  return {
    display: '-webkit-box',
    WebkitLineClamp: lines,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  };
}

function buildGraphCanvasPositions(columns: Array<{ level: number; nodes: GraphNodeVM[] }>): Record<string, GraphNodePosition> {
  const positions: Record<string, GraphNodePosition> = {};
  for (const column of columns) {
    column.nodes.forEach((node, index) => {
      positions[node.id] = {
        x: GRAPH_ORIGIN_X + (column.level * (GRAPH_NODE_WIDTH + GRAPH_COLUMN_GAP)),
        y: GRAPH_ORIGIN_Y + (index * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP)),
      };
    });
  }
  return positions;
}

function graphCanvasBounds(positions: Record<string, GraphNodePosition>, nodes: GraphNodeVM[]): {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
} {
  if (nodes.length === 0) {
    return {
      minX: 0,
      minY: 0,
      maxX: GRAPH_NODE_WIDTH,
      maxY: GRAPH_NODE_HEIGHT,
    };
  }

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  for (const node of nodes) {
    const position = positions[node.id];
    if (!position) continue;
    minX = Math.min(minX, position.x);
    minY = Math.min(minY, position.y);
    maxX = Math.max(maxX, position.x + GRAPH_NODE_WIDTH);
    maxY = Math.max(maxY, position.y + GRAPH_NODE_HEIGHT);
  }

  return { minX, minY, maxX, maxY };
}

function fitGraphCanvasTransform(
  positions: Record<string, GraphNodePosition>,
  nodes: GraphNodeVM[],
  viewportWidth: number,
  viewportHeight: number,
): { x: number; y: number; scale: number } {
  if (nodes.length === 0 || viewportWidth <= 0 || viewportHeight <= 0) {
    return { x: 0, y: 0, scale: 1 };
  }

  const bounds = graphCanvasBounds(positions, nodes);
  const padding = 80;
  const contentWidth = Math.max(240, bounds.maxX - bounds.minX);
  const contentHeight = Math.max(160, bounds.maxY - bounds.minY);
  const scale = clamp(
    Math.min(
      (viewportWidth - padding) / contentWidth,
      (viewportHeight - padding) / contentHeight,
      1.15,
    ),
    0.42,
    1.15,
  );

  return {
    x: ((viewportWidth - (contentWidth * scale)) / 2) - (bounds.minX * scale),
    y: ((viewportHeight - (contentHeight * scale)) / 2) - (bounds.minY * scale),
    scale,
  };
}

function graphCanvasEdgePath(
  positions: Record<string, GraphNodePosition>,
  edge: GraphEdgeVM,
): string | undefined {
  const source = positions[edge.source];
  const target = positions[edge.target];
  if (!source || !target) return undefined;

  const startX = source.x + GRAPH_NODE_WIDTH;
  const startY = source.y + (GRAPH_NODE_HEIGHT / 2);
  const endX = target.x;
  const endY = target.y + (GRAPH_NODE_HEIGHT / 2);
  const delta = Math.max(48, (endX - startX) * 0.45);

  return `M ${startX} ${startY} C ${startX + delta} ${startY}, ${endX - delta} ${endY}, ${endX} ${endY}`;
}

function groupLabel(event: TelemetryEventVM, groupBy: TelemetryGroupMode): string {
  switch (groupBy) {
    case 'namespace': return namespaceLabel(event);
    case 'stream_mode': return event.streamMode;
    case 'event_type': return event.eventType;
    default: return 'all events';
  }
}

function collectInterrupt(
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

function StatusPill(props: { status: TelemetryStatus }) {
  const view = formatStatus(props.status);
  return (
    <span
      className='rd-full px-8px py-2px text-11px font-bold uppercase tracking-wider border border-solid'
      style={{ color: view.color, borderColor: `${view.color}40`, background: `${view.color}10` }}
    >
      {view.text}
    </span>
  );
}

function SegmentedTabs(props: {
  value: string;
  tabs: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <div
      className='flex items-center gap-4px rd-full px-4px py-4px'
      style={{ border: '1px solid var(--control-border)', background: 'rgba(16,22,48,0.76)' }}
    >
      {props.tabs.map((tab) => (
        <Button
          key={tab.value}
          size='small'
          type={props.value === tab.value ? 'primary' : 'text'}
          className={props.value === tab.value ? '' : 'control-quiet-icon-button'}
          onClick={() => props.onChange(tab.value)}
        >
          {tab.label}
        </Button>
      ))}
    </div>
  );
}

function PaneHandle(props: { onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void }) {
  return (
    <div className='relative hidden xl:flex min-h-0 items-stretch justify-center'>
      <div
        role='separator'
        aria-orientation='vertical'
        className='group flex w-10px cursor-col-resize items-center justify-center'
        onPointerDown={props.onPointerDown}
      >
        <div
          className='h-full w-2px rd-full transition-colors duration-150'
          style={{ background: 'rgba(0,240,255,0.08)' }}
        />
        <div
          className='pointer-events-none absolute h-64px w-6px rd-full border border-solid opacity-0 transition-opacity duration-150 group-hover:opacity-100'
          style={{ borderColor: 'rgba(0,240,255,0.22)', background: 'rgba(0,240,255,0.08)' }}
        />
      </div>
    </div>
  );
}

function ScrollableViewport(props: {
  viewportRef?: React.MutableRefObject<HTMLDivElement | null>;
  viewportClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      ref={(node) => {
        if (props.viewportRef) props.viewportRef.current = node;
      }}
      className={`control-scroll control-scroll-strong min-h-0 h-full overflow-y-scroll overflow-x-hidden ${props.viewportClassName ?? ''}`}
    >
      <div className='min-h-full'>
        {props.children}
      </div>
    </div>
  );
}

function PendingApprovalBanner(props: {
  interrupts: PendingTelemetryInterrupt[];
  onSubmit: (interrupt: PendingTelemetryInterrupt, type: 'approve' | 'reject') => void;
}) {
  if (props.interrupts.length === 0) return null;

  return (
    <div className='control-card border-[rgba(255,159,26,0.22)] px-14px py-14px'>
      <div className='flex items-center justify-between gap-12px'>
        <div>
          <span className='block text-11px uppercase tracking-widest text-[var(--control-warning)]'>
            pending approvals ({props.interrupts.length})
          </span>
          <Typography.Text className='mt-4px block text-12px text-[var(--control-subtle)]'>
            The run is paused on HITL. Approve or reject here to resume telemetry streaming.
          </Typography.Text>
        </div>
        <Tag size='small' color='orange'>HITL</Tag>
      </div>
      <div className='mt-12px grid grid-cols-1 gap-10px xl:grid-cols-2'>
        {props.interrupts.map((interrupt) => (
          <div key={interrupt.interruptId} className='rd-10px bg-[rgba(255,159,26,0.06)] px-12px py-12px'>
            <div className='flex items-start justify-between gap-10px'>
              <div className='min-w-0'>
                <Typography.Text className='block text-12px font-semibold text-[var(--control-text)]'>
                  {interrupt.interruptId}
                </Typography.Text>
                <Typography.Text className='mt-4px block text-12px text-[var(--control-subtle)]'>
                  {interrupt.actionRequests.length > 0
                    ? `${interrupt.actionRequests.length} action${interrupt.actionRequests.length === 1 ? '' : 's'} awaiting review`
                    : 'approval required'}
                </Typography.Text>
              </div>
              <div className='flex shrink-0 gap-8px'>
                <Button
                  size='small'
                  status='danger'
                  icon={<CloseOne theme='outline' size='12' fill='currentColor' />}
                  onClick={() => props.onSubmit(interrupt, 'reject')}
                >
                  Reject
                </Button>
                <Button
                  size='small'
                  type='primary'
                  icon={<Check theme='outline' size='12' fill='currentColor' />}
                  onClick={() => props.onSubmit(interrupt, 'approve')}
                >
                  Approve
                </Button>
              </div>
            </div>
            <div className='mt-10px flex flex-col gap-6px'>
              {(interrupt.actionRequests.length > 0 ? interrupt.actionRequests : [{ name: 'approval_required' }]).map((action, index) => (
                <div
                  key={`${interrupt.interruptId}-${index}`}
                  className='rd-8px border border-solid px-10px py-8px'
                  style={{ borderColor: 'rgba(0,240,255,0.08)', background: 'rgba(10,14,30,0.56)' }}
                >
                  <div className='flex items-center gap-8px'>
                    <Tag size='small' color='arcoblue'>{action.name}</Tag>
                    {action.description ? (
                      <span className='text-12px text-[var(--control-subtle)]'>{truncate(action.description, 120)}</span>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function TelemetryPage() {
  const navigate = useNavigate();
  const params = useParams<{ agentName?: string }>();
  const selectedAgentName = params.agentName;
  const streamAbortRef = useRef<AbortController | null>(null);
  const nextEventIdRef = useRef(1);
  const paneLayoutRef = useRef<HTMLDivElement | null>(null);
  const paneDragStateRef = useRef<{
    target: PaneDragTarget;
    startX: number;
    startLeftWidth: number;
    startRightWidth: number;
  } | null>(null);
  const graphPointerStateRef = useRef<(
    | {
      type: 'pan';
      startClientX: number;
      startClientY: number;
      originX: number;
      originY: number;
    }
    | {
      type: 'node';
      nodeId: string;
      startClientX: number;
      startClientY: number;
      originX: number;
      originY: number;
    }
  ) | null>(null);
  const listViewportRef = useRef<HTMLDivElement | null>(null);
  const graphViewportRef = useRef<HTMLDivElement | null>(null);
  const graphClusterRef = useRef(new Set<string>());

  const [prompt, setPrompt] = useState('');
  const [status, setStatus] = useState<TelemetryStatus>('idle');
  const [runSessionId, setRunSessionId] = useState<string | undefined>(undefined);
  const [currentRunId, setCurrentRunId] = useState<string | undefined>(undefined);
  const [currentThreadId, setCurrentThreadId] = useState<string | undefined>(undefined);
  const [events, setEvents] = useState<TelemetryEventVM[]>([]);
  const [selectedEventId, setSelectedEventId] = useState<string | undefined>(undefined);
  const [selectedTraceId, setSelectedTraceId] = useState<string | undefined>(undefined);
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | undefined>(undefined);
  const [pendingInterrupts, setPendingInterrupts] = useState<PendingTelemetryInterrupt[]>([]);
  const [selectedModes, setSelectedModes] = useState<string[]>([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([]);
  const [namespaceFilter, setNamespaceFilter] = useState('');
  const [searchFilter, setSearchFilter] = useState('');
  const [groupBy, setGroupBy] = useState<TelemetryGroupMode>('namespace');
  const [viewMode, setViewMode] = useState<TelemetryViewMode>('trace');
  const [traceSearchFilter, setTraceSearchFilter] = useState('');
  const [traceStatusFilter, setTraceStatusFilter] = useState<TraceStatusFilter>('all');
  const [traceDetailTab, setTraceDetailTab] = useState<TraceDetailTab>('io');
  const [graphDetailTab, setGraphDetailTab] = useState<GraphDetailTab>('data');
  const [debugDetailTab, setDebugDetailTab] = useState<DebugDetailTab>('payload');
  const [leftPaneWidth, setLeftPaneWidth] = useState(280);
  const [rightPaneWidth, setRightPaneWidth] = useState(360);
  const [isDesktopLayout, setIsDesktopLayout] = useState<boolean>(() => (
    typeof window === 'undefined' ? true : window.innerWidth >= 1280
  ));
  const [collapsedClusterPaths, setCollapsedClusterPaths] = useState<string[]>([]);
  const [hoveredGraphNodeId, setHoveredGraphNodeId] = useState<string | undefined>(undefined);
  const [graphViewportSize, setGraphViewportSize] = useState({ width: 0, height: 0 });
  const [graphCanvasTransform, setGraphCanvasTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [graphNodePositions, setGraphNodePositions] = useState<Record<string, { x: number; y: number }>>({});

  const agentsQuery = useSWR('telemetry-agents', () => controlClient.agents.list({ pageSize: 100, pageNumber: 1 }));
  const graphQuery = useSWR(
    selectedAgentName ? ['telemetry-graph', selectedAgentName] : null,
    () => controlClient.agents.getGraph(selectedAgentName!, 2),
  );
  const deferredNamespaceFilter = useDeferredValue(namespaceFilter);
  const deferredSearchFilter = useDeferredValue(searchFilter);

  useEffect(() => {
    if (viewMode === 'graph') return;
    const viewport = listViewportRef.current;
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [events, viewMode]);

  useEffect(() => () => {
    streamAbortRef.current?.abort();
    stopPaneDrag();
    stopGraphPointerInteraction();
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const media = window.matchMedia('(min-width: 1280px)');
    const onChange = () => setIsDesktopLayout(media.matches);
    onChange();
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', onChange);
      return () => media.removeEventListener('change', onChange);
    }
    media.addListener(onChange);
    return () => media.removeListener(onChange);
  }, []);

  useEffect(() => {
    if (isDesktopLayout) return;
    paneDragStateRef.current = null;
  }, [isDesktopLayout]);

  const agentOptions = useMemo(
    () => (agentsQuery.data?.agents ?? []).map((item) => ({ label: item.name ?? 'unnamed-agent', value: item.name ?? '' })),
    [agentsQuery.data?.agents],
  );

  const modeOptions = useMemo(
    () => Array.from(new Set(events.map((event) => event.streamMode))).sort().map((mode) => ({ label: mode, value: mode })),
    [events],
  );
  const eventTypeOptions = useMemo(
    () => Array.from(new Set(events.map((event) => event.eventType))).sort().map((eventType) => ({ label: eventType, value: eventType })),
    [events],
  );
  const hasActiveFilters = selectedModes.length > 0 || selectedEventTypes.length > 0 || deferredNamespaceFilter.trim() !== '' || deferredSearchFilter.trim() !== '';
  const deferredTraceSearch = useDeferredValue(traceSearchFilter);

  const filteredEvents = useMemo(() => {
    const namespaceNeedle = deferredNamespaceFilter.trim().toLowerCase();
    const searchNeedle = deferredSearchFilter.trim().toLowerCase();

    return events.filter((event) => {
      if (selectedModes.length > 0 && !selectedModes.includes(event.streamMode)) return false;
      if (selectedEventTypes.length > 0 && !selectedEventTypes.includes(event.eventType)) return false;

      const namespaceText = namespaceLabel(event).toLowerCase();
      if (namespaceNeedle && !namespaceText.includes(namespaceNeedle)) return false;

      if (!searchNeedle) return true;

      const haystacks = [
        event.eventType,
        event.streamMode,
        namespaceLabel(event),
        summarizeEvent(event),
        stringifyValue(event.metadata) ?? '',
        stringifyValue(event.payload) ?? '',
        stringifyValue(event.publicEvent) ?? '',
      ];
      return haystacks.some((value) => value.toLowerCase().includes(searchNeedle));
    });
  }, [deferredNamespaceFilter, deferredSearchFilter, events, selectedEventTypes, selectedModes]);

  const traceSpans = useMemo(() => buildTraceSpans(events), [events]);
  const graphModel = useMemo(() => buildGraphModel(graphQuery.data, traceSpans), [graphQuery.data, traceSpans]);
  const graphView = useMemo(
    () => buildVisibleGraph(graphModel, collapsedClusterPaths),
    [collapsedClusterPaths, graphModel],
  );
  const graphNodes = graphView.nodes;
  const graphColumns = graphView.columns;
  const graphFocus = useMemo(
    () => buildGraphFocus(graphView, hoveredGraphNodeId ?? selectedGraphNodeId),
    [graphView, hoveredGraphNodeId, selectedGraphNodeId],
  );
  const filteredTraceSpans = useMemo(() => {
    const needle = deferredTraceSearch.trim().toLowerCase();
    return traceSpans.filter((span) => {
      if (traceStatusFilter !== 'all' && span.status !== traceStatusFilter) return false;
      if (!needle) return true;
      const haystacks = [
        span.nodeName,
        traceNamespaceLabel(span),
        traceSummary(span),
        JSON.stringify(span.input ?? ''),
        JSON.stringify(span.output ?? ''),
        span.reasoning.join(' '),
      ];
      return haystacks.some((value) => value.toLowerCase().includes(needle));
    });
  }, [deferredTraceSearch, traceSpans, traceStatusFilter]);

  const modeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const event of filteredEvents) {
      counts.set(event.streamMode, (counts.get(event.streamMode) ?? 0) + 1);
    }
    return Array.from(counts.entries());
  }, [filteredEvents]);

  const groupedEvents = useMemo(() => {
    if (groupBy === 'flat') {
      return [{ key: 'all-events', label: 'all events', events: filteredEvents }];
    }

    const groups = new Map<string, TelemetryEventVM[]>();
    for (const event of filteredEvents) {
      const key = groupLabel(event, groupBy);
      const items = groups.get(key);
      if (items) {
        items.push(event);
      } else {
        groups.set(key, [event]);
      }
    }

    return Array.from(groups.entries()).map(([key, items]) => ({
      key,
      label: key,
      events: items,
    }));
  }, [filteredEvents, groupBy]);

  const selectedEvent = useMemo(
    () => filteredEvents.find((event) => event.id === selectedEventId) ?? filteredEvents.at(-1),
    [filteredEvents, selectedEventId],
  );
  const selectedTrace = useMemo(
    () => filteredTraceSpans.find((span) => span.id === selectedTraceId) ?? filteredTraceSpans.at(0),
    [filteredTraceSpans, selectedTraceId],
  );
  const selectedGraphNode = useMemo(
    () => graphNodes.find((node) => node.id === selectedGraphNodeId) ?? graphNodes.at(0),
    [graphNodes, selectedGraphNodeId],
  );
  const selectedGraphRelatedSpans = useMemo(
    () => (selectedGraphNode ? graphNodeRelatedSpans(selectedGraphNode, traceSpans) : []),
    [selectedGraphNode, traceSpans],
  );
  const expandedClusterPaths = graphView.expandedClusterPaths;
  const desktopLayoutStyle = useMemo(() => {
    if (!isDesktopLayout) return undefined;
    return { gridTemplateColumns: `${leftPaneWidth}px 10px minmax(0,1fr) 10px ${rightPaneWidth}px` };
  }, [isDesktopLayout, leftPaneWidth, rightPaneWidth]);
  const initialGraphPositions = useMemo(
    () => buildGraphCanvasPositions(graphColumns),
    [graphColumns],
  );
  const renderedGraphEdges = useMemo(
    () => graphView.edges
      .map((edge) => ({
        edge,
        path: graphCanvasEdgePath(graphNodePositions, edge),
      }))
      .filter((item): item is { edge: GraphEdgeVM; path: string } => Boolean(item.path)),
    [graphNodePositions, graphView.edges],
  );
  const graphZoomLabel = `${Math.round(graphCanvasTransform.scale * 100)}%`;

  useEffect(() => {
    const currentClusters = new Set(graphModel.clusterPaths);
    setCollapsedClusterPaths((prev) => {
      const previousClusters = graphClusterRef.current;
      const prevCollapsed = new Set(prev);
      const next = new Set<string>();
      for (const path of currentClusters) {
        if (prevCollapsed.has(path) || !previousClusters.has(path)) {
          next.add(path);
        }
      }
      const nextList = Array.from(next).sort();
      return sameStringList(prev, nextList) ? prev : nextList;
    });
    graphClusterRef.current = currentClusters;
  }, [graphModel.clusterPaths]);

  useEffect(() => {
    if (viewMode !== 'graph') return undefined;
    const viewport = graphViewportRef.current;
    if (!viewport || typeof ResizeObserver === 'undefined') return undefined;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setGraphViewportSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [viewMode]);

  useEffect(() => {
    setGraphNodePositions(initialGraphPositions);
  }, [initialGraphPositions]);

  useLayoutEffect(() => {
    if (viewMode !== 'graph') return;
    if (graphViewportSize.width <= 0 || graphViewportSize.height <= 0) return;
    setGraphCanvasTransform(
      fitGraphCanvasTransform(
        initialGraphPositions,
        graphNodes,
        graphViewportSize.width,
        graphViewportSize.height,
      ),
    );
  }, [graphNodes, graphViewportSize.height, graphViewportSize.width, initialGraphPositions, viewMode]);

  useEffect(() => {
    setHoveredGraphNodeId((prev) => (prev && graphNodes.some((node) => node.id === prev) ? prev : undefined));
  }, [graphNodes]);

  function toggleCluster(path: string): void {
    setCollapsedClusterPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return Array.from(next).sort();
    });
  }

  function expandAllClusters(): void {
    setCollapsedClusterPaths([]);
  }

  function collapseAllClusters(): void {
    setCollapsedClusterPaths([...graphModel.clusterPaths]);
  }

  function stopPaneDrag(): void {
    paneDragStateRef.current = null;
    if (typeof document !== 'undefined') {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
    window.removeEventListener('pointermove', onPaneDrag);
    window.removeEventListener('pointerup', stopPaneDrag);
  }

  function onPaneDrag(event: PointerEvent): void {
    const drag = paneDragStateRef.current;
    const container = paneLayoutRef.current;
    if (!drag || !container) return;

    const containerWidth = container.getBoundingClientRect().width;
    const handleAllowance = 20;
    const minimumMainWidth = 420;
    const minimumLeftWidth = 216;
    const minimumRightWidth = 300;
    const delta = event.clientX - drag.startX;

    if (drag.target === 'left') {
      const maxLeftWidth = Math.max(
        minimumLeftWidth,
        containerWidth - rightPaneWidth - minimumMainWidth - handleAllowance,
      );
      setLeftPaneWidth(clamp(drag.startLeftWidth + delta, minimumLeftWidth, maxLeftWidth));
      return;
    }

    if (drag.target === 'right') {
      const maxRightWidth = Math.max(
        minimumRightWidth,
        containerWidth - leftPaneWidth - minimumMainWidth - handleAllowance,
      );
      setRightPaneWidth(clamp(drag.startRightWidth - delta, minimumRightWidth, maxRightWidth));
    }
  }

  function startPaneDrag(target: PaneDragTarget, event: React.PointerEvent<HTMLDivElement>): void {
    if (!isDesktopLayout) return;
    event.preventDefault();
    paneDragStateRef.current = {
      target,
      startX: event.clientX,
      startLeftWidth: leftPaneWidth,
      startRightWidth: rightPaneWidth,
    };
    if (typeof document !== 'undefined') {
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }
    window.addEventListener('pointermove', onPaneDrag);
    window.addEventListener('pointerup', stopPaneDrag);
  }

  function fitGraphCanvas(): void {
    setGraphCanvasTransform(
      fitGraphCanvasTransform(
        graphNodePositions,
        graphNodes,
        graphViewportSize.width,
        graphViewportSize.height,
      ),
    );
  }

  function zoomGraphCanvas(nextScale: number, anchorX?: number, anchorY?: number): void {
    const clampedScale = clamp(nextScale, 0.38, 1.45);
    if (graphViewportSize.width <= 0 || graphViewportSize.height <= 0) return;

    const localAnchorX = anchorX ?? (graphViewportSize.width / 2);
    const localAnchorY = anchorY ?? (graphViewportSize.height / 2);
    const worldX = (localAnchorX - graphCanvasTransform.x) / graphCanvasTransform.scale;
    const worldY = (localAnchorY - graphCanvasTransform.y) / graphCanvasTransform.scale;

    setGraphCanvasTransform({
      scale: clampedScale,
      x: localAnchorX - (worldX * clampedScale),
      y: localAnchorY - (worldY * clampedScale),
    });
  }

  function stopGraphPointerInteraction(): void {
    graphPointerStateRef.current = null;
    if (typeof document !== 'undefined') {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
    window.removeEventListener('pointermove', onGraphPointerMove);
    window.removeEventListener('pointerup', stopGraphPointerInteraction);
  }

  function onGraphPointerMove(event: PointerEvent): void {
    const interaction = graphPointerStateRef.current;
    if (!interaction) return;

    if (interaction.type === 'pan') {
      setGraphCanvasTransform((prev) => ({
        ...prev,
        x: interaction.originX + (event.clientX - interaction.startClientX),
        y: interaction.originY + (event.clientY - interaction.startClientY),
      }));
      return;
    }

    const nextX = clamp(
      interaction.originX + ((event.clientX - interaction.startClientX) / graphCanvasTransform.scale),
      40,
      GRAPH_BOARD_WIDTH - GRAPH_NODE_WIDTH - 40,
    );
    const nextY = clamp(
      interaction.originY + ((event.clientY - interaction.startClientY) / graphCanvasTransform.scale),
      40,
      GRAPH_BOARD_HEIGHT - GRAPH_NODE_HEIGHT - 40,
    );
    setGraphNodePositions((prev) => ({
      ...prev,
      [interaction.nodeId]: { x: nextX, y: nextY },
    }));
  }

  function startGraphPan(event: React.PointerEvent<HTMLDivElement>): void {
    if (event.target !== event.currentTarget) return;
    graphPointerStateRef.current = {
      type: 'pan',
      startClientX: event.clientX,
      startClientY: event.clientY,
      originX: graphCanvasTransform.x,
      originY: graphCanvasTransform.y,
    };
    if (typeof document !== 'undefined') {
      document.body.style.cursor = 'grabbing';
      document.body.style.userSelect = 'none';
    }
    window.addEventListener('pointermove', onGraphPointerMove);
    window.addEventListener('pointerup', stopGraphPointerInteraction);
  }

  function startGraphNodeDrag(nodeId: string, event: React.PointerEvent<HTMLDivElement>): void {
    event.stopPropagation();
    const current = graphNodePositions[nodeId];
    if (!current) return;
    graphPointerStateRef.current = {
      type: 'node',
      nodeId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originX: current.x,
      originY: current.y,
    };
    if (typeof document !== 'undefined') {
      document.body.style.cursor = 'grabbing';
      document.body.style.userSelect = 'none';
    }
    window.addEventListener('pointermove', onGraphPointerMove);
    window.addEventListener('pointerup', stopGraphPointerInteraction);
  }

  function handleGraphWheel(event: React.WheelEvent<HTMLDivElement>): void {
    event.preventDefault();
    const viewport = graphViewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const anchorX = event.clientX - rect.left;
    const anchorY = event.clientY - rect.top;
    const delta = event.deltaY < 0 ? 0.08 : -0.08;
    zoomGraphCanvas(graphCanvasTransform.scale + delta, anchorX, anchorY);
  }

  function resetRunState(nextPrompt?: string) {
    setStatus('starting');
    setRunSessionId(undefined);
    setCurrentRunId(undefined);
    setCurrentThreadId(undefined);
    setPendingInterrupts([]);
    setEvents([]);
    setSelectedEventId(undefined);
    setSelectedTraceId(undefined);
    setSelectedGraphNodeId(undefined);
    if (typeof nextPrompt === 'string') setPrompt(nextPrompt);
  }

  function appendTelemetryEvent(payload: HTTPTelemetryEventDTO, eventName: string) {
    const normalized: TelemetryEventVM = {
      id: `telemetry-${nextEventIdRef.current++}`,
      runId: payload.run_id ?? payload.public_event?.run_id,
      agentName: payload.agent_name ?? payload.public_event?.agent_name,
      timestamp: payload.timestamp ?? payload.public_event?.timestamp,
      namespace: payload.namespace ?? [],
      streamMode: payload.stream_mode ?? (payload.public_event ? 'lifecycle' : 'unknown'),
      eventType: payload.event_type ?? eventName,
      metadata: payload.metadata,
      payload: payload.payload,
      publicEvent: payload.public_event,
    };

    setEvents((prev) => [...prev, normalized]);
    setSelectedEventId(normalized.id);

    if (normalized.runId) setCurrentRunId(normalized.runId);
    if (payload.public_event?.thread_id) setCurrentThreadId(payload.public_event.thread_id);

    if (normalized.eventType === 'run_started') setStatus('streaming');
    if (normalized.eventType === 'run_ended') {
      setStatus('completed');
      setPendingInterrupts([]);
    }
    if (normalized.eventType === 'run_canceled') {
      setStatus('canceled');
      setPendingInterrupts([]);
    }
    if (normalized.eventType === 'error') {
      setStatus('failed');
      setPendingInterrupts([]);
    }

    const interrupt = collectInterrupt(payload.payload, payload.public_event);
    if (interrupt) {
      setPendingInterrupts((prev) => {
        if (prev.some((item) => item.interruptId === interrupt.interruptId)) return prev;
        return [...prev, interrupt];
      });
      setStatus('waiting_hitl');
    }
  }

  async function startTelemetry(): Promise<void> {
    if (!selectedAgentName) {
      Message.warning('Please select an agent first.');
      return;
    }
    const message = prompt.trim();
    if (!message) {
      Message.warning('Please enter a prompt.');
      return;
    }
    if (streamAbortRef.current) {
      Message.warning('A telemetry stream is already active.');
      return;
    }

    resetRunState(message);

    const controller = new AbortController();
    streamAbortRef.current = controller;

    try {
      await controlClient.runs.streamTelemetry(
        selectedAgentName,
        { message },
        {
          signal: controller.signal,
          onOpen: ({ runSessionId: next }) => setRunSessionId(next),
          onEvent: (eventName, rawPayload) => {
            if (eventName === 'run_session' && typeof rawPayload === 'object' && rawPayload !== null && 'session_id' in rawPayload) {
              const value = (rawPayload as Record<string, unknown>).session_id;
              if (typeof value === 'string') setRunSessionId(value);
              return;
            }
            if (eventName === 'transport_error' && typeof rawPayload === 'object' && rawPayload !== null && 'error' in rawPayload) {
              const value = (rawPayload as Record<string, unknown>).error;
              Message.error(typeof value === 'string' ? value : 'telemetry transport error');
              setStatus('failed');
              return;
            }
            if (!isTelemetryEvent(rawPayload)) return;
            appendTelemetryEvent(rawPayload, eventName);
          },
          onClose: () => {
            streamAbortRef.current = null;
            setRunSessionId(undefined);
          },
        },
      );
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'telemetry stream failed');
      setStatus('failed');
    } finally {
      streamAbortRef.current = null;
      setRunSessionId(undefined);
    }
  }

  async function cancelTelemetry(): Promise<void> {
    if (!runSessionId) {
      Message.warning('No active telemetry run_session.');
      return;
    }
    setStatus('canceling');
    try {
      await controlClient.runs.cancel(runSessionId, { reason: 'user_requested' });
      Message.success('cancel request sent');
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'cancel failed');
    }
  }

  async function submitDecision(interrupt: PendingTelemetryInterrupt, type: 'approve' | 'reject'): Promise<void> {
    if (!runSessionId) {
      Message.warning('No active telemetry run_session.');
      return;
    }
    const decisionCount = Math.max(1, interrupt.actionRequests.length);
    const decisions = Array.from({ length: decisionCount }, () => ({ type }));
    try {
      await controlClient.runs.submitHitl(runSessionId, {
        interrupt_id: interrupt.interruptId,
        decisions,
      });
      setPendingInterrupts((prev) => prev.filter((item) => item.interruptId !== interrupt.interruptId));
      setStatus((prev) => (prev === 'waiting_hitl' ? 'streaming' : prev));
      Message.success(`${type} submitted`);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'submit hitl decision failed');
    }
  }

  function handleAgentChange(value: string | number | Record<string, unknown> | undefined) {
    const nextAgent = typeof value === 'string' ? value : '';
    if (!nextAgent) {
      void navigate(links.telemetryRoot());
      return;
    }
    void navigate(links.telemetryAgent(nextAgent));
  }

  function clearFilters() {
    setSelectedModes([]);
    setSelectedEventTypes([]);
    setNamespaceFilter('');
    setSearchFilter('');
    setGroupBy('namespace');
  }

  function clearTraceFilters() {
    setTraceSearchFilter('');
    setTraceStatusFilter('all');
  }

  useEffect(() => {
    if (filteredEvents.length === 0) {
      setSelectedEventId(undefined);
      return;
    }
    if (!selectedEventId || !filteredEvents.some((event) => event.id === selectedEventId)) {
      setSelectedEventId(filteredEvents[0].id);
    }
  }, [filteredEvents, selectedEventId]);

  useEffect(() => {
    if (filteredTraceSpans.length === 0) {
      setSelectedTraceId(undefined);
      return;
    }
    if (!selectedTraceId || !filteredTraceSpans.some((span) => span.id === selectedTraceId)) {
      setSelectedTraceId(filteredTraceSpans[0].id);
    }
  }, [filteredTraceSpans, selectedTraceId]);

  useEffect(() => {
    if (graphNodes.length === 0) {
      setSelectedGraphNodeId(undefined);
      return;
    }
    if (!selectedGraphNodeId || !graphNodes.some((node) => node.id === selectedGraphNodeId)) {
      setSelectedGraphNodeId(graphNodes[0].id);
    }
  }, [graphNodes, selectedGraphNodeId]);

  return (
    <div className='telemetry-page flex min-h-0 flex-1 flex-col overflow-hidden'>
      <Spin loading={agentsQuery.isLoading} className='telemetry-page-spin flex min-h-0 flex-1 flex-col overflow-hidden'>
        <div className='flex min-h-0 flex-1 flex-col gap-12px overflow-hidden'>
        <div className='flex items-center justify-between gap-16px'>
          <div className='flex items-center gap-12px'>
            <div className='registry-card-icon' style={{ background: 'rgba(0,240,255,0.08)', color: CYAN }}>
              <Server size={20} fill={[CYAN]} />
            </div>
            <div>
              <Typography.Title heading={4} className='!mb-2px !mt-0 !text-[var(--control-text)]'>
                Telemetry
              </Typography.Title>
              <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                Read-only execution stream for messages, updates, debug, and custom events.
              </Typography.Text>
            </div>
          </div>
          <div className='flex items-center gap-8px'>
            <div
              className='flex items-center gap-4px rd-full px-4px py-4px'
              style={{ border: '1px solid var(--control-border)', background: 'rgba(16,22,48,0.76)' }}
            >
              <Button
                size='small'
                type={viewMode === 'trace' ? 'primary' : 'text'}
                className={viewMode === 'trace' ? '' : 'control-quiet-icon-button'}
                onClick={() => setViewMode('trace')}
              >
                Trace
              </Button>
              <Button
                size='small'
                type={viewMode === 'graph' ? 'primary' : 'text'}
                className={viewMode === 'graph' ? '' : 'control-quiet-icon-button'}
                onClick={() => setViewMode('graph')}
              >
                Graph
              </Button>
              <Button
                size='small'
                type={viewMode === 'debug' ? 'primary' : 'text'}
                className={viewMode === 'debug' ? '' : 'control-quiet-icon-button'}
                onClick={() => setViewMode('debug')}
              >
                Debug
              </Button>
            </div>
            <StatusPill status={status} />
            <Button size='small' onClick={() => void navigate(links.chatRoot())}>
              Chat
            </Button>
          </div>
        </div>

        <PendingApprovalBanner
          interrupts={pendingInterrupts}
          onSubmit={(interrupt, type) => { void submitDecision(interrupt, type); }}
        />

        <div
          ref={paneLayoutRef}
          className='grid min-h-0 h-full flex-1 grid-cols-1 grid-rows-[minmax(0,1fr)] gap-12px xl:grid-cols-[280px_minmax(0,1.6fr)_minmax(320px,0.92fr)]'
          style={desktopLayoutStyle}
        >
          <div className='control-scroll control-scroll-strong flex min-h-0 h-full flex-col gap-12px overflow-y-scroll overflow-x-hidden'>
            <div className='control-card px-14px py-14px'>
              <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>run config</span>
              <div className='flex flex-col gap-10px'>
                <Select
                  allowClear
                  placeholder='Select agent'
                  options={agentOptions}
                  value={selectedAgentName}
                  onChange={handleAgentChange}
                />
                <TextArea
                  autoSize={{ minRows: 4, maxRows: 8 }}
                  placeholder='Prompt to execute with telemetry'
                  value={prompt}
                  onChange={setPrompt}
                />
                <div className='flex gap-8px'>
                  <Button
                    type='primary'
                    className='min-w-0 flex-1'
                    icon={<PlayOne theme='outline' size='14' fill='currentColor' />}
                    disabled={!selectedAgentName || status === 'starting' || status === 'streaming' || status === 'waiting_hitl' || status === 'canceling'}
                    onClick={() => void startTelemetry()}
                  >
                    Start
                  </Button>
                  <Button
                    status='warning'
                    className='min-w-0 flex-1'
                    disabled={!runSessionId || status === 'canceling'}
                    onClick={() => void cancelTelemetry()}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            </div>

            <div className='control-card px-14px py-14px'>
              <div className='mb-10px flex items-center justify-between gap-8px'>
                <span className='block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>run summary</span>
                <StatusPill status={status} />
              </div>
              <div className='grid grid-cols-2 gap-x-10px gap-y-8px text-13px'>
                <span className='text-[var(--control-subtle)]'>agent</span>
                <span className='truncate text-right'>{selectedAgentName ?? 'n/a'}</span>
                <span className='text-[var(--control-subtle)]'>thread</span>
                <span className='truncate text-right'>{currentThreadId ?? 'pending'}</span>
                <span className='text-[var(--control-subtle)]'>session</span>
                <span className='truncate text-right'>{runSessionId ?? '-'}</span>
                <span className='text-[var(--control-subtle)]'>run</span>
                <span className='truncate text-right'>{currentRunId ?? '-'}</span>
              </div>
              <div className='mt-12px'>
                <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>stream modes</span>
                {modeCounts.length === 0 ? (
                  <Typography.Text className='text-12px text-[var(--control-subtle)]'>No events yet</Typography.Text>
                ) : (
                  <div className='flex flex-wrap gap-8px'>
                    {modeCounts.map(([mode, count]) => (
                      <Tag key={mode} size='small' color='arcoblue'>
                        {mode} {count}
                      </Tag>
                    ))}
                  </div>
                )}
              </div>
            </div>

            </div>

          {isDesktopLayout ? (
            <PaneHandle onPointerDown={(event) => startPaneDrag('left', event)} />
          ) : null}

          {viewMode === 'trace' ? (
            <>
              <div className='control-card flex min-h-0 h-full flex-col overflow-hidden'>
                <div className='flex items-center justify-between border-b border-solid border-[var(--control-border)] px-14px py-10px'>
                  <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>trace</span>
                  <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                    {filteredTraceSpans.length} spans
                  </Typography.Text>
                </div>
                <div className='border-b border-solid border-[var(--control-border)] px-12px py-10px'>
                  <div className='mb-8px flex items-center justify-between gap-8px'>
                    <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>trace filters</span>
                    {(traceSearchFilter.trim() !== '' || traceStatusFilter !== 'all') ? (
                      <Button size='mini' type='text' className='control-quiet-icon-button' onClick={clearTraceFilters}>
                        Clear
                      </Button>
                    ) : null}
                  </div>
                  <div className='grid grid-cols-1 gap-8px lg:grid-cols-[minmax(0,1fr)_180px]'>
                    <Input
                      allowClear
                      size='small'
                      placeholder='Search node, namespace, input, output'
                      value={traceSearchFilter}
                      onChange={setTraceSearchFilter}
                    />
                    <Select
                      size='small'
                      value={traceStatusFilter}
                      options={[
                        { label: 'All statuses', value: 'all' },
                        { label: 'Running', value: 'running' },
                        { label: 'Completed', value: 'completed' },
                        { label: 'Failed', value: 'failed' },
                        { label: 'Interrupted', value: 'interrupted' },
                        { label: 'Observed', value: 'observed' },
                      ]}
                      onChange={(value) => setTraceStatusFilter(String(value) as TraceStatusFilter)}
                    />
                  </div>
                </div>
                <div className='min-h-0 flex-1 overflow-hidden'>
                  <ScrollableViewport viewportRef={listViewportRef} viewportClassName='px-10px py-10px'>
                    {traceSpans.length === 0 ? (
                      <div className='flex h-full items-center justify-center'>
                        <Empty description='Start a telemetry run to inspect the execution trace' />
                      </div>
                    ) : filteredTraceSpans.length === 0 ? (
                      <div className='flex h-full items-center justify-center'>
                        <Empty description='No trace spans match the current filters' />
                      </div>
                    ) : (
                      <div className='flex flex-col gap-8px'>
                        {filteredTraceSpans.map((span) => {
                          const active = selectedTrace?.id === span.id;
                          const accent = traceAccent(span.status);
                          return (
                            <button
                              key={span.id}
                              type='button'
                              className='cursor-pointer border-none rd-12px px-12px py-10px text-left transition-all duration-200'
                              style={{
                                marginLeft: `${span.namespace.length * 14}px`,
                                background: active ? `${accent}14` : 'rgba(16,22,48,0.76)',
                                border: `1px solid ${active ? `${accent}55` : 'rgba(0,240,255,0.08)'}`,
                                boxShadow: active ? `0 0 12px ${accent}20` : 'none',
                              }}
                              onClick={() => setSelectedTraceId(span.id)}
                            >
                              <div className='flex items-center gap-8px'>
                                <span
                                  className='inline-block h-8px w-8px shrink-0 rd-full'
                                  style={{ background: accent, boxShadow: `0 0 8px ${accent}` }}
                                />
                                <span className='text-12px font-semibold text-[var(--control-text)]'>{span.nodeName}</span>
                                <Tag size='small' color='arcoblue'>{traceStatusLabel(span.status)}</Tag>
                                {span.step !== undefined ? <Tag size='small' color='purple'>step {span.step}</Tag> : null}
                                <span className='ml-auto text-11px text-[var(--control-subtle)]'>
                                  {traceDurationLabel(span)}
                                </span>
                              </div>
                              <div className='mt-6px flex items-center gap-8px'>
                                <span className='text-11px uppercase tracking-wider text-[var(--control-subtle)]'>
                                  {traceNamespaceLabel(span)}
                                </span>
                              </div>
                              <div className='mt-6px text-12px leading-18px text-[var(--control-subtle)]'>
                                {traceSummary(span)}
                              </div>
                              <div className='mt-8px flex flex-wrap gap-6px'>
                                <Tag size='small' color='green'>events {span.events.length}</Tag>
                                {span.messages.length > 0 ? <Tag size='small' color='arcoblue'>messages {span.messages.length}</Tag> : null}
                                {span.reasoning.length > 0 ? <Tag size='small' color='magenta'>reasoning {span.reasoning.length}</Tag> : null}
                                {span.updates.length > 0 ? <Tag size='small' color='orange'>updates {span.updates.length}</Tag> : null}
                                {span.custom.length > 0 ? <Tag size='small' color='green'>custom {span.custom.length}</Tag> : null}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </ScrollableViewport>
                </div>
              </div>

              {isDesktopLayout ? (
                <PaneHandle onPointerDown={(event) => startPaneDrag('right', event)} />
              ) : null}

              <div className='flex min-h-0 h-full flex-col gap-12px overflow-hidden'>
                <div className='control-card px-14px py-14px'>
                  <div className='mb-10px flex items-center justify-between gap-8px'>
                    <span className='block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>selected span</span>
                    {selectedTrace ? (
                      <Tag size='small' color='arcoblue'>{traceStatusLabel(selectedTrace.status)}</Tag>
                    ) : null}
                  </div>
                  {selectedTrace ? (
                    <div className='grid grid-cols-2 gap-x-10px gap-y-8px text-13px'>
                      <span className='text-[var(--control-subtle)]'>node</span>
                      <span className='truncate text-right'>{selectedTrace.nodeName}</span>
                      <span className='text-[var(--control-subtle)]'>namespace</span>
                      <span className='truncate text-right'>{traceNamespaceLabel(selectedTrace)}</span>
                      <span className='text-[var(--control-subtle)]'>started</span>
                      <span className='truncate text-right'>{formatCompactDateTime(selectedTrace.startedAt)}</span>
                      <span className='text-[var(--control-subtle)]'>duration</span>
                      <span className='truncate text-right'>{traceDurationLabel(selectedTrace)}</span>
                    </div>
                  ) : (
                    <Typography.Text className='text-12px text-[var(--control-subtle)]'>No span selected</Typography.Text>
                  )}
                </div>

                {selectedTrace ? (
                  <div className='control-card flex min-h-0 flex-1 flex-col overflow-hidden px-14px py-14px'>
                    <div className='mb-10px flex items-center justify-between gap-8px'>
                      <span className='block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>span details</span>
                      <SegmentedTabs
                        value={traceDetailTab}
                        tabs={[
                          { value: 'io', label: 'I/O' },
                          { value: 'reasoning', label: 'Reasoning' },
                          { value: 'events', label: 'Events' },
                        ]}
                        onChange={(value) => setTraceDetailTab(value as TraceDetailTab)}
                      />
                    </div>
                    <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden'>
                      {traceDetailTab === 'io' ? (
                        <div className='flex flex-col gap-12px'>
                          <div>
                            <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>input</span>
                            <pre
                              className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                              style={{ background: 'rgba(0,240,255,0.03)', border: '1px solid rgba(0,240,255,0.08)' }}
                            >
                              {stringifyValue(selectedTrace.input) ?? 'n/a'}
                            </pre>
                          </div>
                          <div>
                            <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>output</span>
                            <pre
                              className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                              style={{ background: 'rgba(57,255,20,0.03)', border: '1px solid rgba(57,255,20,0.10)' }}
                            >
                              {stringifyValue(selectedTrace.output ?? selectedTrace.messages.at(-1)) ?? 'n/a'}
                            </pre>
                          </div>
                          <div>
                            <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>state updates</span>
                            <pre
                              className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                              style={{ background: 'rgba(255,159,26,0.03)', border: '1px solid rgba(255,159,26,0.12)' }}
                            >
                              {selectedTrace.updates.length > 0 ? stringifyValue(selectedTrace.updates) : 'n/a'}
                            </pre>
                          </div>
                        </div>
                      ) : traceDetailTab === 'reasoning' ? (
                        <div>
                          <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>reasoning</span>
                          <div
                            className='chat-markdown rd-10px p-10px'
                            style={{ background: 'rgba(255,45,149,0.03)', border: '1px solid rgba(255,45,149,0.10)' }}
                          >
                            {traceReasoningMarkdown(selectedTrace) ? (
                              <Markdown remarkPlugins={[remarkGfm]}>
                                {traceReasoningMarkdown(selectedTrace)!}
                              </Markdown>
                            ) : 'n/a'}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <div className='mb-8px flex items-center justify-between gap-8px'>
                            <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>raw events</span>
                            <Button
                              size='mini'
                              type='text'
                              className='control-quiet-icon-button'
                              onClick={() => setViewMode('debug')}
                            >
                              Open Debug
                            </Button>
                          </div>
                          <div className='flex flex-col gap-6px'>
                            {selectedTrace.events.map((event) => (
                              <button
                                key={event.id}
                                type='button'
                                className='cursor-pointer border-none rd-10px px-10px py-8px text-left transition-all duration-200'
                                style={{ background: 'rgba(16,22,48,0.76)', border: '1px solid rgba(0,240,255,0.08)' }}
                                onClick={() => {
                                  setViewMode('debug');
                                  setSelectedEventId(event.id);
                                }}
                              >
                                <div className='flex items-center gap-8px'>
                                  <Tag size='small' color='arcoblue'>{event.streamMode}</Tag>
                                  <span className='text-12px text-[var(--control-text)]'>{event.eventType}</span>
                                  <span className='ml-auto text-11px text-[var(--control-subtle)]'>{formatCompactDateTime(event.timestamp)}</span>
                                </div>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
                </div>
            </>
          ) : viewMode === 'graph' ? (
            <>
              <div className='control-card grid min-h-0 h-full grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden'>
                <div className='flex items-center justify-between border-b border-solid border-[var(--control-border)] px-14px py-10px'>
                  <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>graph canvas</span>
                  <div className='flex items-center gap-8px'>
                    <Tag size='small' color='arcoblue'>xray 2</Tag>
                    <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                      {graphNodes.length} visible / {graphModel.rawNodes.length} total
                    </Typography.Text>
                    <Tag size='small' color='green'>{graphZoomLabel}</Tag>
                    <Button size='mini' type='text' className='control-quiet-icon-button' onClick={() => zoomGraphCanvas(graphCanvasTransform.scale - 0.1)}>
                      -
                    </Button>
                    <Button size='mini' type='text' className='control-quiet-icon-button' onClick={fitGraphCanvas}>
                      Fit
                    </Button>
                    <Button size='mini' type='text' className='control-quiet-icon-button' onClick={() => zoomGraphCanvas(graphCanvasTransform.scale + 0.1)}>
                      +
                    </Button>
                  </div>
                </div>
                <div className='border-b border-solid border-[var(--control-border)] px-12px py-10px'>
                  <div className='flex items-center justify-between gap-8px'>
                    <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>subgraphs</span>
                    <div className='flex items-center gap-8px'>
                      {collapsedClusterPaths.length > 0 ? (
                        <Button size='mini' type='text' className='control-quiet-icon-button' onClick={expandAllClusters}>
                          Expand all
                        </Button>
                      ) : null}
                      {expandedClusterPaths.length > 0 ? (
                        <Button size='mini' type='text' className='control-quiet-icon-button' onClick={collapseAllClusters}>
                          Collapse all
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {graphModel.clusters.length === 0 ? (
                    <Typography.Text className='mt-8px block text-12px text-[var(--control-subtle)]'>
                      No nested subgraphs detected in this graph.
                    </Typography.Text>
                  ) : expandedClusterPaths.length === 0 ? (
                    <Typography.Text className='mt-8px block text-12px text-[var(--control-subtle)]'>
                      All {graphModel.clusters.length} subgraphs are collapsed for the high-level view.
                    </Typography.Text>
                  ) : (
                    <div className='mt-8px flex flex-wrap gap-6px'>
                      {expandedClusterPaths.map((path) => (
                        <button
                          key={path}
                          type='button'
                          className='cursor-pointer border-none rd-full px-8px py-4px text-11px'
                          style={{ color: CYAN, background: 'rgba(0,240,255,0.06)', border: '1px solid rgba(0,240,255,0.16)' }}
                          onClick={() => toggleCluster(path)}
                        >
                          {path} x
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div
                  ref={graphViewportRef}
                  className='relative min-h-0 flex-1 overflow-hidden px-12px py-12px'
                  style={{
                    background:
                      'radial-gradient(circle at top left, rgba(0,240,255,0.05), transparent 32%), repeating-linear-gradient(0deg, transparent, transparent 43px, rgba(0,240,255,0.03) 43px, rgba(0,240,255,0.03) 44px), repeating-linear-gradient(90deg, transparent, transparent 43px, rgba(0,240,255,0.03) 43px, rgba(0,240,255,0.03) 44px)',
                  }}
                  onMouseLeave={() => setHoveredGraphNodeId(undefined)}
                  onWheel={handleGraphWheel}
                  onPointerDown={startGraphPan}
                >
                  {graphQuery.isLoading ? (
                    <div className='flex h-full items-center justify-center'>
                      <Spin loading />
                    </div>
                  ) : !selectedAgentName ? (
                    <div className='flex h-full items-center justify-center'>
                      <Empty description='Select an agent to load its graph' />
                    </div>
                  ) : graphNodes.length === 0 ? (
                    <div className='flex h-full items-center justify-center'>
                      <Empty description='No graph data available for this agent' />
                    </div>
                  ) : (
                    <div className='absolute inset-0'>
                      <div
                        className='absolute left-0 top-0'
                        style={{
                          width: `${GRAPH_BOARD_WIDTH}px`,
                          height: `${GRAPH_BOARD_HEIGHT}px`,
                          transform: `translate(${graphCanvasTransform.x}px, ${graphCanvasTransform.y}px) scale(${graphCanvasTransform.scale})`,
                          transformOrigin: '0 0',
                        }}
                      >
                        <svg
                          className='pointer-events-none absolute left-0 top-0'
                          width={GRAPH_BOARD_WIDTH}
                          height={GRAPH_BOARD_HEIGHT}
                          viewBox={`0 0 ${GRAPH_BOARD_WIDTH} ${GRAPH_BOARD_HEIGHT}`}
                        >
                          {renderedGraphEdges.map(({ edge, path }) => {
                            const tone = graphEdgeTone(edge, graphFocus);
                            return (
                              <path
                                key={edge.id}
                                d={path}
                                fill='none'
                                stroke={tone.stroke}
                                strokeWidth={tone.width}
                                strokeOpacity={tone.opacity}
                                strokeDasharray={edge.conditional ? '7 5' : undefined}
                                strokeLinecap='round'
                              />
                            );
                          })}
                        </svg>
                        {graphNodes.map((node) => {
                          const position = graphNodePositions[node.id];
                          if (!position) return null;
                          const active = selectedGraphNode?.id === node.id;
                          const status = graphNodeStatus(node, traceSpans);
                          const accent = traceAccent(status);
                          const related = graphNodeRelatedSpans(node, traceSpans);
                          const pathState = graphNodePathState(node, graphFocus);
                          const tone = graphNodeBadgeTone(pathState);
                          const background = active
                            ? `${accent}14`
                            : pathState === 'focus'
                              ? `${MAGENTA}10`
                              : pathState === 'upstream'
                                ? `${ORANGE}10`
                                : pathState === 'downstream'
                                  ? `${CYAN}10`
                                  : 'rgba(16,22,48,0.88)';

                          return (
                            <div
                              key={node.id}
                              role='button'
                              tabIndex={0}
                              className='absolute cursor-grab rd-14px border border-solid text-left transition-all duration-150 active:cursor-grabbing'
                              style={{
                                left: `${position.x}px`,
                                top: `${position.y}px`,
                                width: `${GRAPH_NODE_WIDTH}px`,
                                minHeight: `${GRAPH_NODE_HEIGHT}px`,
                                background,
                                borderColor: active ? `${accent}55` : tone.border,
                                boxShadow: active ? `0 0 14px ${accent}24` : tone.glow ?? 'none',
                                opacity: tone.opacity,
                                padding: '12px 12px 10px 12px',
                              }}
                              onPointerDown={(event) => startGraphNodeDrag(node.id, event)}
                              onClick={() => setSelectedGraphNodeId(node.id)}
                              onMouseEnter={() => setHoveredGraphNodeId(node.id)}
                              onFocus={() => setHoveredGraphNodeId(node.id)}
                              onBlur={() => setHoveredGraphNodeId(undefined)}
                              onKeyDown={(event) => {
                                if (event.key !== 'Enter' && event.key !== ' ') return;
                                event.preventDefault();
                                setSelectedGraphNodeId(node.id);
                              }}
                            >
                              <div className='flex items-start gap-8px'>
                                <span
                                  className='mt-4px inline-block h-8px w-8px shrink-0 rd-full'
                                  style={{ background: accent, boxShadow: `0 0 8px ${accent}` }}
                                />
                                <div className='min-w-0 flex-1'>
                                  <div className='flex items-start gap-8px'>
                                    <span className='min-w-0 flex-1 text-13px font-semibold text-[var(--control-text)]' style={lineClampStyle(1)}>
                                      {node.label}
                                    </span>
                                    <Tag size='small' color='arcoblue'>{traceStatusLabel(status)}</Tag>
                                  </div>
                                  <div className='mt-6px text-10px uppercase tracking-widest text-[var(--control-subtle)]' style={lineClampStyle(1)}>
                                    {node.graphID}
                                  </div>
                                  <div className='mt-8px text-12px leading-18px text-[var(--control-subtle)]' style={lineClampStyle(2)}>
                                    {graphNodeSummary(node, traceSpans)}
                                  </div>
                                  <div className='mt-8px flex flex-wrap gap-6px'>
                                    <Tag size='small' color='purple'>{node.kind}</Tag>
                                    {related.length > 0 ? <Tag size='small' color='green'>spans {related.length}</Tag> : null}
                                    {node.isCluster ? <Tag size='small' color='magenta'>nodes {node.memberCount}</Tag> : null}
                                  </div>
                                  {node.isCluster ? (
                                    <div className='mt-8px flex justify-end'>
                                      <Button
                                        size='mini'
                                        type='text'
                                        className='control-quiet-icon-button'
                                        onClick={(event) => {
                                          event.stopPropagation();
                                          toggleCluster(node.graphID);
                                        }}
                                      >
                                        Expand
                                      </Button>
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {isDesktopLayout ? (
                <PaneHandle onPointerDown={(event) => startPaneDrag('right', event)} />
              ) : null}

              <div className='flex min-h-0 h-full flex-col gap-12px overflow-hidden'>
                <div className='control-card px-14px py-14px'>
                  <div className='mb-10px flex items-center justify-between gap-8px'>
                    <span className='block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>selected node</span>
                    {selectedGraphNode ? (
                      <Tag size='small' color='arcoblue'>{selectedGraphNode.isCluster ? 'subgraph' : selectedGraphNode.kind}</Tag>
                    ) : null}
                  </div>
                  {selectedGraphNode ? (
                    <>
                      <div className='grid grid-cols-2 gap-x-10px gap-y-8px text-13px'>
                        <span className='text-[var(--control-subtle)]'>label</span>
                        <span className='truncate text-right'>{selectedGraphNode.label}</span>
                        <span className='text-[var(--control-subtle)]'>id</span>
                        <span className='truncate text-right'>{selectedGraphNode.graphID}</span>
                        <span className='text-[var(--control-subtle)]'>scope</span>
                        <span className='truncate text-right'>{graphNodeScopeLabel(selectedGraphNode)}</span>
                        <span className='text-[var(--control-subtle)]'>related spans</span>
                        <span className='truncate text-right'>{selectedGraphNode.relatedSpanIDs.length}</span>
                        {selectedGraphNode.isCluster ? (
                          <>
                            <span className='text-[var(--control-subtle)]'>members</span>
                            <span className='truncate text-right'>{selectedGraphNode.memberCount}</span>
                          </>
                        ) : null}
                      </div>
                      <div className='mt-10px flex flex-wrap gap-8px'>
                        {selectedGraphNode.isCluster ? (
                          <Button size='mini' type='primary' onClick={() => toggleCluster(selectedGraphNode.graphID)}>
                            Expand subgraph
                          </Button>
                        ) : selectedGraphNode.clusterAncestors.map((path) => (
                          <Button key={path} size='mini' type='text' className='control-quiet-icon-button' onClick={() => toggleCluster(path)}>
                            Collapse {path}
                          </Button>
                        ))}
                      </div>
                    </>
                  ) : (
                    <Typography.Text className='text-12px text-[var(--control-subtle)]'>No node selected</Typography.Text>
                  )}
                </div>

                {selectedGraphNode ? (
                  <div className='control-card flex min-h-0 flex-1 flex-col overflow-hidden px-14px py-14px'>
                    <div className='mb-10px flex items-center justify-between gap-8px'>
                      <span className='block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>node details</span>
                      <SegmentedTabs
                        value={graphDetailTab}
                        tabs={[
                          { value: 'data', label: 'Data' },
                          { value: 'metadata', label: 'Metadata' },
                          { value: 'trace', label: 'Trace' },
                        ]}
                        onChange={(value) => setGraphDetailTab(value as GraphDetailTab)}
                      />
                    </div>
                    <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden'>
                      {graphDetailTab === 'data' ? (
                        <div className='flex flex-col gap-12px'>
                          {selectedGraphNode.isCluster ? (
                            <div>
                              <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>subgraph members</span>
                              <div className='flex flex-wrap gap-6px'>
                                {selectedGraphNode.leafNodeIDs.slice(0, 24).map((nodeID) => (
                                  <span
                                    key={nodeID}
                                    className='rd-full px-8px py-3px text-11px border border-solid'
                                    style={{ color: 'var(--control-text)', borderColor: 'rgba(0,240,255,0.10)', background: 'rgba(0,240,255,0.04)' }}
                                  >
                                    {nodeID}
                                  </span>
                                ))}
                                {selectedGraphNode.leafNodeIDs.length > 24 ? (
                                  <Tag size='small' color='arcoblue'>+{selectedGraphNode.leafNodeIDs.length - 24} more</Tag>
                                ) : null}
                              </div>
                              {selectedGraphNode.childClusterPaths.length > 0 ? (
                                <div className='mt-10px'>
                                  <span className='mb-6px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>nested subgraphs</span>
                                  <div className='flex flex-wrap gap-6px'>
                                    {selectedGraphNode.childClusterPaths.map((path) => (
                                      <span
                                        key={path}
                                        className='rd-full px-8px py-3px text-11px border border-solid'
                                        style={{ color: MAGENTA, borderColor: 'rgba(255,45,149,0.12)', background: 'rgba(255,45,149,0.06)' }}
                                      >
                                        {path}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                          <div>
                            <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>node data</span>
                            <pre
                              className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                              style={{ background: 'rgba(0,240,255,0.03)', border: '1px solid rgba(0,240,255,0.08)' }}
                            >
                              {stringifyValue(selectedGraphNode.rawData) ?? 'n/a'}
                            </pre>
                          </div>
                        </div>
                      ) : graphDetailTab === 'metadata' ? (
                        <div>
                          <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>metadata</span>
                          <pre
                            className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                            style={{ background: 'rgba(255,45,149,0.03)', border: '1px solid rgba(255,45,149,0.10)' }}
                          >
                            {stringifyValue(selectedGraphNode.metadata) ?? 'n/a'}
                          </pre>
                        </div>
                      ) : (
                        <div>
                          <div className='mb-8px flex items-center justify-between gap-8px'>
                            <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>related trace spans</span>
                            <Button
                              size='mini'
                              type='text'
                              className='control-quiet-icon-button'
                              onClick={() => setViewMode('trace')}
                            >
                              Open Trace
                            </Button>
                          </div>
                          <div className='flex flex-col gap-6px'>
                            {selectedGraphRelatedSpans.length === 0 ? (
                              <Typography.Text className='text-12px text-[var(--control-subtle)]'>No related spans observed yet</Typography.Text>
                            ) : (
                              selectedGraphRelatedSpans.map((span) => (
                                <button
                                  key={span.id}
                                  type='button'
                                  className='cursor-pointer border-none rd-10px px-10px py-8px text-left transition-all duration-200'
                                  style={{ background: 'rgba(16,22,48,0.76)', border: '1px solid rgba(0,240,255,0.08)' }}
                                  onClick={() => {
                                    setViewMode('trace');
                                    setSelectedTraceId(span.id);
                                  }}
                                >
                                  <div className='flex items-center gap-8px'>
                                    <Tag size='small' color='arcoblue'>{traceStatusLabel(span.status)}</Tag>
                                    <span className='text-12px text-[var(--control-text)]'>{span.nodeName}</span>
                                    <span className='ml-auto text-11px text-[var(--control-subtle)]'>{traceDurationLabel(span)}</span>
                                  </div>
                                  <div className='mt-6px text-12px leading-18px text-[var(--control-subtle)]'>
                                    {traceSummary(span)}
                                  </div>
                                </button>
                              ))
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
                </div>
            </>
          ) : (
            <>
              <div className='control-card flex min-h-0 h-full flex-col overflow-hidden'>
                <div className='flex items-center justify-between border-b border-solid border-[var(--control-border)] px-14px py-10px'>
                  <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>debug event stream</span>
                  <Typography.Text className='text-12px text-[var(--control-subtle)]'>
                    {filteredEvents.length} visible
                  </Typography.Text>
                </div>
                <div className='border-b border-solid border-[var(--control-border)] px-12px py-10px'>
                  <div className='mb-8px flex items-center justify-between gap-8px'>
                    <span className='text-11px uppercase tracking-widest text-[var(--control-subtle)]'>filters</span>
                    <div className='flex items-center gap-8px'>
                      <Tag size='small' color='arcoblue'>{groupBy}</Tag>
                      {hasActiveFilters ? (
                        <Button size='mini' type='text' className='control-quiet-icon-button' onClick={clearFilters}>
                          Clear
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  <div className='grid grid-cols-1 gap-8px md:grid-cols-2 xl:grid-cols-3'>
                    <Input
                      allowClear
                      size='small'
                      placeholder='Search event, payload, metadata'
                      value={searchFilter}
                      onChange={setSearchFilter}
                    />
                    <Input
                      allowClear
                      size='small'
                      placeholder='Filter namespace'
                      value={namespaceFilter}
                      onChange={setNamespaceFilter}
                    />
                    <Select
                      mode='multiple'
                      allowClear
                      size='small'
                      placeholder='Filter stream modes'
                      options={modeOptions}
                      value={selectedModes}
                      onChange={(value) => {
                        const next = Array.isArray(value) ? value.map((item) => String(item)) : [];
                        setSelectedModes(next);
                      }}
                    />
                    <Select
                      mode='multiple'
                      allowClear
                      size='small'
                      placeholder='Filter event types'
                      options={eventTypeOptions}
                      value={selectedEventTypes}
                      onChange={(value) => {
                        const next = Array.isArray(value) ? value.map((item) => String(item)) : [];
                        setSelectedEventTypes(next);
                      }}
                    />
                    <Select
                      size='small'
                      placeholder='Group by'
                      value={groupBy}
                      options={[
                        { label: 'Namespace', value: 'namespace' },
                        { label: 'Stream mode', value: 'stream_mode' },
                        { label: 'Event type', value: 'event_type' },
                        { label: 'Flat list', value: 'flat' },
                      ]}
                      onChange={(value) => setGroupBy(String(value) as TelemetryGroupMode)}
                    />
                  </div>
                </div>
                <div className='min-h-0 flex-1 overflow-hidden'>
                  <ScrollableViewport viewportRef={listViewportRef} viewportClassName='px-10px py-10px'>
                    {events.length === 0 ? (
                      <div className='flex h-full items-center justify-center'>
                        <Empty description='Start a telemetry run to inspect events' />
                      </div>
                    ) : filteredEvents.length === 0 ? (
                      <div className='flex h-full items-center justify-center'>
                        <Empty description='No events match the current filters' />
                      </div>
                    ) : (
                      <div className='flex flex-col gap-12px'>
                        {groupedEvents.map((group) => (
                          <div key={group.key} className='flex flex-col gap-8px'>
                            {groupBy !== 'flat' ? (
                              <div
                                className='sticky top-0 z-1 flex items-center justify-between rd-10px px-10px py-8px'
                                style={{ background: 'rgba(12,16,36,0.98)', border: '1px solid rgba(0,240,255,0.08)' }}
                              >
                                <span className='text-11px font-semibold uppercase tracking-widest text-[var(--control-subtle)]'>
                                  {group.label}
                                </span>
                                <Tag size='small' color='arcoblue'>{group.events.length}</Tag>
                              </div>
                            ) : null}
                            {group.events.map((event) => {
                              const active = selectedEvent?.id === event.id;
                              const accent = eventAccent(event);
                              return (
                                <button
                                  key={event.id}
                                  type='button'
                                  className='cursor-pointer border-none rd-12px px-12px py-10px text-left transition-all duration-200'
                                  style={{
                                    background: active ? `${accent}14` : 'rgba(16,22,48,0.76)',
                                    border: `1px solid ${active ? `${accent}55` : 'rgba(0,240,255,0.08)'}`,
                                    boxShadow: active ? `0 0 12px ${accent}20` : 'none',
                                  }}
                                  onClick={() => setSelectedEventId(event.id)}
                                >
                                  <div className='flex items-center gap-8px'>
                                    <span
                                      className='inline-block h-8px w-8px shrink-0 rd-full'
                                      style={{ background: accent, boxShadow: `0 0 8px ${accent}` }}
                                    />
                                    <span className='text-12px font-semibold text-[var(--control-text)]'>{event.eventType}</span>
                                    <Tag size='small' color='arcoblue'>{event.streamMode}</Tag>
                                    <span className='ml-auto text-11px text-[var(--control-subtle)]'>
                                      {formatCompactDateTime(event.timestamp)}
                                    </span>
                                  </div>
                                  <div className='mt-6px flex items-center gap-8px'>
                                    <span className='text-11px uppercase tracking-wider text-[var(--control-subtle)]'>
                                      {namespaceLabel(event)}
                                    </span>
                                  </div>
                                  <div className='mt-6px text-12px leading-18px text-[var(--control-subtle)]'>
                                    {summarizeEvent(event)}
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        ))}
                      </div>
                    )}
                  </ScrollableViewport>
                </div>
              </div>

              {isDesktopLayout ? (
                <PaneHandle onPointerDown={(event) => startPaneDrag('right', event)} />
              ) : null}

              <div className='flex min-h-0 h-full flex-col gap-12px overflow-hidden'>
                <div className='control-card px-14px py-14px'>
                  <div className='mb-10px flex items-center justify-between gap-8px'>
                    <span className='block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>selected event</span>
                    {selectedEvent ? <Tag size='small' color='arcoblue'>{selectedEvent.streamMode}</Tag> : null}
                  </div>
                  {selectedEvent ? (
                    <div className='grid grid-cols-2 gap-x-10px gap-y-8px text-13px'>
                      <span className='text-[var(--control-subtle)]'>type</span>
                      <span className='truncate text-right'>{selectedEvent.eventType}</span>
                      <span className='text-[var(--control-subtle)]'>time</span>
                      <span className='truncate text-right'>{formatCompactDateTime(selectedEvent.timestamp)}</span>
                      <span className='text-[var(--control-subtle)]'>namespace</span>
                      <span className='truncate text-right'>{namespaceLabel(selectedEvent)}</span>
                    </div>
                  ) : (
                    <Typography.Text className='text-12px text-[var(--control-subtle)]'>No event selected</Typography.Text>
                  )}
                </div>

                {selectedEvent ? (
                  <div className='control-card flex min-h-0 flex-1 flex-col overflow-hidden px-14px py-14px'>
                    <div className='mb-10px flex items-center justify-between gap-8px'>
                      <span className='block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>event details</span>
                      <SegmentedTabs
                        value={debugDetailTab}
                        tabs={[
                          { value: 'payload', label: 'Payload' },
                          { value: 'metadata', label: 'Metadata' },
                          { value: 'public_event', label: 'Public' },
                        ]}
                        onChange={(value) => setDebugDetailTab(value as DebugDetailTab)}
                      />
                    </div>
                    <div className='control-scroll control-scroll-strong min-h-0 flex-1 overflow-y-scroll overflow-x-hidden'>
                      {debugDetailTab === 'payload' ? (
                        <div>
                          <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>payload</span>
                          <pre
                            className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                            style={{ background: 'rgba(255,45,149,0.03)', border: '1px solid rgba(255,45,149,0.10)' }}
                          >
                            {stringifyValue(selectedEvent.payload) ?? 'n/a'}
                          </pre>
                        </div>
                      ) : debugDetailTab === 'metadata' ? (
                        <div>
                          <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>metadata</span>
                          <pre
                            className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                            style={{ background: 'rgba(0,240,255,0.03)', border: '1px solid rgba(0,240,255,0.08)' }}
                          >
                            {stringifyValue(selectedEvent.metadata) ?? 'n/a'}
                          </pre>
                        </div>
                      ) : (
                        <div>
                          <span className='mb-8px block text-11px uppercase tracking-widest text-[var(--control-subtle)]'>public event</span>
                          <pre
                            className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                            style={{ background: 'rgba(57,255,20,0.03)', border: '1px solid rgba(57,255,20,0.10)' }}
                          >
                            {stringifyValue(selectedEvent.publicEvent) ?? 'n/a'}
                          </pre>
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
                </div>
            </>
          )}
        </div>
        </div>
      </Spin>
    </div>
  );
}
