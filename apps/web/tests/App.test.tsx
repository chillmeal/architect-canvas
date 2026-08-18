import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import type { ArchitectureBackend } from "../src/api/architectureClient";
import type { GraphProjectionResponse } from "../src/api/client";
import { buildConnectionRoute } from "../src/features/architecture-workspace/connectionRouting";
import { buildArchitectureView } from "../src/features/architecture-workspace/model";
import { buildFlowGraph } from "../src/features/graph-canvas/graphLayout";

describe("App", () => {
  it("renders the React architecture workspace as the primary interface", async () => {
    const backend = createBackend();

    render(<App backend={backend} />);

    expect(screen.getByRole("main", { name: "Архитектура" })).toBeInTheDocument();
    expect(screen.queryByTitle("Архитектура")).not.toBeInTheDocument();
    expect(screen.getAllByText("Payments Platform").length).toBeGreaterThan(0);
    await waitFor(() => expect(backend.health).toHaveBeenCalled());
  });

  it("uses the mouse wheel for zoom and canvas drag for pan semantics", async () => {
    const { container } = render(<App backend={createBackend()} />);
    const canvas = container.querySelector<HTMLElement>(".canvas");

    expect(canvas).not.toBeNull();
    expect(screen.getByText("100%")).toBeInTheDocument();

    fireEvent.wheel(canvas!, { deltaY: -120, clientX: 500, clientY: 350 });

    await waitFor(() => expect(screen.queryByText("100%")).not.toBeInTheDocument());
  });

  it("highlights only the connector ports used by the selected relation", async () => {
    const { container } = render(<App backend={createBackend()} />);
    const fraudService = screen.getByRole("button", { name: "Fraud Service" });

    fireEvent.click(fraudService);
    const relation = container.querySelector<HTMLButtonElement>(
      '.connection-item[data-edge="fraud-events"]'
    );
    expect(relation).not.toBeNull();
    fireEvent.click(relation!);

    await waitFor(() => {
      expect(container.querySelectorAll('[data-node="fraud"] .port.is-connection-selected')).toHaveLength(1);
      expect(container.querySelectorAll('[data-node="events"] .port.is-connection-selected')).toHaveLength(1);
    });
    expect(container.querySelectorAll(".port.is-connection-selected")).toHaveLength(2);
    expect(container.querySelector('path[data-edge="fraud-events"]')).toHaveClass("connection-selected");
  });
});

describe("buildFlowGraph", () => {
  it("converts graph projection into flow nodes and relation edges", () => {
    const graph = buildFlowGraph(graphFixture);

    expect(graph.nodes.map((node) => node.id)).toEqual([
      "system-1",
      "subsystem-1",
      "service-2",
      "service-1"
    ]);
    expect(graph.edges).toHaveLength(1);
    expect(graph.edges[0].source).toBe("service-1");
    expect(graph.edges[0].target).toBe("service-2");
    expect(graph.edges[0].data?.nodeBounds.length).toBe(2);
  });
});

describe("buildArchitectureView", () => {
  it("renders flat real-audit components through a view-only fallback hierarchy", () => {
    const flatProjection: GraphProjectionResponse = {
      ...graphFixture,
      nodes: [
        nodeProjection("service-1", "MICROSERVICE", "Orders API"),
        nodeProjection("service-2", "MICROSERVICE", "Billing API")
      ],
      edges: [edgeProjection("sync-1", "service-1", "service-2", "SYNC_CALL")],
      hierarchy: []
    };

    const view = buildArchitectureView(flatProjection);

    expect(view.systems).toHaveLength(1);
    expect(view.systems[0].subsystems[0].className).toBe("fp-flat");
    expect(view.systems[0].subsystems[0].services.map((node) => node.id)).toEqual([
      "service-1",
      "service-2"
    ]);
    expect(view.nodeById.has("service-1")).toBe(true);
    expect(view.nodeById.has("service-2")).toBe(true);
    expect(view.relationEdges).toHaveLength(1);
  });
});

describe("buildConnectionRoute", () => {
  it("starts and ends exactly at the center of selected ports", () => {
    const route = buildConnectionRoute({
      source: { x: 10, y: 20, width: 100, height: 40 },
      target: { x: 220, y: 20, width: 80, height: 40 },
      sourcePort: "right",
      targetPort: "left"
    });

    expect(route.sourcePoint).toEqual({ x: 110, y: 40 });
    expect(route.targetPoint).toEqual({ x: 220, y: 40 });
    expect(route.path.startsWith("M 110 40")).toBe(true);
    expect(route.path.endsWith("L 220 40")).toBe(true);
  });

  it("rounds orthogonal bends without moving the endpoints", () => {
    const route = buildConnectionRoute({
      source: { x: 10, y: 20, width: 100, height: 40 },
      target: { x: 220, y: 130, width: 80, height: 40 }
    });

    expect(route.path.startsWith("M 110 40")).toBe(true);
    expect(route.path.endsWith("L 220 150")).toBe(true);
    expect(route.path).toContain("Q");
  });

  it("routes around unrelated obstacle boxes", () => {
    const obstacle = { x: 140, y: 10, width: 50, height: 70 };
    const route = buildConnectionRoute({
      source: { x: 10, y: 20, width: 100, height: 40 },
      target: { x: 260, y: 20, width: 80, height: 40 },
      sourcePort: "right",
      targetPort: "left",
      obstacles: [obstacle]
    });

    expect(polylineIntersectsRect(route.points, expandRect(obstacle, 18))).toBe(false);
  });
});

