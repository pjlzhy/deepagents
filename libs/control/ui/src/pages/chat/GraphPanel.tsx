import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Button, Empty, Spin, Typography } from '@arco-design/web-react';
import type { AgentGraphDTO } from '@/shared/types/api';
import {
  buildGraphFocus,
  buildGraphModel,
  buildVisibleGraph,
  type GraphNodeVM,
} from '@/features/telemetry/graphModel';
import type { TraceSpanVM } from '@/features/telemetry/traceModel';
import {
  CYAN,
  MAGENTA,
  ORANGE,
  graphEdgeTone,
  graphNodeBadgeTone,
  graphNodePathState,
  graphNodeRelatedSpans,
  graphNodeScopeLabel,
  graphNodeStatus,
  graphNodeSummary,
  lineClampStyle,
  traceAccent,
  traceStatusLabel,
  stringifyValue,
  type GraphDetailTab,
} from '@/shared/utils/telemetryHelpers';
import {
  GRAPH_BOARD_WIDTH,
  GRAPH_BOARD_HEIGHT,
  GRAPH_NODE_WIDTH,
  GRAPH_NODE_HEIGHT,
  buildGraphCanvasPositions,
  fitGraphCanvasTransform,
  graphCanvasEdgePath,
} from '@/shared/utils/graphLayout';
import SegmentedTabs from '@/shared/components/telemetry/SegmentedTabs';
import TraceTreeRow from '@/shared/components/telemetry/TraceTreeRow';
import CollapsibleSection from '@/shared/components/telemetry/CollapsibleSection';

type GraphPanelProps = {
  graphData?: AgentGraphDTO;
  traceSpans: TraceSpanVM[];
  loading: boolean;
  agentName: string;
};

