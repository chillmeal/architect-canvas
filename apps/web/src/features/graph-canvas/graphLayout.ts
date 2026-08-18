import type { Edge, Node } from "@xyflow/react";

import type {
  GraphEdgeProjectionResponse,
  GraphNodeProjectionResponse,
  GraphProjectionResponse
} from "../../api/client";

export type ArchitectureNodeData = Record<string, unknown> & {
  label: string;
  nodeType: string;
  origin: string;
  validationState: string;
  confidence: number;
  isGroup: boolean;
};

export type ArchitectureEdgeData = Record<string, unknown> & {
  edgeType: string;
  protocol: string | null;
  validationState: string;
  confidence: number;
  nodeBounds: NodeBounds[];
};

export type ArchitectureFlowNode = Node<ArchitectureNodeData, "architectureNode">;
export type ArchitectureFlowEdge = Edge<ArchitectureEdgeData, "architectureEdge">;

export type NodeBounds = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

type LayoutNode = GraphNodeProjectionResponse & {
  children: LayoutNode[];
  parentId: string | null;
  depth: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

const GROUP_TYPES = new Set(["AUTOMATED_SYSTEM", "FUNCTIONAL_SUBSYSTEM", "MODULE", "SUBMODULE"]);
const TYPE_ORDER = new Map([
  ["AUTOMATED_SYSTEM", 0],
  ["FUNCTIONAL_SUBSYSTEM", 1],
  ["MODULE", 2],
  ["SUBMODULE", 3],
  ["MICROSERVICE", 4],
  ["APPLICATION_COMPONENT", 4],
  ["INFRA_COMPONENT", 4],
  ["DATABASE", 4],
  ["EXTERNAL_SYSTEM", 4],
  ["API_ENDPOINT", 5],
  ["UNKNOWN", 6]
]);

const NODE_WIDTH = 178;
const NODE_HEIGHT = 48;
const NODE_GAP_X = 48;
const NODE_GAP_Y = 26;
const GROUP_PAD_X = 28;
const GROUP_PAD_TOP = 56;
const GROUP_PAD_BOTTOM = 28;
const ROOT_X = 40;
const ROOT_Y = 104;

export function buildFlowGraph(projection: GraphProjectionResponse): {
  nodes: ArchitectureFlowNode[];
  edges: ArchitectureFlowEdge[];
} {
  const layoutNodes = buildLayoutTree(projection);
  const roots = layoutNodes.filter((node) => node.parentId === null);
  let cursorY = ROOT_Y;
  for (const root of roots) {
    measure(root);
    place(root, ROOT_X, cursorY);
    cursorY += root.height + 52;
  }

  const orderedNodes = layoutNodes.sort((left, right) => {
    if (left.depth !== right.depth) return left.depth - right.depth;
    return left.y - right.y || left.x - right.x || left.name.localeCompare(right.name);
  });

  const nodes: ArchitectureFlowNode[] = orderedNodes.map((node) => {
    const isGroup = GROUP_TYPES.has(node.node_type);
    return {
      id: node.node_id,
      type: "architectureNode",
      position: { x: node.x, y: node.y },
      data: {
        label: node.name,
        nodeType: node.node_type,
        origin: node.origin,
        validationState: node.validation_state,
        confidence: node.confidence,
        isGroup
      },
      width: node.width,
      height: node.height,
      style: { width: node.width, height: node.height },
      draggable: false,
      zIndex: isGroup ? node.depth : 20
    };
  });

  const nodeBounds = orderedNodes
    .filter((node) => !GROUP_TYPES.has(node.node_type))
    .map((node) => ({
      id: node.node_id,
      x: node.x,
      y: node.y,
      width: node.width,
      height: node.height
    }));
  const hierarchyIds = new Set(projection.hierarchy.map((edge) => edge.edge_id));
  const relationEdges = projection.edges.filter((edge: GraphEdgeProjectionResponse) => {
    return edge.edge_type !== "CONTAINS" && !hierarchyIds.has(edge.edge_id);
  });

  return {
    nodes,
    edges: relationEdges.map((edge: GraphEdgeProjectionResponse) => ({
      id: edge.edge_id,
      type: "architectureEdge",
      source: edge.source_node_id,
      target: edge.target_node_id,
      data: {
        edgeType: edge.edge_type,
        protocol: edge.protocol,
        validationState: edge.validation_state,
        confidence: edge.confidence,
        nodeBounds
      }
    }))
  };
}

function buildLayoutTree(projection: GraphProjectionResponse): LayoutNode[] {
  const nodes = new Map<string, LayoutNode>();
  for (const node of projection.nodes) {
    nodes.set(node.node_id, {
      ...node,
      children: [],
      parentId: null,
      depth: typeDepth(node.node_type),
      x: 0,
      y: 0,
      width: GROUP_TYPES.has(node.node_type) ? 260 : NODE_WIDTH,
      height: GROUP_TYPES.has(node.node_type) ? 150 : NODE_HEIGHT
    });
  }

  for (const edge of projection.hierarchy) {
    const parent = nodes.get(edge.parent_node_id);
    const child = nodes.get(edge.child_node_id);
    if (!parent || !child) continue;
    parent.children.push(child);
    child.parentId = parent.node_id;
    child.depth = Math.max(typeDepth(child.node_type), parent.depth + 1);
  }

  for (const node of nodes.values()) {
    node.children.sort(compareLayoutNode);
  }
  return [...nodes.values()];
}

function measure(node: LayoutNode): { width: number; height: number } {
  if (!GROUP_TYPES.has(node.node_type)) {
    node.width = Math.max(NODE_WIDTH, Math.min(240, 104 + node.name.length * 6));
    node.height = NODE_HEIGHT;
    return { width: node.width, height: node.height };
  }

  if (node.children.length === 0) {
    node.width = 320;
    node.height = node.node_type === "AUTOMATED_SYSTEM" ? 180 : 136;
    return { width: node.width, height: node.height };
  }

  const children = node.children.map((child) => {
    const size = measure(child);
    return { node: child, ...size };
  });
  const leafChildren = children.filter((child) => !GROUP_TYPES.has(child.node.node_type));
  const groupChildren = children.filter((child) => GROUP_TYPES.has(child.node.node_type));
  const rowWidth = (items: typeof children) =>
    items.reduce((sum, child) => sum + child.width, 0) + Math.max(0, items.length - 1) * NODE_GAP_X;

  const contentWidth = Math.max(rowWidth(groupChildren), rowWidth(leafChildren), NODE_WIDTH);
  const groupHeight = groupChildren.length ? Math.max(...groupChildren.map((child) => child.height)) : 0;
  const leafHeight = leafChildren.length ? NODE_HEIGHT : 0;
  node.width = Math.max(260, contentWidth + GROUP_PAD_X * 2);
  node.height =
    GROUP_PAD_TOP +
    groupHeight +
    (groupChildren.length && leafChildren.length ? NODE_GAP_Y : 0) +
    leafHeight +
    GROUP_PAD_BOTTOM;

  return { width: node.width, height: node.height };
}

function place(node: LayoutNode, x: number, y: number): void {
  node.x = x;
  node.y = y;
  if (!GROUP_TYPES.has(node.node_type)) return;

  const groupChildren = node.children.filter((child) => GROUP_TYPES.has(child.node_type));
  const leafChildren = node.children.filter((child) => !GROUP_TYPES.has(child.node_type));
  let childY = y + GROUP_PAD_TOP;
  placeRow(groupChildren, x + GROUP_PAD_X, childY, node.width - GROUP_PAD_X * 2);
  if (groupChildren.length) {
    childY += Math.max(...groupChildren.map((child) => child.height)) + NODE_GAP_Y;
  }
  placeRow(leafChildren, x + GROUP_PAD_X, childY, node.width - GROUP_PAD_X * 2);
}

function placeRow(children: LayoutNode[], x: number, y: number, availableWidth: number): void {
  if (!children.length) return;
  const totalWidth =
    children.reduce((sum, child) => sum + child.width, 0) + Math.max(0, children.length - 1) * NODE_GAP_X;
  let childX = x + Math.max(0, (availableWidth - totalWidth) / 2);
  for (const child of children) {
    place(child, childX, y);
    childX += child.width + NODE_GAP_X;
  }
}

function compareLayoutNode(left: LayoutNode, right: LayoutNode): number {
  return typeDepth(left.node_type) - typeDepth(right.node_type) || left.name.localeCompare(right.name);
}

function typeDepth(nodeType: string): number {
  return TYPE_ORDER.get(nodeType) ?? 6;
}
