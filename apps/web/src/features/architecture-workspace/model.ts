import type {
  GraphEdgeProjectionResponse,
  GraphHierarchyEdgeResponse,
  GraphNodeProjectionResponse,
  GraphProjectionResponse
} from "../../api/client";
import type { PortSide } from "./connectionRouting";

export type ArchitectureScope = {
  id: string;
  nodeId: string;
  systemId: string;
  kind: "system" | "functional-subsystem";
  label: string;
  displayLabel: string;
  viewScope: "system" | "customer-payments" | "settlement-clearing" | "empty";
};

export type VisualNode = {
  id: string;
  name: string;
  nodeType: string;
  origin: string;
  validationState: string;
  confidence: number;
  kind: "service" | "event";
  className: string;
  ports: PortSide[];
  scopeKey: string;
  position?: { left: number; top: number; width: number };
};

export type VisualSubmodule = {
  id: string;
  label: string;
  className: string;
  services: VisualNode[];
};

export type VisualModule = {
  id: string;
  label: string;
  className: string;
  submodules: VisualSubmodule[];
  services: VisualNode[];
};

export type VisualFunctionalSubsystem = {
  id: string;
  label: string;
  className: string;
  scopeKey: string;
  modules: VisualModule[];
  services: VisualNode[];
};

export type VisualSystem = {
  id: string;
  label: string;
  meta: string;
  subsystems: VisualFunctionalSubsystem[];
  eventNodes: VisualNode[];
};

export type VisualEdge = {
  id: string;
  sourceNodeId: string;
  targetNodeId: string;
  edgeType: string;
  protocol: string | null;
  protocolLabel: string;
  validationState: string;
  confidence: number;
  active: boolean;
  scopeKey: string;
  sourcePort?: PortSide;
  targetPort?: PortSide;
};

export type HierarchyLine = {
  text: string;
  selected: boolean;
};

export type ArchitectureViewModel = {
  systems: VisualSystem[];
  scopes: ArchitectureScope[];
  relationEdges: VisualEdge[];
  nodeById: Map<string, VisualNode>;
  sourceNodeById: Map<string, GraphNodeProjectionResponse>;
  parentByNodeId: Map<string, string>;
  hierarchyLinesByNodeId: Map<string, HierarchyLine[]>;
};

const GROUP_NODE_TYPES = new Set([
  "AUTOMATED_SYSTEM",
  "FUNCTIONAL_SUBSYSTEM",
  "MODULE",
  "SUBMODULE"
]);
const EVENT_NODE_TYPES = new Set(["MESSAGE_BROKER", "TOPIC"]);
const SYSTEM_NODE_TYPES = new Set(["AUTOMATED_SYSTEM"]);
const FUNCTIONAL_SUBSYSTEM_NODE_TYPES = new Set(["FUNCTIONAL_SUBSYSTEM"]);
const MODULE_NODE_TYPES = new Set(["MODULE"]);
const SUBMODULE_NODE_TYPES = new Set(["SUBMODULE"]);

const SERVICE_CLASS_BY_NAME = new Map([
  ["payment orchestrator", "s-orchestrator"],
  ["retry worker", "s-retry"],
  ["customer api", "s-api"],
  ["fraud service", "s-fraud"],
  ["settlement service", "s-settlement"],
  ["ledger adapter", "s-ledger-adapter"],
  ["ledger gateway", "s-ledger-gateway"],
  ["reconciliation worker", "s-recon"]
]);

const SUBSYSTEM_CLASS_BY_NAME = new Map([
  ["customer payments", "fp-customer"],
  ["settlement & clearing", "fp-settlement"]
]);

const MODULE_CLASS_BY_NAME = new Map([
  ["orchestration", "module-orchestration"],
  ["api edge", "module-api"],
  ["fraud & risk", "module-fraud"],
  ["settlement engine", "module-settlement"],
  ["ledger sync", "module-ledger"],
  ["reconciliation", "module-recon"]
]);

const SUBMODULE_CLASS_BY_NAME = new Map([
  ["routing", "sub-routing"],
  ["retry", "sub-retry"],
  ["ledger", "sub-ledger"]
]);

