import type { AgentGraphDTO, AgentGraphNodeDTO } from '@/shared/types/api';
import type { TraceSpanVM } from './traceModel';

const CLUSTER_ID_PREFIX = '__cluster__:';

export type GraphRawNodeVM = {
  id: string;
  graphID: string;
  label: string;
  kind: string;
  metadata?: Record<string, unknown>;
  rawData?: unknown;
  relatedSpanIDs: string[];
  pathSegments: string[];
  clusterAncestors: string[];
};

export type GraphRawEdgeVM = {
  id: string;
  source: string;
  target: string;
  conditional: boolean;
};

export type GraphClusterVM = {
  path: string;
  label: string;
  depth: number;
  parentPath?: string;
  descendantLeafNodeIDs: string[];
  directLeafNodeIDs: string[];
  childClusterPaths: string[];
  relatedSpanIDs: string[];
};

export type GraphModelVM = {
  rawNodes: GraphRawNodeVM[];
  rawEdges: GraphRawEdgeVM[];
  clusters: GraphClusterVM[];
  clusterPaths: string[];
};

export type GraphNodeVM = {
  id: string;
  graphID: string;
  label: string;
  kind: string;
  metadata?: Record<string, unknown>;
  rawData?: unknown;
  level: number;
  outgoing: string[];
  incoming: string[];
  relatedSpanIDs: string[];
  pathSegments: string[];
  clusterAncestors: string[];
  leafNodeIDs: string[];
  memberCount: number;
  isCluster: boolean;
  clusterPath?: string;
  directLeafNodeIDs: string[];
  childClusterPaths: string[];
};

export type GraphEdgeVM = {
  id: string;
  source: string;
  target: string;
  conditional: boolean;
  rawEdgeCount: number;
};

export type GraphViewVM = {
  nodes: GraphNodeVM[];
  edges: GraphEdgeVM[];
  columns: Array<{ level: number; nodes: GraphNodeVM[] }>;
  expandedClusterPaths: string[];
};

export type GraphFocusVM = {
  nodeID?: string;
  upstreamNodeIDs: Set<string>;
  downstreamNodeIDs: Set<string>;
  upstreamEdgeIDs: Set<string>;
  downstreamEdgeIDs: Set<string>;
};

type MutableCluster = {
  path: string;
  label: string;
  depth: number;
  parentPath?: string;
  descendantLeafNodeIDs: Set<string>;
  directLeafNodeIDs: Set<string>;
  childClusterPaths: Set<string>;
  relatedSpanIDs: Set<string>;
};