const graphFixture: GraphProjectionResponse = {
  graph_id: "snapshot-1",
  audit_id: "audit-1",
  project_id: "project-1",
  repository_state_id: "repo-state-1",
  schema_version: "1.0",
  status: "PUBLISHED",
  summary: {},
  nodes: [
    nodeProjection("system-1", "AUTOMATED_SYSTEM", "Payments Platform"),
    nodeProjection("subsystem-1", "FUNCTIONAL_SUBSYSTEM", "Customer Payments"),
    nodeProjection("service-1", "MICROSERVICE", "Orders API"),
    nodeProjection("service-2", "MICROSERVICE", "Billing API")
  ],
  edges: [
    edgeProjection("contains-1", "system-1", "subsystem-1", "CONTAINS"),
    edgeProjection("contains-2", "subsystem-1", "service-1", "CONTAINS"),
    edgeProjection("contains-3", "subsystem-1", "service-2", "CONTAINS"),
    edgeProjection("sync-1", "service-1", "service-2", "SYNC_CALL")
  ],
  hierarchy: [
    { edge_id: "contains-1", parent_node_id: "system-1", child_node_id: "subsystem-1" },
    { edge_id: "contains-2", parent_node_id: "subsystem-1", child_node_id: "service-1" },
    { edge_id: "contains-3", parent_node_id: "subsystem-1", child_node_id: "service-2" }
  ],
  revision: null,
  layout_hints: {},
  issue_counters: { total: 0 }
};

function nodeProjection(nodeId: string, nodeType: string, name: string) {
  return {
    node_id: nodeId,
    stable_key: `stable/${nodeId}`,
    node_type: nodeType,
    name,
    origin: "INFERRED",
    validation_state: "CONFIRMED",
    confidence: 0.92
  };
}

function edgeProjection(edgeId: string, source: string, target: string, edgeType: string) {
  return {
    edge_id: edgeId,
    source_node_id: source,
    target_node_id: target,
    edge_type: edgeType,
    origin: "INFERRED",
    validation_state: "CONFIRMED",
    confidence: 0.88,
    protocol: edgeType === "SYNC_CALL" ? "HTTP/REST" : null
  };
}

function polylineIntersectsRect(
  points: readonly { x: number; y: number }[],
  rect: { x: number; y: number; width: number; height: number }
) {
  for (let index = 1; index < points.length; index += 1) {
    if (segmentIntersectsRect(points[index - 1], points[index], rect)) return true;
  }
  return false;
}

function segmentIntersectsRect(
  start: { x: number; y: number },
  end: { x: number; y: number },
  rect: { x: number; y: number; width: number; height: number }
) {
  if (start.x === end.x) {
    const top = Math.min(start.y, end.y);
    const bottom = Math.max(start.y, end.y);
    return start.x > rect.x && start.x < rect.x + rect.width && bottom > rect.y && top < rect.y + rect.height;
  }
  if (start.y === end.y) {
    const left = Math.min(start.x, end.x);
    const right = Math.max(start.x, end.x);
    return start.y > rect.y && start.y < rect.y + rect.height && right > rect.x && left < rect.x + rect.width;
  }
  return true;
}

function expandRect(rect: { x: number; y: number; width: number; height: number }, clearance: number) {
  return {
    x: rect.x - clearance,
    y: rect.y - clearance,
    width: rect.width + clearance * 2,
    height: rect.height + clearance * 2
  };
}

function createBackend(): ArchitectureBackend {
  return {
    health: vi.fn(async () => ({ app_env: "test", status: "ok" })),
    listProjects: vi.fn(async () => []),
    createProject: vi.fn(async () => {
      throw new Error("not implemented");
    }),
    listProjectAudits: vi.fn(async () => []),
    startAudit: vi.fn(async () => {
      throw new Error("not implemented");
    }),
    getAudit: vi.fn(async () => {
      throw new Error("not implemented");
    }),
    getAuditGraph: vi.fn(async () => graphFixture),
    getGraphNode: vi.fn(async () => ({})),
    getGraphEdge: vi.fn(async () => {
      throw new Error("not implemented");
    }),
    createGraphRevision: vi.fn(async () => {
      throw new Error("not implemented");
    }),
    createGraphOverride: vi.fn(async () => {
      throw new Error("not implemented");
    }),
    commitGraphRevision: vi.fn(async () => {
      throw new Error("not implemented");
    }),
    deleteUnsavedManualNode: vi.fn(async () => undefined)
  };
}