const SUBSYSTEM_CLASS_SLOTS = ["fp-customer", "fp-settlement"];
const MODULE_CLASS_SLOTS = [
  ["module-orchestration", "module-api", "module-fraud"],
  ["module-settlement", "module-ledger", "module-recon"]
];
const SUBMODULE_CLASS_SLOTS = ["sub-routing", "sub-retry", "sub-ledger"];
const SERVICE_CLASS_SLOTS = [
  "s-orchestrator",
  "s-retry",
  "s-api",
  "s-fraud",
  "s-settlement",
  "s-ledger-adapter",
  "s-ledger-gateway",
  "s-recon"
];

const PORT_ORDER: readonly PortSide[] = ["left", "right", "top", "bottom"];

export function buildArchitectureView(
  projection: GraphProjectionResponse
): ArchitectureViewModel {
  const sourceNodeById = new Map(projection.nodes.map((node) => [node.node_id, node]));
  const hierarchyEdgeIds = new Set(projection.hierarchy.map((edge) => edge.edge_id));
  const parentByNodeId = new Map<string, string>();
  const childIdsByParentId = new Map<string, string[]>();

  for (const edge of projection.hierarchy) {
    parentByNodeId.set(edge.child_node_id, edge.parent_node_id);
    const children = childIdsByParentId.get(edge.parent_node_id) ?? [];
    children.push(edge.child_node_id);
    childIdsByParentId.set(edge.parent_node_id, children);
  }

  const relationEdges = projection.edges.filter(
    (edge) => edge.edge_type !== "CONTAINS" && !hierarchyEdgeIds.has(edge.edge_id)
  );
  const portSidesByNodeId = collectPortSides(relationEdges);
  const nodeById = new Map<string, VisualNode>();
  let systems = getSystemNodes(projection.nodes, parentByNodeId).map((systemNode) => {
    const subsystems = childrenOf(
      systemNode.node_id,
      childIdsByParentId,
      sourceNodeById,
      FUNCTIONAL_SUBSYSTEM_NODE_TYPES
    ).map((subsystemNode, subsystemIndex) =>
      buildSubsystem(
        subsystemNode,
        subsystemIndex,
        childIdsByParentId,
        sourceNodeById,
        portSidesByNodeId,
        nodeById
      )
    );
    const eventNodes = childrenOf(systemNode.node_id, childIdsByParentId, sourceNodeById)
      .filter(isEventNode)
      .map((node, index) =>
        buildVisualNode(node, index, "system", portSidesByNodeId, nodeById)
      );

    return {
      id: systemNode.node_id,
      label: systemNode.name,
      meta: systemMeta(subsystems, eventNodes),
      subsystems,
      eventNodes
    };
  });

  if (nodeById.size === 0) {
    const flatSystem = buildFlatFallbackSystem(projection.nodes, portSidesByNodeId, nodeById);
    if (flatSystem) systems = [flatSystem];
  }

  const scopes: ArchitectureScope[] = systems.flatMap((system) => [
    {
      id: `scope:${system.id}`,
      nodeId: system.id,
      systemId: system.id,
      kind: "system" as const,
      label: system.label,
      displayLabel: system.label,
      viewScope: (system.subsystems.length || system.eventNodes.length ? "system" : "empty") as ArchitectureScope["viewScope"]
    },
    ...system.subsystems.map((subsystem) => ({
      id: `scope:${subsystem.id}`,
      nodeId: subsystem.id,
      systemId: system.id,
      kind: "functional-subsystem" as const,
      label: subsystem.label,
      displayLabel: `${system.label} / ${subsystem.label}`,
      viewScope: subsystemViewScope(subsystem)
    }))
  ]);

  const visualRelationEdges = relationEdges.map((edge) =>
    buildVisualEdge(edge, sourceNodeById, parentByNodeId)
  );
  const hierarchyLinesByNodeId = new Map<string, HierarchyLine[]>();
  for (const node of projection.nodes) {
    hierarchyLinesByNodeId.set(
      node.node_id,
      buildHierarchyLines(node.node_id, sourceNodeById, parentByNodeId)
    );
  }

  return {
    systems,
    scopes,
    relationEdges: visualRelationEdges,
    nodeById,
    sourceNodeById,
    parentByNodeId,
    hierarchyLinesByNodeId
  };
}