type MutableGraphEdge = {
  id: string;
  source: string;
  target: string;
  conditional: boolean;
  rawEdgeCount: number;
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function normalizedID(value: string | number): string {
  return String(value);
}

function cleanedLabel(value: string): string {
  if (value === '__start__') return 'start';
  if (value === '__end__') return 'end';
  const tail = value.split(':').at(-1);
  return tail && tail.trim() !== '' ? tail : value;
}

function nodeLabel(node: AgentGraphNodeDTO): string {
  if (typeof node.data === 'string') return cleanedLabel(node.data);
  const data = asRecord(node.data);
  if (typeof data?.name === 'string' && data.name.trim() !== '') return cleanedLabel(data.name);
  if (typeof node.id === 'string') return cleanedLabel(node.id);
  return String(node.id);
}

function lastNamespaceSegment(namespace: string[]): string | undefined {
  const raw = namespace.at(-1);
  if (!raw) return undefined;
  const [, tail] = raw.split(':');
  return tail || raw;
}

function relatedSpansForNode(node: AgentGraphNodeDTO, spans: TraceSpanVM[]): string[] {
  const id = normalizedID(node.id);
  const label = nodeLabel(node);
  const tail = id.split(':').at(-1);
  return spans
    .filter((span) => (
      span.nodeName === id
      || span.nodeName === label
      || span.nodeName === tail
      || lastNamespaceSegment(span.namespace) === id
      || lastNamespaceSegment(span.namespace) === label
      || lastNamespaceSegment(span.namespace) === tail
    ))
    .map((span) => span.id);
}

function pathSegments(value: string): string[] {
  return value.split(':').filter((item) => item.trim() !== '');
}

function clusterAncestorsForID(value: string): string[] {
  const segments = pathSegments(value);
  if (segments.length <= 1) return [];

  const paths: string[] = [];
  for (let index = 1; index < segments.length; index += 1) {
    paths.push(segments.slice(0, index).join(':'));
  }
  return paths;
}

function parentClusterPath(path: string): string | undefined {
  const segments = pathSegments(path);
  if (segments.length <= 1) return undefined;
  return segments.slice(0, -1).join(':');
}

function visibleClusterID(path: string): string {
  return `${CLUSTER_ID_PREFIX}${path}`;
}

function parseVisibleClusterID(value: string): string | undefined {
  return value.startsWith(CLUSTER_ID_PREFIX) ? value.slice(CLUSTER_ID_PREFIX.length) : undefined;
}

function computeLevels(
  nodeIDs: string[],
  edges: Array<Pick<GraphEdgeVM, 'source' | 'target'>>,
): Map<string, number> {
  const incomingCount = new Map<string, number>();
  const outgoing = new Map<string, string[]>();

  for (const id of nodeIDs) {
    incomingCount.set(id, 0);
    outgoing.set(id, []);
  }

  for (const edge of edges) {
    if (!incomingCount.has(edge.source)) {
      incomingCount.set(edge.source, 0);
      outgoing.set(edge.source, []);
    }
    if (!incomingCount.has(edge.target)) {
      incomingCount.set(edge.target, 0);
      outgoing.set(edge.target, []);
    }

    incomingCount.set(edge.target, (incomingCount.get(edge.target) ?? 0) + 1);
    outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
  }

  const queue = Array.from(incomingCount.entries())
    .filter(([, count]) => count === 0)
    .map(([id]) => id);
  const levels = new Map<string, number>();

  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentLevel = levels.get(current) ?? 0;

    for (const target of outgoing.get(current) ?? []) {
      levels.set(target, Math.max(levels.get(target) ?? 0, currentLevel + 1));
      const nextCount = (incomingCount.get(target) ?? 0) - 1;
      incomingCount.set(target, nextCount);
      if (nextCount === 0) {
        queue.push(target);
      }
    }
  }

  for (const id of incomingCount.keys()) {
    if (!levels.has(id)) levels.set(id, 0);
  }

  return levels;
}

function createCluster(path: string): MutableCluster {
  return {
    path,
    label: cleanedLabel(path),
    depth: pathSegments(path).length,
    parentPath: parentClusterPath(path),
    descendantLeafNodeIDs: new Set<string>(),
    directLeafNodeIDs: new Set<string>(),
    childClusterPaths: new Set<string>(),
    relatedSpanIDs: new Set<string>(),
  };
}

function createVisibleClusterNode(cluster: GraphClusterVM): GraphNodeVM {
  const clusterMetadata: Record<string, unknown> = {
    depth: cluster.depth,
    member_count: cluster.descendantLeafNodeIDs.length,
    direct_leaf_count: cluster.directLeafNodeIDs.length,
    child_cluster_count: cluster.childClusterPaths.length,
  };

  return {
    id: visibleClusterID(cluster.path),
    graphID: cluster.path,
    label: cluster.label,
    kind: 'subgraph',
    metadata: clusterMetadata,
    rawData: {
      path: cluster.path,
      members: cluster.descendantLeafNodeIDs,
      direct_leaves: cluster.directLeafNodeIDs,
      child_clusters: cluster.childClusterPaths,
    },
    level: 0,
    outgoing: [],
    incoming: [],
    relatedSpanIDs: cluster.relatedSpanIDs,
    pathSegments: pathSegments(cluster.path),
    clusterAncestors: cluster.parentPath ? clusterAncestorsForID(cluster.path) : [],
    leafNodeIDs: cluster.descendantLeafNodeIDs,
    memberCount: cluster.descendantLeafNodeIDs.length,
    isCluster: true,
    clusterPath: cluster.path,
    directLeafNodeIDs: cluster.directLeafNodeIDs,
    childClusterPaths: cluster.childClusterPaths,
  };
}

