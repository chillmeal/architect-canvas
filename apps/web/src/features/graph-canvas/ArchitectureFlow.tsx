import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  MiniMap,
  ReactFlow,
  type EdgeTypes,
  type EdgeProps,
  type NodeTypes,
  type NodeProps,
  Position,
  getBezierPath,
  getSmoothStepPath
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { memo, useMemo } from "react";

import type { GraphProjectionResponse } from "../../api/client";
import {
  buildFlowGraph,
  type ArchitectureEdgeData,
  type ArchitectureFlowEdge,
  type ArchitectureFlowNode,
  type ArchitectureNodeData,
  type NodeBounds
} from "./graphLayout";

type Props = {
  projection: GraphProjectionResponse | null;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onSelectEdge: (edgeId: string) => void;
};

export function ArchitectureFlow({
  projection,
  selectedNodeId,
  selectedEdgeId,
  onSelectNode,
  onSelectEdge
}: Props) {
  const graph = useMemo(
    () => (projection ? buildFlowGraph(projection) : { nodes: [], edges: [] }),
    [projection]
  );
  const nodes = useMemo(
    () =>
      graph.nodes.map((node) => ({
        ...node,
        selected: node.id === selectedNodeId
      })),
    [graph.nodes, selectedNodeId]
  );
  const edges = useMemo(
    () =>
      graph.edges.map((edge) => ({
        ...edge,
        selected: edge.id === selectedEdgeId
      })),
    [graph.edges, selectedEdgeId]
  );

  if (!projection) {
    return (
      <div className="scope-empty" aria-live="polite">
        <div className="scope-empty__title">Архитектура ещё не построена</div>
        <div className="scope-empty__text">
          Создайте проект или запустите аудит, чтобы получить graph projection.
        </div>
      </div>
    );
  }

  return (
    <ReactFlow
      className="architecture-flow"
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      minZoom={0.35}
      maxZoom={1.6}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      onNodeClick={(_, node) => onSelectNode(node.id)}
      onEdgeClick={(_, edge) => onSelectEdge(edge.id)}
    >
      <Background color="var(--flow-grid)" gap={24} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(node) => {
          const data = node.data as ArchitectureNodeData;
          if (node.id === selectedNodeId) return "var(--green)";
          if (data.origin === "MANUAL") return "var(--yellow)";
          return data.isGroup ? "var(--minimap-group)" : "var(--minimap-node)";
        }}
      />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

const ArchitectureNode = memo(function ArchitectureNode({
  data,
  selected
}: NodeProps<ArchitectureFlowNode>) {
  if (data.isGroup) {
    return (
      <div
        className={[
          "architecture-node",
          "architecture-node--group",
          selected ? "is-selected" : "",
          data.validationState !== "CONFIRMED" ? "has-warning" : ""
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {data.nodeType === "AUTOMATED_SYSTEM" ? (
          <div className="architecture-node__system-head">
            <div className="architecture-node__type">{nodeTypeLabel(data.nodeType)}</div>
            <div className="architecture-node__system-title">{data.label}</div>
            <div className="architecture-node__system-meta">
              Автоматизированная система
            </div>
          </div>
        ) : (
          <div className="architecture-node__type">
            {nodeTypeLabel(data.nodeType)} · {data.label}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={[
        "architecture-node",
        "architecture-node--component",
        selected ? "is-selected" : "",
        data.origin === "MANUAL" ? "is-manual" : "",
        data.validationState !== "CONFIRMED" ? "has-warning" : ""
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="architecture-node__port architecture-node__port--left" />
      <span className="architecture-node__port architecture-node__port--right" />
      <span className="architecture-node__port architecture-node__port--top" />
      <span className="architecture-node__port architecture-node__port--bottom" />
      <div className="architecture-node__name">{data.label}</div>
    </div>
  );
});

const ArchitectureEdge = memo(function ArchitectureEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  selected,
  data
}: EdgeProps<ArchitectureFlowEdge>) {
  const route = buildEdgeRoute({
    sourceX,
    sourceY,
    targetX,
    targetY,
    bounds: data?.nodeBounds ?? []
  });
  const colorClass = data?.validationState === "CONFIRMED" ? "is-confirmed" : "has-warning";
  return (
    <>
      <BaseEdge
        id={id}
        path={route.path}
        className={["architecture-edge", colorClass, selected ? "is-selected" : ""]
          .filter(Boolean)
          .join(" ")}
      />
      {selected ? (
        <EdgeLabelRenderer>
        <button
          className="architecture-edge__label"
          style={{
            transform: `translate(-50%, -50%) translate(${route.labelX}px, ${route.labelY}px)`
          }}
          type="button"
          aria-label={`Связь ${data?.edgeType ?? id}`}
        >
          {edgeLabel(data)}
        </button>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
});

const nodeTypes = { architectureNode: ArchitectureNode } satisfies NodeTypes;
const edgeTypes = { architectureEdge: ArchitectureEdge } satisfies EdgeTypes;

function buildEdgeRoute({
  sourceX,
  sourceY,
  targetX,
  targetY,
  bounds
}: {
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  bounds: NodeBounds[];
}): { path: string; labelX: number; labelY: number } {
  const blocking = bounds.find((box) =>
    lineIntersectsBox(sourceX, sourceY, targetX, targetY, box, 18)
  );
  if (blocking) {
    const horizontal = Math.abs(targetX - sourceX) >= Math.abs(targetY - sourceY);
    const offset = horizontal ? blocking.y - 34 : blocking.x - 34;
    const midX = horizontal ? (sourceX + targetX) / 2 : offset;
    const midY = horizontal ? offset : (sourceY + targetY) / 2;
    const [path, labelX, labelY] = getSmoothStepPath({
      sourceX,
      sourceY,
      sourcePosition: horizontal ? Position.Right : Position.Bottom,
      targetX,
      targetY,
      targetPosition: horizontal ? Position.Left : Position.Top,
      centerX: midX,
      centerY: midY,
      borderRadius: 22
    });
    return { path, labelX, labelY };
  }
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition: sourceX <= targetX ? Position.Right : Position.Left,
    targetX,
    targetY,
    targetPosition: sourceX <= targetX ? Position.Left : Position.Right,
    curvature: 0.28
  });
  return { path, labelX, labelY };
}

function lineIntersectsBox(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  box: NodeBounds,
  padding: number
): boolean {
  const minX = box.x - padding;
  const maxX = box.x + box.width + padding;
  const minY = box.y - padding;
  const maxY = box.y + box.height + padding;
  const samples = 12;
  for (let index = 1; index < samples; index += 1) {
    const t = index / samples;
    const x = x1 + (x2 - x1) * t;
    const y = y1 + (y2 - y1) * t;
    if (x >= minX && x <= maxX && y >= minY && y <= maxY) return true;
  }
  return false;
}

function nodeTypeLabel(nodeType: string): string {
  const labels: Record<string, string> = {
    AUTOMATED_SYSTEM: "АС",
    FUNCTIONAL_SUBSYSTEM: "ФП",
    MODULE: "МОДУЛЬ",
    SUBMODULE: "ПОДМОДУЛЬ",
    MICROSERVICE: "СЕРВИС",
    APPLICATION_COMPONENT: "КОМПОНЕНТ",
    INFRA_COMPONENT: "ИНФРА",
    DATABASE: "БД",
    EXTERNAL_SYSTEM: "ВНЕШНЯЯ",
    API_ENDPOINT: "API"
  };
  return labels[nodeType] ?? nodeType;
}

function edgeLabel(data?: ArchitectureEdgeData): string {
  if (!data) return "Связь";
  return data.protocol ? `${data.edgeType} · ${data.protocol}` : data.edgeType;
}