export function createManualNodeProjection({
  nodeId,
  nodeType,
  name
}: {
  nodeId: string;
  nodeType: string;
  name: string;
}): GraphNodeProjectionResponse {
  return {
    node_id: nodeId,
    stable_key: `manual/${nodeType}/${slugify(name)}-${nodeId}`,
    node_type: nodeType,
    name,
    origin: "MANUAL",
    validation_state: "CONFIRMED",
    confidence: 1
  };
}

export function addManualNodeToProjection(
  projection: GraphProjectionResponse,
  node: GraphNodeProjectionResponse,
  parentNodeId: string | null
): GraphProjectionResponse {
  if (!parentNodeId) {
    return { ...projection, nodes: [...projection.nodes, node] };
  }

  const edgeId = `manual-contains-${parentNodeId}-${node.node_id}`;
  const edge: GraphEdgeProjectionResponse = {
    edge_id: edgeId,
    source_node_id: parentNodeId,
    target_node_id: node.node_id,
    edge_type: "CONTAINS",
    origin: "MANUAL",
    validation_state: "CONFIRMED",
    confidence: 1,
    protocol: null
  };
  const hierarchy: GraphHierarchyEdgeResponse = {
    edge_id: edgeId,
    parent_node_id: parentNodeId,
    child_node_id: node.node_id
  };

  return {
    ...projection,
    nodes: [...projection.nodes, node],
    edges: [...projection.edges, edge],
    hierarchy: [...projection.hierarchy, hierarchy]
  };
}

export function removeNodeSubtreeFromProjection(
  projection: GraphProjectionResponse,
  nodeId: string
): GraphProjectionResponse {
  const childrenByParentId = new Map<string, string[]>();
  for (const edge of projection.hierarchy) {
    const children = childrenByParentId.get(edge.parent_node_id) ?? [];
    children.push(edge.child_node_id);
    childrenByParentId.set(edge.parent_node_id, children);
  }

  const removedNodeIds = new Set<string>();
  collectDescendants(nodeId, childrenByParentId, removedNodeIds);

  return {
    ...projection,
    nodes: projection.nodes.filter((node) => !removedNodeIds.has(node.node_id)),
    edges: projection.edges.filter(
      (edge) =>
        !removedNodeIds.has(edge.source_node_id) && !removedNodeIds.has(edge.target_node_id)
    ),
    hierarchy: projection.hierarchy.filter(
      (edge) =>
        !removedNodeIds.has(edge.parent_node_id) && !removedNodeIds.has(edge.child_node_id)
    )
  };
}

export function slugify(value: string): string {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9а-яё]+/giu, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "node";
}

export function nodeTypeLabel(nodeType: string): string {
  const labels: Record<string, string> = {
    AUTOMATED_SYSTEM: "АС",
    FUNCTIONAL_SUBSYSTEM: "ФП",
    MODULE: "МОДУЛЬ",
    SUBMODULE: "ПОДМОДУЛЬ",
    MICROSERVICE: "СЕРВИС",
    APPLICATION_COMPONENT: "КОМПОНЕНТ",
    INFRA_COMPONENT: "ИНФРА",
    MESSAGE_BROKER: "БРОКЕР",
    TOPIC: "ТОПИК",
    DATABASE: "БД",
    EXTERNAL_SYSTEM: "ВНЕШНЯЯ",
    API_ENDPOINT: "API"
  };
  return labels[nodeType] ?? nodeType;
}

function buildSubsystem(
  node: GraphNodeProjectionResponse,
  subsystemIndex: number,
  childIdsByParentId: Map<string, string[]>,
  sourceNodeById: Map<string, GraphNodeProjectionResponse>,
  portSidesByNodeId: Map<string, Set<PortSide>>,
  nodeById: Map<string, VisualNode>
): VisualFunctionalSubsystem {
  const modules = childrenOf(
    node.node_id,
    childIdsByParentId,
    sourceNodeById,
    MODULE_NODE_TYPES
  ).map((moduleNode, moduleIndex) =>
    buildModule(
      moduleNode,
      subsystemIndex,
      moduleIndex,
      childIdsByParentId,
      sourceNodeById,
      portSidesByNodeId,
      nodeById
    )
  );
  const services = childrenOf(node.node_id, childIdsByParentId, sourceNodeById)
    .filter((child) => isLeafNode(child) && !isEventNode(child))
    .map((serviceNode, index) =>
      buildVisualNode(serviceNode, index, subsystemScopeKey(node), portSidesByNodeId, nodeById)
    );

  return {
    id: node.node_id,
    label: node.name,
    className:
      SUBSYSTEM_CLASS_BY_NAME.get(normalizeName(node.name)) ??
      SUBSYSTEM_CLASS_SLOTS[subsystemIndex] ??
      SUBSYSTEM_CLASS_SLOTS[SUBSYSTEM_CLASS_SLOTS.length - 1],
    scopeKey: subsystemScopeKey(node),
    modules,
    services
  };
}