export function buildGraphModel(
  graph: AgentGraphDTO | undefined,
  spans: TraceSpanVM[],
): GraphModelVM {
  if (!graph) {
    return {
      rawNodes: [],
      rawEdges: [],
      clusters: [],
      clusterPaths: [],
    };
  }

  const rawNodes = graph.nodes.map((node) => {
    const id = normalizedID(node.id);
    return {
      id,
      graphID: id,
      label: nodeLabel(node),
      kind: node.type ?? 'node',
      metadata: node.metadata,
      rawData: node.data,
      relatedSpanIDs: relatedSpansForNode(node, spans),
      pathSegments: pathSegments(id),
      clusterAncestors: clusterAncestorsForID(id),
    } satisfies GraphRawNodeVM;
  });

  const rawEdges = graph.edges.map((edge, index) => ({
    id: `raw-edge-${index}-${normalizedID(edge.source)}-${normalizedID(edge.target)}`,
    source: normalizedID(edge.source),
    target: normalizedID(edge.target),
    conditional: Boolean(edge.conditional),
  }));

  const clusterMap = new Map<string, MutableCluster>();

  function ensureCluster(path: string): MutableCluster {
    const existing = clusterMap.get(path);
    if (existing) return existing;
    const created = createCluster(path);
    clusterMap.set(path, created);
    return created;
  }

  for (const node of rawNodes) {
    for (const path of node.clusterAncestors) {
      const cluster = ensureCluster(path);
      cluster.descendantLeafNodeIDs.add(node.id);
      for (const spanID of node.relatedSpanIDs) {
        cluster.relatedSpanIDs.add(spanID);
      }
    }

    const directParentPath = node.clusterAncestors.at(-1);
    if (directParentPath) {
      ensureCluster(directParentPath).directLeafNodeIDs.add(node.id);
    }
  }

  for (const path of clusterMap.keys()) {
    const parentPath = parentClusterPath(path);
    if (!parentPath) continue;
    ensureCluster(parentPath).childClusterPaths.add(path);
  }

  const clusters = Array.from(clusterMap.values())
    .map((cluster) => ({
      path: cluster.path,
      label: cluster.label,
      depth: cluster.depth,
      parentPath: cluster.parentPath,
      descendantLeafNodeIDs: Array.from(cluster.descendantLeafNodeIDs).sort(),
      directLeafNodeIDs: Array.from(cluster.directLeafNodeIDs).sort(),
      childClusterPaths: Array.from(cluster.childClusterPaths).sort(),
      relatedSpanIDs: Array.from(cluster.relatedSpanIDs).sort(),
    } satisfies GraphClusterVM))
    .sort((left, right) => {
      if (left.depth !== right.depth) return left.depth - right.depth;
      return left.path.localeCompare(right.path);
    });

  return {
    rawNodes,
    rawEdges,
    clusters,
    clusterPaths: clusters.map((cluster) => cluster.path),
  };
}

function representativeForNode(node: GraphRawNodeVM, collapsed: Set<string>): string {
  for (const path of node.clusterAncestors) {
    if (collapsed.has(path)) return visibleClusterID(path);
  }
  return node.id;
}

function addVisibleEdge(
  edgeMap: Map<string, MutableGraphEdge>,
  source: string,
  target: string,
  conditional: boolean,
): void {
  const id = `edge:${source}->${target}`;
  const existing = edgeMap.get(id);
  if (existing) {
    existing.rawEdgeCount += 1;
    existing.conditional = existing.conditional || conditional;
    return;
  }

  edgeMap.set(id, {
    id,
    source,
    target,
    conditional,
    rawEdgeCount: 1,
  });
}

