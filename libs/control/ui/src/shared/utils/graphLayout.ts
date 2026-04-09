import type { GraphEdgeVM, GraphNodeVM } from '@/features/telemetry/graphModel';
import { clamp, type GraphNodePosition } from '@/shared/utils/telemetryHelpers';

// ─── Constants ───

export const GRAPH_BOARD_WIDTH = 5200;
export const GRAPH_BOARD_HEIGHT = 3600;
export const GRAPH_NODE_WIDTH = 250;
export const GRAPH_NODE_HEIGHT = 132;
export const GRAPH_COLUMN_GAP = 110;
export const GRAPH_ROW_GAP = 32;
export const GRAPH_ORIGIN_X = 180;
export const GRAPH_ORIGIN_Y = 140;

// ─── Layout helpers ───

export function buildGraphCanvasPositions(
  columns: Array<{ level: number; nodes: GraphNodeVM[] }>,
): Record<string, GraphNodePosition> {
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

export function graphCanvasBounds(
  positions: Record<string, GraphNodePosition>,
  nodes: GraphNodeVM[],
): { minX: number; minY: number; maxX: number; maxY: number } {
  if (nodes.length === 0) {
    return { minX: 0, minY: 0, maxX: GRAPH_NODE_WIDTH, maxY: GRAPH_NODE_HEIGHT };
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

export function fitGraphCanvasTransform(
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

export function graphCanvasEdgePath(
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