function buildModule(
  node: GraphNodeProjectionResponse,
  subsystemIndex: number,
  moduleIndex: number,
  childIdsByParentId: Map<string, string[]>,
  sourceNodeById: Map<string, GraphNodeProjectionResponse>,
  portSidesByNodeId: Map<string, Set<PortSide>>,
  nodeById: Map<string, VisualNode>
): VisualModule {
  const submodules = childrenOf(
    node.node_id,
    childIdsByParentId,
    sourceNodeById,
    SUBMODULE_NODE_TYPES
  ).map((submoduleNode, submoduleIndex) =>
    buildSubmodule(
      submoduleNode,
      submoduleIndex,
      childIdsByParentId,
      sourceNodeById,
      portSidesByNodeId,
      nodeById
    )
  );
  const services = childrenOf(node.node_id, childIdsByParentId, sourceNodeById)
    .filter((child) => isLeafNode(child) && !isEventNode(child))
    .map((serviceNode, index) =>
      buildVisualNode(serviceNode, moduleIndex * 2 + index, "module", portSidesByNodeId, nodeById)
    );

  return {
    id: node.node_id,
    label: node.name,
    className:
      MODULE_CLASS_BY_NAME.get(normalizeName(node.name)) ??
      MODULE_CLASS_SLOTS[subsystemIndex]?.[moduleIndex] ??
      MODULE_CLASS_SLOTS[0][Math.min(moduleIndex, MODULE_CLASS_SLOTS[0].length - 1)],
    submodules,
    services
  };
}

function buildSubmodule(
  node: GraphNodeProjectionResponse,
  submoduleIndex: number,
  childIdsByParentId: Map<string, string[]>,
  sourceNodeById: Map<string, GraphNodeProjectionResponse>,
  portSidesByNodeId: Map<string, Set<PortSide>>,
  nodeById: Map<string, VisualNode>
): VisualSubmodule {
  const services = childrenOf(node.node_id, childIdsByParentId, sourceNodeById)
    .filter((child) => isLeafNode(child) && !isEventNode(child))
    .map((serviceNode, index) =>
      buildVisualNode(serviceNode, submoduleIndex * 2 + index, "submodule", portSidesByNodeId, nodeById)
    );

  return {
    id: node.node_id,
    label: node.name,
    className:
      SUBMODULE_CLASS_BY_NAME.get(normalizeName(node.name)) ??
      SUBMODULE_CLASS_SLOTS[submoduleIndex] ??
      SUBMODULE_CLASS_SLOTS[SUBMODULE_CLASS_SLOTS.length - 1],
    services
  };
}

function buildVisualNode(
  node: GraphNodeProjectionResponse,
  index: number,
  scopeKey: string,
  portSidesByNodeId: Map<string, Set<PortSide>>,
  nodeById: Map<string, VisualNode>,
  position?: VisualNode["position"]
): VisualNode {
  const kind: VisualNode["kind"] = isEventNode(node) ? "event" : "service";
  const visualNode: VisualNode = {
    id: node.node_id,
    name: node.name,
    nodeType: node.node_type,
    origin: node.origin,
    validationState: node.validation_state,
    confidence: node.confidence,
    kind,
    className:
      kind === "event"
        ? ""
        : SERVICE_CLASS_BY_NAME.get(normalizeName(node.name)) ??
          SERVICE_CLASS_SLOTS[index] ??
          SERVICE_CLASS_SLOTS[SERVICE_CLASS_SLOTS.length - 1],
    ports: sortedPorts(portSidesByNodeId.get(node.node_id), kind),
    scopeKey,
    position
  };
  nodeById.set(node.node_id, visualNode);
  return visualNode;
}

