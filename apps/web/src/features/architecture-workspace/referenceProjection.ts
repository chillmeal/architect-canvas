import type {
  GraphEdgeProjectionResponse,
  GraphHierarchyEdgeResponse,
  GraphNodeProjectionResponse,
  GraphProjectionResponse
} from "../../api/client";

export const referenceGraphProjection: GraphProjectionResponse = {
  graph_id: "reference-snapshot",
  audit_id: "reference-audit",
  project_id: "reference-project",
  repository_state_id: "reference-repository-state",
  schema_version: "0.1.0",
  status: "PUBLISHED",
  summary: { source: "reference-ui" },
  nodes: [
    node("system-payments", "AUTOMATED_SYSTEM", "Payments Platform"),
    node("fp-customer-payments", "FUNCTIONAL_SUBSYSTEM", "Customer Payments"),
    node("fp-settlement-clearing", "FUNCTIONAL_SUBSYSTEM", "Settlement & Clearing"),
    node("module-orchestration", "MODULE", "Orchestration"),
    node("module-api-edge", "MODULE", "API Edge"),
    node("module-fraud-risk", "MODULE", "Fraud & Risk"),
    node("module-settlement-engine", "MODULE", "Settlement Engine"),
    node("module-ledger-sync", "MODULE", "Ledger Sync"),
    node("module-reconciliation", "MODULE", "Reconciliation"),
    node("sub-routing", "SUBMODULE", "routing"),
    node("sub-retry", "SUBMODULE", "retry"),
    node("sub-ledger", "SUBMODULE", "ledger"),
    node("orchestrator", "MICROSERVICE", "Payment Orchestrator"),
    node("retry", "MICROSERVICE", "Retry Worker"),
    node("api", "MICROSERVICE", "Customer API"),
    node("fraud", "MICROSERVICE", "Fraud Service"),
    node("events", "TOPIC", "payments.events"),
    node("settlement", "MICROSERVICE", "Settlement Service"),
    node("ledger-adapter", "MICROSERVICE", "Ledger Adapter"),
    node("ledger-gateway", "MICROSERVICE", "Ledger Gateway"),
    node("recon", "MICROSERVICE", "Reconciliation Worker")
  ],
  edges: [
    contains("contains-system-customer", "system-payments", "fp-customer-payments"),
    contains("contains-system-settlement", "system-payments", "fp-settlement-clearing"),
    contains("contains-system-events", "system-payments", "events"),
    contains("contains-customer-orchestration", "fp-customer-payments", "module-orchestration"),
    contains("contains-customer-api", "fp-customer-payments", "module-api-edge"),
    contains("contains-customer-fraud", "fp-customer-payments", "module-fraud-risk"),
    contains("contains-settlement-engine", "fp-settlement-clearing", "module-settlement-engine"),
    contains("contains-settlement-ledger", "fp-settlement-clearing", "module-ledger-sync"),
    contains("contains-settlement-recon", "fp-settlement-clearing", "module-reconciliation"),
    contains("contains-orchestration-routing", "module-orchestration", "sub-routing"),
    contains("contains-orchestration-retry", "module-orchestration", "sub-retry"),
    contains("contains-ledger-sub", "module-ledger-sync", "sub-ledger"),
    contains("contains-routing-orchestrator", "sub-routing", "orchestrator"),
    contains("contains-retry-worker", "sub-retry", "retry"),
    contains("contains-api-service", "module-api-edge", "api"),
    contains("contains-fraud-service", "module-fraud-risk", "fraud"),
    contains("contains-settlement-service", "module-settlement-engine", "settlement"),
    contains("contains-ledger-adapter", "sub-ledger", "ledger-adapter"),
    contains("contains-ledger-gateway", "sub-ledger", "ledger-gateway"),
    contains("contains-recon-worker", "module-reconciliation", "recon"),
    relation("orchestrator-api", "orchestrator", "api", "SYNC_CALL", "HTTP/REST", 0.94),
    relation("api-fraud", "api", "fraud", "SYNC_CALL", "gRPC", 0.92),
    relation("orchestrator-retry", "orchestrator", "retry", "DEPENDS_ON", "Внутренний вызов", 0.8),
    relation("fraud-events", "fraud", "events", "ASYNC_PUBLISH", "Kafka", 0.82),
    relation("events-settlement", "events", "settlement", "ASYNC_SUBSCRIBE", "Kafka", 0.81),
    relation("settlement-ledger-adapter", "settlement", "ledger-adapter", "SYNC_CALL", "gRPC", 0.9),
    relation("ledger-adapter-gateway", "ledger-adapter", "ledger-gateway", "SYNC_CALL", "HTTP/REST", 0.9),
    relation("ledger-gateway-recon", "ledger-gateway", "recon", "SYNC_CALL", "gRPC", 0.78),
    relation("events-recon", "events", "recon", "ASYNC_SUBSCRIBE", "Kafka", 0.78)
  ],
  hierarchy: [
    hierarchy("contains-system-customer", "system-payments", "fp-customer-payments"),
    hierarchy("contains-system-settlement", "system-payments", "fp-settlement-clearing"),
    hierarchy("contains-system-events", "system-payments", "events"),
    hierarchy("contains-customer-orchestration", "fp-customer-payments", "module-orchestration"),
    hierarchy("contains-customer-api", "fp-customer-payments", "module-api-edge"),
    hierarchy("contains-customer-fraud", "fp-customer-payments", "module-fraud-risk"),
    hierarchy("contains-settlement-engine", "fp-settlement-clearing", "module-settlement-engine"),
    hierarchy("contains-settlement-ledger", "fp-settlement-clearing", "module-ledger-sync"),
    hierarchy("contains-settlement-recon", "fp-settlement-clearing", "module-reconciliation"),
    hierarchy("contains-orchestration-routing", "module-orchestration", "sub-routing"),
    hierarchy("contains-orchestration-retry", "module-orchestration", "sub-retry"),
    hierarchy("contains-ledger-sub", "module-ledger-sync", "sub-ledger"),
    hierarchy("contains-routing-orchestrator", "sub-routing", "orchestrator"),
    hierarchy("contains-retry-worker", "sub-retry", "retry"),
    hierarchy("contains-api-service", "module-api-edge", "api"),
    hierarchy("contains-fraud-service", "module-fraud-risk", "fraud"),
    hierarchy("contains-settlement-service", "module-settlement-engine", "settlement"),
    hierarchy("contains-ledger-adapter", "sub-ledger", "ledger-adapter"),
    hierarchy("contains-ledger-gateway", "sub-ledger", "ledger-gateway"),
    hierarchy("contains-recon-worker", "module-reconciliation", "recon")
  ],
  revision: null,
  layout_hints: {},
  issue_counters: { total: 0 }
};

function node(
  nodeId: string,
  nodeType: string,
  name: string,
  origin = "INFERRED"
): GraphNodeProjectionResponse {
  return {
    node_id: nodeId,
    stable_key: `reference/${nodeType}/${nodeId}`,
    node_type: nodeType,
    name,
    origin,
    validation_state: "CONFIRMED",
    confidence: 0.9
  };
}

function contains(edgeId: string, source: string, target: string): GraphEdgeProjectionResponse {
  return relation(edgeId, source, target, "CONTAINS", null, 0.92);
}

function relation(
  edgeId: string,
  source: string,
  target: string,
  edgeType: string,
  protocol: string | null,
  confidence: number
): GraphEdgeProjectionResponse {
  return {
    edge_id: edgeId,
    source_node_id: source,
    target_node_id: target,
    edge_type: edgeType,
    origin: "INFERRED",
    validation_state: confidence >= 0.85 ? "CONFIRMED" : "CONFIRMED_WITH_WARNINGS",
    confidence,
    protocol
  };
}

function hierarchy(
  edgeId: string,
  parent: string,
  child: string
): GraphHierarchyEdgeResponse {
  return {
    edge_id: edgeId,
    parent_node_id: parent,
    child_node_id: child
  };
}
