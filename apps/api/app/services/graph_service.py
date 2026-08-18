from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from sqlalchemy.orm import Session

from app.contracts.graph import GraphEdge, GraphNode
from app.core.errors import AppError
from app.domain.enums import EdgeType, OverrideOperation
from app.infrastructure.db.models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    GraphOverrideRecord,
    GraphRevisionRecord,
    GraphSnapshotRecord,
)
from app.infrastructure.db.repositories import (
    ActiveParentConflictError,
    DangerousNodeSuppressionError,
    GraphRevisionRepository,
    GraphRevisionStateError,
    GraphSnapshotRepository,
)


@dataclass(frozen=True)
class GraphProjection:
    snapshot: GraphSnapshotRecord
    nodes: tuple[Any, ...]
    edges: tuple[Any, ...]
    revision: GraphRevisionRecord | None = None


@dataclass(frozen=True)
class ProjectedGraphNode:
    node_id: str
    stable_key: str
    node_type: str
    name: str
    origin: str
    validation_state: str
    confidence: float
    evidence: list[dict[str, Any]]
    validation_record: dict[str, Any] | None
    metadata_json: dict[str, Any]


@dataclass(frozen=True)
class ProjectedGraphEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    origin: str
    validation_state: str
    confidence: float
    contract: str | None
    protocol: str | None
    evidence: list[dict[str, Any]]
    validation_record: dict[str, Any] | None
    metadata_json: dict[str, Any]