export default function GraphPanel(props: GraphPanelProps) {
  const graphViewportRef = useRef<HTMLDivElement | null>(null);
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | undefined>(undefined);
  const [hoveredGraphNodeId, setHoveredGraphNodeId] = useState<string | undefined>(undefined);
  const [collapsedClusterPaths, setCollapsedClusterPaths] = useState<string[]>([]);
  const [graphViewportSize, setGraphViewportSize] = useState({ width: 0, height: 0 });
  const [graphCanvasTransform, setGraphCanvasTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [graphDetailTab, setGraphDetailTab] = useState<GraphDetailTab>('data');

  const graphModel = useMemo(
    () => buildGraphModel(props.graphData, props.traceSpans),
    [props.graphData, props.traceSpans],
  );
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
  const graphPositions = useMemo(
    () => buildGraphCanvasPositions(graphColumns),
    [graphColumns],
  );
  const renderedEdges = useMemo(
    () => graphView.edges
      .map((edge) => ({
        edge,
        path: graphCanvasEdgePath(graphPositions, edge),
      }))
      .filter((item): item is { edge: typeof graphView.edges[0]; path: string } => Boolean(item.path)),
    [graphPositions, graphView.edges],
  );
  const selectedGraphNode = useMemo(
    () => graphNodes.find((node) => node.id === selectedGraphNodeId) ?? graphNodes.at(0),
    [graphNodes, selectedGraphNodeId],
  );
  const selectedGraphRelatedSpans = useMemo(
    () => (selectedGraphNode ? graphNodeRelatedSpans(selectedGraphNode, props.traceSpans) : []),
    [selectedGraphNode, props.traceSpans],
  );

  // Auto-fit on graph data change
  useEffect(() => {
    const viewport = graphViewportRef.current;
    if (!viewport || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setGraphViewportSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    if (graphViewportSize.width <= 0 || graphViewportSize.height <= 0) return;
    setGraphCanvasTransform(
      fitGraphCanvasTransform(graphPositions, graphNodes, graphViewportSize.width, graphViewportSize.height),
    );
  }, [graphNodes, graphViewportSize.height, graphViewportSize.width, graphPositions]);

  // Collapse new clusters by default
  useEffect(() => {
    setCollapsedClusterPaths([...graphModel.clusterPaths]);
  }, [graphModel.clusterPaths]);

  function toggleCluster(path: string) {
    setCollapsedClusterPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return Array.from(next).sort();
    });
  }

  return (
    <div className='flex h-full min-h-0 flex-col overflow-hidden'>
      {/* Graph canvas */}
      <div
        ref={graphViewportRef}
        className='relative min-h-0 flex-1 overflow-hidden'
        style={{
          background:
            'radial-gradient(circle at top left, rgba(0,240,255,0.05), transparent 32%), repeating-linear-gradient(0deg, transparent, transparent 43px, rgba(0,240,255,0.03) 43px, rgba(0,240,255,0.03) 44px), repeating-linear-gradient(90deg, transparent, transparent 43px, rgba(0,240,255,0.03) 43px, rgba(0,240,255,0.03) 44px)',
        }}
        onMouseLeave={() => setHoveredGraphNodeId(undefined)}
      >
        {props.loading ? (
          <div className='flex h-full items-center justify-center'>
            <Spin loading />
          </div>
        ) : graphNodes.length === 0 ? (
          <div className='flex h-full items-center justify-center'>
            <Empty description='No graph data available' />
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
                {renderedEdges.map(({ edge, path }) => {
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
                const position = graphPositions[node.id];
                if (!position) return null;
                const active = selectedGraphNode?.id === node.id;
                const status = graphNodeStatus(node, props.traceSpans);
                const accent = traceAccent(status);
                const pathState = graphNodePathState(node, graphFocus);
                const tone = graphNodeBadgeTone(pathState);
                const background = active
                  ? `${accent}14`
                  : pathState === 'focus' ? `${MAGENTA}10`
                    : pathState === 'upstream' ? `${ORANGE}10`
                      : pathState === 'downstream' ? `${CYAN}10`
                        : 'rgba(16,22,48,0.88)';

                return (
                  <div
                    key={node.id}
                    role='button'
                    tabIndex={0}
                    className='absolute rd-14px border border-solid text-left transition-all duration-150'
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
                      cursor: 'pointer',
                    }}
                    onClick={() => setSelectedGraphNodeId(node.id)}
                    onMouseEnter={() => setHoveredGraphNodeId(node.id)}
                    onFocus={() => setHoveredGraphNodeId(node.id)}
                    onBlur={() => setHoveredGraphNodeId(undefined)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedGraphNodeId(node.id); } }}
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
                          <span
                            className='shrink-0 rd-4px px-4px py-1px text-10px'
                            style={{ background: `${accent}18`, color: accent }}
                          >
                            {traceStatusLabel(status)}
                          </span>
                        </div>
                        <div className='mt-6px text-10px uppercase tracking-widest text-[var(--control-subtle)]' style={lineClampStyle(1)}>
                          {node.graphID}
                        </div>
                        <div className='mt-8px text-12px leading-18px text-[var(--control-subtle)]' style={lineClampStyle(2)}>
                          {graphNodeSummary(node, props.traceSpans)}
                        </div>
                        <div className='mt-6px flex flex-wrap items-center gap-4px'>
                          <span className='rd-4px px-4px py-1px text-10px' style={{ background: 'rgba(157,78,221,0.15)', color: '#c084fc' }}>
                            {node.kind}
                          </span>
                          {graphNodeRelatedSpans(node, props.traceSpans).length > 0 ? (
                            <span className='rd-4px px-4px py-1px text-10px' style={{ background: 'rgba(57,255,20,0.1)', color: '#39ff14' }}>
                              {graphNodeRelatedSpans(node, props.traceSpans).length} spans
                            </span>
                          ) : null}
                          {node.isCluster ? (
                            <span className='rd-4px px-4px py-1px text-10px' style={{ background: 'rgba(255,45,149,0.1)', color: '#ff2d95' }}>
                              {node.memberCount} nodes
                            </span>
                          ) : null}
                        </div>
                        {node.isCluster ? (
                          <div className='mt-8px flex justify-end'>
                            <Button
                              size='mini'
                              type='text'
                              className='control-quiet-icon-button'
                              onClick={(event) => { event.stopPropagation(); toggleCluster(node.graphID); }}
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

      {/* Node detail below graph */}
      {selectedGraphNode ? (
        <div
          className='shrink-0 border-t border-solid border-[var(--control-border)]'
          style={{ maxHeight: '280px' }}
        >
          <div className='flex items-center justify-between px-14px py-8px'>
            <div className='flex min-w-0 flex-1 items-center gap-8px'>
              <span
                className='inline-block h-8px w-8px shrink-0 rd-full'
                style={{ background: traceAccent(graphNodeStatus(selectedGraphNode, props.traceSpans)), boxShadow: `0 0 6px ${traceAccent(graphNodeStatus(selectedGraphNode, props.traceSpans))}` }}
              />
              <span className='truncate text-12px font-semibold text-[var(--control-text)]'>
                {selectedGraphNode.label}
              </span>
              <span className='text-[var(--control-border)]'>|</span>
              <span className='text-10px text-[var(--control-subtle)]'>
                {graphNodeScopeLabel(selectedGraphNode)}
              </span>
            </div>
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
          <div className='control-scroll control-scroll-strong overflow-y-scroll overflow-x-hidden px-14px pb-10px' style={{ maxHeight: '220px' }}>
            {graphDetailTab === 'data' ? (
              <CollapsibleSection label='Data' defaultOpen>
                <pre
                  className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                  style={{ background: 'rgba(0,240,255,0.03)', border: '1px solid rgba(0,240,255,0.08)' }}
                >
                  {stringifyValue(selectedGraphNode.rawData) ?? 'n/a'}
                </pre>
              </CollapsibleSection>
            ) : graphDetailTab === 'metadata' ? (
              <CollapsibleSection label='Metadata' defaultOpen>
                <pre
                  className='!m-0 overflow-auto whitespace-pre-wrap break-words rd-10px p-10px text-12px'
                  style={{ background: 'rgba(255,45,149,0.03)', border: '1px solid rgba(255,45,149,0.10)' }}
                >
                  {stringifyValue(selectedGraphNode.metadata) ?? 'n/a'}
                </pre>
              </CollapsibleSection>
            ) : (
              <div className='flex flex-col'>
                {selectedGraphRelatedSpans.length === 0 ? (
                  <Typography.Text className='text-12px text-[var(--control-subtle)]'>No related spans</Typography.Text>
                ) : (
                  selectedGraphRelatedSpans.map((span) => (
                    <TraceTreeRow
                      key={span.id}
                      span={span}
                      active={false}
                      expandable={false}
                      expanded={false}
                      onSelect={() => {}}
                      indentLevel={0}
                    />
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