function buildFlatFallbackSystem(
  nodes: GraphNodeProjectionResponse[],
  portSidesByNodeId: Map<string, Set<PortSide>>,
  nodeById: Map<string, VisualNode>
): VisualSystem | null {
  const leafNodes = nodes.filter(isLeafNode);
  if (!leafNodes.length) return null;

  const columns = 4;
  const services = leafNodes.map((node, index) =>
    buildVisualNode(
      node,
      index,
      "detected",
      portSidesByNodeId,
      nodeById,
      {
        left: 38 + (index % columns) * 244,
        top: 68 + Math.floor(index / columns) * 78,
        width: 190
      }
    )
  );
  const subsystem: VisualFunctionalSubsystem = {
    id: "view-detected-subsystem",
    label: "Найденные компоненты",
    className: "fp-flat",
    scopeKey: "detected",
    modules: [],
    services
  };
  return {
    id: "view-detected-system",
    label: "Архитектура репозитория",
    meta: `Найдено компонентов: ${services.length}`,
    subsystems: [subsystem],
    eventNodes: []
  };
}

function buildVisualEdge(
  edge: GraphEdgeProjectionResponse,
  sourceNodeById: Map<string, GraphNodeProjectionResponse>,
  parentByNodeId: Map<string, string>
): VisualEdge {
  const sourceSubsystem = findAncestorOfType(
    edge.source_node_id,
    "FUNCTIONAL_SUBSYSTEM",
    sourceNodeById,
    parentByNodeId
  );
  const targetSubsystem = findAncestorOfType(
    edge.target_node_id,
    "FUNCTIONAL_SUBSYSTEM",
    sourceNodeById,
    parentByNodeId
  );
  const scopeKey = subsystemScopeKey(sourceSubsystem ?? targetSubsystem);

  return {
    id: edge.edge_id,
    sourceNodeId: edge.source_node_id,
    targetNodeId: edge.target_node_id,
    edgeType: edge.edge_type,
    protocol: edge.protocol,
    protocolLabel: edgeProtocolLabel(edge),
    validationState: edge.validation_state,
    confidence: edge.confidence,
    active: edge.validation_state === "CONFIRMED" && edge.confidence >= 0.85,
    scopeKey
  };
}

function collectPortSides(
  edges: GraphEdgeProjectionResponse[]
): Map<string, Set<PortSide>> {
  const ports = new Map<string, Set<PortSide>>();
  for (const edge of edges) {
    for (const side of PORT_ORDER) {
      addPort(ports, edge.source_node_id, side);
      addPort(ports, edge.target_node_id, side);
    }
  }
  return ports;
}

function addPort(ports: Map<string, Set<PortSide>>, nodeId: string, side: PortSide): void {
  const nodePorts = ports.get(nodeId) ?? new Set<PortSide>();
  nodePorts.add(side);
  ports.set(nodeId, nodePorts);
}

function sortedPorts(portSet: Set<PortSide> | undefined, kind: "service" | "event"): PortSide[] {
  if (!portSet || !portSet.size) {
    return kind === "event" ? ["left", "right", "top", "bottom"] : ["left", "right"];
  }
  return PORT_ORDER.filter((side) => portSet.has(side));
}

function getSystemNodes(
  nodes: GraphNodeProjectionResponse[],
  parentByNodeId: Map<string, string>
): GraphNodeProjectionResponse[] {
  const systems = nodes.filter((node) => SYSTEM_NODE_TYPES.has(node.node_type));
  if (systems.length) return systems;
  const root = nodes.find((node) => !parentByNodeId.has(node.node_id));
  if (!root) {
    return [
      {
        node_id: "empty-system",
        stable_key: "empty/system",
        node_type: "AUTOMATED_SYSTEM",
        name: "Architecture",
        origin: "MANUAL",
        validation_state: "REVIEW_REQUIRED",
        confidence: 0
      }
    ];
  }
  return [{ ...root, node_type: "AUTOMATED_SYSTEM" }];
}

function childrenOf(
  parentId: string,
  childIdsByParentId: Map<string, string[]>,
  sourceNodeById: Map<string, GraphNodeProjectionResponse>,
  allowedTypes?: Set<string>
): GraphNodeProjectionResponse[] {
  return (childIdsByParentId.get(parentId) ?? [])
    .map((childId) => sourceNodeById.get(childId))
    .filter((node): node is GraphNodeProjectionResponse => {
      if (!node) return false;
      return allowedTypes ? allowedTypes.has(node.node_type) : true;
    });
}