class GraphService:
    def __init__(self, *, session: Session) -> None:
        self._snapshots = GraphSnapshotRepository(session)
        self._revisions = GraphRevisionRepository(session)

    def get_graph_for_audit(self, audit_id: str, revision_id: str | None = None) -> GraphProjection:
        snapshot = self._snapshots.get_snapshot_for_audit(audit_id)
        if snapshot is None:
            raise AppError("GRAPH_NOT_FOUND", "Graph snapshot not found", status_code=HTTPStatus.NOT_FOUND)
        return self._projection(snapshot, revision_id=revision_id)

    def get_graph(self, graph_id: str, revision_id: str | None = None) -> GraphProjection:
        snapshot = self._get_snapshot(graph_id)
        return self._projection(snapshot, revision_id=revision_id)

    def list_revisions(self, graph_id: str) -> tuple[GraphRevisionRecord, ...]:
        self._get_snapshot(graph_id)
        return self._revisions.list_revisions(snapshot_id=graph_id)

    def get_node(self, *, graph_id: str, node_id: str) -> GraphNodeRecord:
        self._get_snapshot(graph_id)
        node = self._snapshots.get_node(snapshot_id=graph_id, node_id=node_id)
        if node is None:
            raise AppError("GRAPH_NODE_NOT_FOUND", "Graph node not found", status_code=HTTPStatus.NOT_FOUND)
        return node

    def get_edge(self, *, graph_id: str, edge_id: str) -> GraphEdgeRecord:
        self._get_snapshot(graph_id)
        edge = self._snapshots.get_edge(snapshot_id=graph_id, edge_id=edge_id)
        if edge is None:
            raise AppError("GRAPH_EDGE_NOT_FOUND", "Graph edge not found", status_code=HTTPStatus.NOT_FOUND)
        return edge

    def create_revision(
        self,
        *,
        graph_id: str,
        parent_revision_id: str | None = None,
        title: str | None = None,
        created_by: str | None = None,
    ) -> GraphRevisionRecord:
        try:
            return self._revisions.create_revision(
                snapshot_id=graph_id,
                parent_revision_id=parent_revision_id,
                title=title,
                created_by=created_by,
            )
        except LookupError as exc:
            raise AppError("GRAPH_NOT_FOUND", "Graph snapshot not found", status_code=HTTPStatus.NOT_FOUND) from exc
        except GraphRevisionStateError as exc:
            raise AppError(
                "GRAPH_REVISION_INVALID",
                str(exc),
                status_code=HTTPStatus.CONFLICT,
            ) from exc

    def add_override(
        self,
        *,
        revision_id: str,
        operation: OverrideOperation,
        payload: dict[str, Any],
        reason: str | None = None,
        created_by: str | None = None,
    ) -> GraphOverrideRecord:
        try:
            if operation == OverrideOperation.SUPPRESS_NODE:
                return self._revisions.suppress_node(
                    revision_id=revision_id,
                    node_id=_required_string(payload, "node_id"),
                    reason=reason,
                    created_by=created_by,
                    confirm_children_strategy=_optional_string(
                        payload,
                        "confirm_children_strategy",
                    ),
                    confirm_incident_edges=bool(payload.get("confirm_incident_edges")),
                    confirm_high_impact=bool(payload.get("confirm_high_impact")),
                )
            if operation == OverrideOperation.RESTORE_NODE:
                return self._revisions.restore_node(
                    revision_id=revision_id,
                    node_id=_required_string(payload, "node_id"),
                    reason=reason,
                    created_by=created_by,
                )
            if operation == OverrideOperation.UPDATE_NODE:
                return self._revisions.update_node(
                    revision_id=revision_id,
                    node_id=_required_string(payload, "node_id"),
                    updates=_required_dict(payload, "updates"),
                    reason=reason,
                    created_by=created_by,
                )
            if operation == OverrideOperation.MOVE_NODE:
                return self._revisions.move_node(
                    revision_id=revision_id,
                    node_id=_required_string(payload, "node_id"),
                    new_parent_node_id=_required_string(payload, "new_parent_node_id"),
                    reason=reason,
                    created_by=created_by,
                )
            if operation == OverrideOperation.SUPPRESS_EDGE:
                return self._revisions.suppress_edge(
                    revision_id=revision_id,
                    edge_id=_required_string(payload, "edge_id"),
                    reason=reason,
                    created_by=created_by,
                )
            if operation == OverrideOperation.RESTORE_EDGE:
                return self._revisions.restore_edge(
                    revision_id=revision_id,
                    edge_id=_required_string(payload, "edge_id"),
                    reason=reason,
                    created_by=created_by,
                )
            if operation == OverrideOperation.UPDATE_EDGE:
                return self._revisions.update_edge(
                    revision_id=revision_id,
                    edge_id=_required_string(payload, "edge_id"),
                    updates=_required_dict(payload, "updates"),
                    reason=reason,
                    created_by=created_by,
                )
            if operation == OverrideOperation.ADD_NODE:
                return self._revisions.add_manual_node(
                    revision_id=revision_id,
                    node=GraphNode.model_validate(payload["node"]),
                    created_by=created_by,
                )
            if operation == OverrideOperation.ADD_EDGE:
                if "edge" in payload:
                    return self._revisions.add_edge(
                        revision_id=revision_id,
                        edge=GraphEdge.model_validate(payload["edge"]),
                        created_by=created_by,
                    )
                if payload.get("edge_type") == EdgeType.CONTAINS.value:
                    return self._revisions.add_contains_parent(
                        revision_id=revision_id,
                        parent_node_id=_required_string(payload, "source_node_id"),
                        child_node_id=_required_string(payload, "target_node_id"),
                        created_by=created_by,
                    )
                raise AppError(
                    "GRAPH_OVERRIDE_INVALID",
                    "ADD_EDGE payload must contain edge or CONTAINS edge fields",
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
        except DangerousNodeSuppressionError as exc:
            raise AppError(
                "GRAPH_DANGEROUS_SUPPRESSION_REQUIRES_CONFIRMATION",
                str(exc),
                status_code=HTTPStatus.CONFLICT,
                details=exc.details,
            ) from exc
        except KeyError as exc:
            raise AppError(
                "GRAPH_OVERRIDE_INVALID",
                f"Missing override payload field: {exc.args[0]}",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            ) from exc
        except ValueError as exc:
            raise AppError(
                "GRAPH_OVERRIDE_INVALID",
                str(exc),
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            ) from exc
        except LookupError as exc:
            raise AppError("GRAPH_ENTITY_NOT_FOUND", str(exc), status_code=HTTPStatus.NOT_FOUND) from exc
        except ActiveParentConflictError as exc:
            raise AppError(
                "GRAPH_ACTIVE_PARENT_CONFLICT",
                str(exc),
                status_code=HTTPStatus.CONFLICT,
            ) from exc
        except GraphRevisionStateError as exc:
            raise AppError(
                "GRAPH_REVISION_INVALID",
                str(exc),
                status_code=HTTPStatus.CONFLICT,
            ) from exc
        raise AppError(
            "GRAPH_OVERRIDE_UNSUPPORTED",
            "Override operation is not supported before B8-01",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    def commit_revision(self, revision_id: str) -> GraphRevisionRecord:
        try:
            return self._revisions.commit_revision(revision_id)
        except LookupError as exc:
            raise AppError(
                "GRAPH_REVISION_NOT_FOUND",
                "Graph revision not found",
                status_code=HTTPStatus.NOT_FOUND,
            ) from exc
        except GraphRevisionStateError as exc:
            raise AppError(
                "GRAPH_REVISION_INVALID",
                str(exc),
                status_code=HTTPStatus.CONFLICT,
            ) from exc

    def delete_unsaved_manual_node(self, *, revision_id: str, node_id: str) -> None:
        try:
            self._revisions.delete_unsaved_manual_node(revision_id=revision_id, node_id=node_id)
        except LookupError as exc:
            raise AppError(
                "GRAPH_MANUAL_NODE_NOT_FOUND",
                "Unsaved manual node override not found",
                status_code=HTTPStatus.NOT_FOUND,
            ) from exc
        except GraphRevisionStateError as exc:
            raise AppError(
                "GRAPH_REVISION_INVALID",
                str(exc),
                status_code=HTTPStatus.CONFLICT,
            ) from exc

    def _get_snapshot(self, graph_id: str) -> GraphSnapshotRecord:
        snapshot = self._snapshots.get_snapshot(graph_id)
        if snapshot is None:
            raise AppError("GRAPH_NOT_FOUND", "Graph snapshot not found", status_code=HTTPStatus.NOT_FOUND)
        return snapshot

    def _projection(
        self,
        snapshot: GraphSnapshotRecord,
        *,
        revision_id: str | None = None,
    ) -> GraphProjection:
        nodes: dict[str, Any] = {
            node.node_id: _project_node(node) for node in self._snapshots.list_nodes(snapshot.snapshot_id)
        }
        edges: dict[str, Any] = {
            edge.edge_id: _project_edge(edge) for edge in self._snapshots.list_edges(snapshot.snapshot_id)
        }
        revision: GraphRevisionRecord | None = None
        if revision_id is not None:
            revision = self._revisions.get_revision(revision_id)
            if revision is None:
                raise AppError(
                    "GRAPH_REVISION_NOT_FOUND",
                    "Graph revision not found",
                    status_code=HTTPStatus.NOT_FOUND,
                )
            if revision.snapshot_id != snapshot.snapshot_id:
                raise AppError(
                    "GRAPH_REVISION_INVALID",
                    "Graph revision belongs to another snapshot",
                    status_code=HTTPStatus.CONFLICT,
                )
            for override in self._revision_chain_overrides(revision):
                _apply_override(nodes=nodes, edges=edges, override=override)
        return GraphProjection(
            snapshot=snapshot,
            nodes=tuple(nodes.values()),
            edges=tuple(edges.values()),
            revision=revision,
        )

    def _revision_chain_overrides(
        self,
        revision: GraphRevisionRecord,
    ) -> tuple[GraphOverrideRecord, ...]:
        chain: list[GraphRevisionRecord] = []
        current: GraphRevisionRecord | None = revision
        while current is not None:
            chain.append(current)
            current = (
                self._revisions.get_revision(current.parent_revision_id)
                if current.parent_revision_id is not None
                else None
            )
        overrides: list[GraphOverrideRecord] = []
        for chained_revision in reversed(chain):
            overrides.extend(self._revisions.list_overrides(chained_revision.revision_id))
        return tuple(overrides)


def _project_node(node: GraphNodeRecord | GraphNode) -> ProjectedGraphNode:
    return ProjectedGraphNode(
        node_id=node.node_id,
        stable_key=node.stable_key,
        node_type=node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type),
        name=node.name,
        origin=node.origin.value if hasattr(node.origin, "value") else str(node.origin),
        validation_state=(
            node.validation_state.value
            if hasattr(node.validation_state, "value")
            else str(node.validation_state)
        ),
        confidence=float(node.confidence),
        evidence=list(node.evidence),
        validation_record=node.validation_record,
        metadata_json=node.metadata if isinstance(node, GraphNode) else node.metadata_json,
    )


def _project_edge(edge: GraphEdgeRecord | GraphEdge) -> ProjectedGraphEdge:
    return ProjectedGraphEdge(
        edge_id=edge.edge_id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        edge_type=edge.edge_type.value if hasattr(edge.edge_type, "value") else str(edge.edge_type),
        origin=edge.origin.value if hasattr(edge.origin, "value") else str(edge.origin),
        validation_state=(
            edge.validation_state.value
            if hasattr(edge.validation_state, "value")
            else str(edge.validation_state)
        ),
        confidence=float(edge.confidence),
        contract=edge.contract,
        protocol=edge.protocol,
        evidence=list(edge.evidence),
        validation_record=edge.validation_record,
        metadata_json=edge.metadata if isinstance(edge, GraphEdge) else edge.metadata_json,
    )


def _apply_override(
    *,
    nodes: dict[str, Any],
    edges: dict[str, Any],
    override: GraphOverrideRecord,
) -> None:
    operation = override.operation
    payload = override.payload
    if operation == OverrideOperation.ADD_NODE.value:
        node = GraphNode.model_validate(payload["node"])
        nodes[node.node_id] = _project_node(node)
        return
    if operation == OverrideOperation.UPDATE_NODE.value and override.target_node_id in nodes:
        nodes[override.target_node_id] = _replace_node(
            nodes[override.target_node_id],
            payload.get("updates", {}),
        )
        return
    if operation == OverrideOperation.SUPPRESS_NODE.value and override.target_node_id is not None:
        nodes.pop(override.target_node_id, None)
        for edge_id, edge in tuple(edges.items()):
            if edge.source_node_id == override.target_node_id or edge.target_node_id == override.target_node_id:
                edges.pop(edge_id, None)
        return
    if operation == OverrideOperation.ADD_EDGE.value:
        if "edge" in payload:
            edge = GraphEdge.model_validate(payload["edge"])
            edges[edge.edge_id] = _project_edge(edge)
            return
        if payload.get("edge_type") == EdgeType.CONTAINS.value:
            edge_id = str(payload.get("edge_id") or override.override_id)
            edges[edge_id] = ProjectedGraphEdge(
                edge_id=edge_id,
                source_node_id=str(payload["source_node_id"]),
                target_node_id=str(payload["target_node_id"]),
                edge_type=EdgeType.CONTAINS.value,
                origin="MANUAL",
                validation_state="CONFIRMED",
                confidence=1.0,
                contract=None,
                protocol=None,
                evidence=[],
                validation_record=None,
                metadata_json={},
            )
        return
    if operation == OverrideOperation.UPDATE_EDGE.value and override.target_edge_id in edges:
        edges[override.target_edge_id] = _replace_edge(
            edges[override.target_edge_id],
            payload.get("updates", {}),
        )
        return
    if operation == OverrideOperation.SUPPRESS_EDGE.value and override.target_edge_id is not None:
        edges.pop(override.target_edge_id, None)
        return
    if operation == OverrideOperation.MOVE_NODE.value and override.target_node_id is not None:
        for edge_id, edge in tuple(edges.items()):
            if edge.edge_type == EdgeType.CONTAINS.value and edge.target_node_id == override.target_node_id:
                edges.pop(edge_id, None)
        edge_id = override.override_id
        edges[edge_id] = ProjectedGraphEdge(
            edge_id=edge_id,
            source_node_id=str(payload["new_parent_node_id"]),
            target_node_id=override.target_node_id,
            edge_type=EdgeType.CONTAINS.value,
            origin="MANUAL",
            validation_state="CONFIRMED",
            confidence=1.0,
            contract=None,
            protocol=None,
            evidence=[],
            validation_record=None,
            metadata_json={},
        )


def _replace_node(node: Any, updates: dict[str, Any]) -> ProjectedGraphNode:
    data = node.__dict__.copy()
    for key in ("stable_key", "node_type", "name", "origin", "validation_state", "confidence"):
        if key in updates:
            data[key] = updates[key]
    if "metadata" in updates:
        data["metadata_json"] = updates["metadata"]
    return ProjectedGraphNode(**data)


def _replace_edge(edge: Any, updates: dict[str, Any]) -> ProjectedGraphEdge:
    data = edge.__dict__.copy()
    for key in (
        "source_node_id",
        "target_node_id",
        "edge_type",
        "origin",
        "validation_state",
        "confidence",
        "contract",
        "protocol",
    ):
        if key in updates:
            data[key] = updates[key]
    if "metadata" in updates:
        data["metadata_json"] = updates["metadata"]
    return ProjectedGraphEdge(**data)


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload[key]
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{key} must be a non-empty object")
    return value