export function buildVisibleGraph(
  model: GraphModelVM,
  collapsedClusterPaths: string[],
): GraphViewVM {
  if (model.rawNodes.length === 0) {
    return {
      nodes: [],
      edges: [],
      columns: [],
      expandedClusterPaths: [],
    };
  }

  const collapsed = new Set(collapsedClusterPaths);
  const clusterByPath = new Map(model.clusters.map((cluster) => [cluster.path, cluster]));
  const visibleNodes = new Map<string, GraphNodeVM>();
  const representativeByNodeID = new Map<string, string>();

  for (const rawNode of model.rawNodes) {
    const representative = representativeForNode(rawNode, collapsed);
    representativeByNodeID.set(rawNode.id, representative);

    if (representative === rawNode.id) {
      if (!visibleNodes.has(rawNode.id)) {
        visibleNodes.set(rawNode.id, {
          id: rawNode.id,
          graphID: rawNode.graphID,
          label: rawNode.label,
          kind: rawNode.kind,
          metadata: rawNode.metadata,
          rawData: rawNode.rawData,
          level: 0,
          outgoing: [],
          incoming: [],
          relatedSpanIDs: rawNode.relatedSpanIDs,
          pathSegments: rawNode.pathSegments,
          clusterAncestors: rawNode.clusterAncestors,
          leafNodeIDs: [rawNode.id],
          memberCount: 1,
          isCluster: false,
          directLeafNodeIDs: [rawNode.id],
          childClusterPaths: [],
        });
      }
      continue;
    }

    const clusterPath = parseVisibleClusterID(representative);
    if (!clusterPath) continue;

    const cluster = clusterByPath.get(clusterPath);
    if (!cluster || visibleNodes.has(representative)) continue;
    visibleNodes.set(representative, createVisibleClusterNode(cluster));
  }

  const edgeMap = new Map<string, MutableGraphEdge>();
  for (const edge of model.rawEdges) {
    const source = representativeByNodeID.get(edge.source);
    const target = representativeByNodeID.get(edge.target);
    if (!source || !target || source === target) continue;
    addVisibleEdge(edgeMap, source, target, edge.conditional);
  }

  const edges = Array.from(edgeMap.values())
    .map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      conditional: edge.conditional,
      rawEdgeCount: edge.rawEdgeCount,
    } satisfies GraphEdgeVM))
    .sort((left, right) => left.id.localeCompare(right.id));

  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const edge of edges) {
    outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
  }

  const levels = computeLevels(Array.from(visibleNodes.keys()), edges);
  const nodes = Array.from(visibleNodes.values())
    .map((node) => ({
      ...node,
      level: levels.get(node.id) ?? 0,
      outgoing: outgoing.get(node.id) ?? [],
      incoming: incoming.get(node.id) ?? [],
    }))
    .sort((left, right) => {
      if (left.level !== right.level) return left.level - right.level;
      if (left.isCluster !== right.isCluster) return left.isCluster ? -1 : 1;
      return left.label.localeCompare(right.label);
    });

  return {
    nodes,
    edges,
    columns: groupGraphColumns(nodes),
    expandedClusterPaths: model.clusterPaths.filter((path) => !collapsed.has(path)),
  };
}

export function groupGraphColumns(nodes: GraphNodeVM[]): Array<{ level: number; nodes: GraphNodeVM[] }> {
  const columns = new Map<number, GraphNodeVM[]>();
  for (const node of nodes) {
    const items = columns.get(node.level);
    if (items) {
      items.push(node);
    } else {
      columns.set(node.level, [node]);
    }
  }
  return Array.from(columns.entries())
    .sort((left, right) => left[0] - right[0])
    .map(([level, items]) => ({ level, nodes: items }));
}

export function buildGraphFocus(
  view: GraphViewVM,
  nodeID?: string,
): GraphFocusVM {
  const empty = {
    nodeID,
    upstreamNodeIDs: new Set<string>(),
    downstreamNodeIDs: new Set<string>(),
    upstreamEdgeIDs: new Set<string>(),
    downstreamEdgeIDs: new Set<string>(),
  } satisfies GraphFocusVM;

  if (!nodeID || !view.nodes.some((node) => node.id === nodeID)) return empty;

  const edgesBySource = new Map<string, GraphEdgeVM[]>();
  const edgesByTarget = new Map<string, GraphEdgeVM[]>();
  for (const edge of view.edges) {
    edgesBySource.set(edge.source, [...(edgesBySource.get(edge.source) ?? []), edge]);
    edgesByTarget.set(edge.target, [...(edgesByTarget.get(edge.target) ?? []), edge]);
  }

  const upstreamNodeIDs = new Set<string>([nodeID]);
  const downstreamNodeIDs = new Set<string>([nodeID]);
  const upstreamEdgeIDs = new Set<string>();
  const downstreamEdgeIDs = new Set<string>();

  const upstreamQueue = [nodeID];
  while (upstreamQueue.length > 0) {
    const current = upstreamQueue.shift()!;
    for (const edge of edgesByTarget.get(current) ?? []) {
      upstreamEdgeIDs.add(edge.id);
      if (!upstreamNodeIDs.has(edge.source)) {
        upstreamNodeIDs.add(edge.source);
        upstreamQueue.push(edge.source);
      }
    }
  }

  const downstreamQueue = [nodeID];
  while (downstreamQueue.length > 0) {
    const current = downstreamQueue.shift()!;
    for (const edge of edgesBySource.get(current) ?? []) {
      downstreamEdgeIDs.add(edge.id);
      if (!downstreamNodeIDs.has(edge.target)) {
        downstreamNodeIDs.add(edge.target);
        downstreamQueue.push(edge.target);
      }
    }
  }

  return {
    nodeID,
    upstreamNodeIDs,
    downstreamNodeIDs,
    upstreamEdgeIDs,
    downstreamEdgeIDs,
  };
}