function isLeafNode(node: GraphNodeProjectionResponse): boolean {
  return !GROUP_NODE_TYPES.has(node.node_type);
}

function isEventNode(node: GraphNodeProjectionResponse): boolean {
  return EVENT_NODE_TYPES.has(node.node_type) || /\.events$/i.test(node.name);
}

function normalizeName(name: string): string {
  return name.trim().toLowerCase();
}

function subsystemViewScope(
  subsystem: VisualFunctionalSubsystem
): ArchitectureScope["viewScope"] {
  if (!subsystem.modules.length && !subsystem.services.length) return "empty";
  if (subsystem.scopeKey === "customer") return "customer-payments";
  if (subsystem.scopeKey === "settlement") return "settlement-clearing";
  return "system";
}

function subsystemScopeKey(node: GraphNodeProjectionResponse | undefined): string {
  if (!node) return "system";
  const normalized = normalizeName(node.name);
  if (normalized === "customer payments") return "customer";
  if (normalized === "settlement & clearing") return "settlement";
  return slugify(node.name);
}

function edgeProtocolLabel(edge: GraphEdgeProjectionResponse): string {
  const interaction = edge.edge_type.startsWith("ASYNC_")
    ? "Асинхронное"
    : edge.edge_type === "DEPENDS_ON"
      ? "Внутренняя"
      : "Синхронное";
  return edge.protocol ? `${interaction} · ${edge.protocol}` : `${interaction} · ${edge.edge_type}`;
}

function findAncestorOfType(
  nodeId: string,
  nodeType: string,
  sourceNodeById: Map<string, GraphNodeProjectionResponse>,
  parentByNodeId: Map<string, string>
): GraphNodeProjectionResponse | undefined {
  let currentId: string | undefined = nodeId;
  while (currentId) {
    const node = sourceNodeById.get(currentId);
    if (node?.node_type === nodeType) return node;
    currentId = parentByNodeId.get(currentId);
  }
  return undefined;
}

function buildHierarchyLines(
  nodeId: string,
  sourceNodeById: Map<string, GraphNodeProjectionResponse>,
  parentByNodeId: Map<string, string>
): HierarchyLine[] {
  const path: GraphNodeProjectionResponse[] = [];
  let currentId: string | undefined = nodeId;
  while (currentId) {
    const node = sourceNodeById.get(currentId);
    if (!node) break;
    path.unshift(node);
    currentId = parentByNodeId.get(currentId);
  }

  return path.map((node, index) => ({
    text: `${indent(index)}${index === 0 ? "" : "└ "}${nodeTypeLabel(node.node_type)} · ${node.name}`,
    selected: node.node_id === nodeId
  }));
}

function indent(level: number): string {
  return "   ".repeat(Math.max(0, level));
}

function systemMeta(subsystems: VisualFunctionalSubsystem[], eventNodes: VisualNode[]): string {
  const moduleCount = subsystems.reduce((sum, subsystem) => sum + subsystem.modules.length, 0);
  const submoduleCount = subsystems.reduce(
    (sum, subsystem) =>
      sum + subsystem.modules.reduce((moduleSum, module) => moduleSum + module.submodules.length, 0),
    0
  );
  const serviceCount =
    eventNodes.length +
    subsystems.reduce(
      (sum, subsystem) =>
        sum +
        subsystem.services.length +
        subsystem.modules.reduce(
          (moduleSum, module) =>
            moduleSum +
            module.services.length +
            module.submodules.reduce(
              (submoduleSum, submodule) => submoduleSum + submodule.services.length,
              0
            ),
          0
        ),
      0
    );

  return [
    "Автоматизированная система",
    `${subsystems.length} ФП`,
    `${moduleCount} ${pluralRu(moduleCount, "модуль", "модуля", "модулей")}`,
    `${submoduleCount} ${pluralRu(submoduleCount, "подмодуль", "подмодуля", "подмодулей")}`,
    `${serviceCount} ${pluralRu(serviceCount, "сервис", "сервиса", "сервисов")}`
  ].join(" · ");
}

function pluralRu(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function collectDescendants(
  nodeId: string,
  childrenByParentId: Map<string, string[]>,
  removedNodeIds: Set<string>
): void {
  removedNodeIds.add(nodeId);
  for (const childId of childrenByParentId.get(nodeId) ?? []) {
    collectDescendants(childId, childrenByParentId, removedNodeIds);
  }
}
