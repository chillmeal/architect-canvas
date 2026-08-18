from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.graph import GraphEdge, GraphNode, GraphSnapshot
from app.domain.enums import (
    EdgeType,
    GraphOverrideEntityKind,
    GraphRevisionStatus,
    GraphSnapshotStatus,
    OverrideOperation,
)
from app.infrastructure.db.models import (
    AuditRecord,
    GraphEdgeRecord,
    GraphNodeRecord,
    GraphOverrideRecord,
    GraphRevisionRecord,
    GraphSnapshotRecord,
)


class GraphSnapshotImmutableError(RuntimeError):
    pass


class GraphRevisionStateError(RuntimeError):
    pass


class ActiveParentConflictError(RuntimeError):
    pass


class DangerousNodeSuppressionError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any]) -> None:
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class PublishedGraphSnapshot:
    snapshot: GraphSnapshotRecord
    nodes: tuple[GraphNodeRecord, ...]
    edges: tuple[GraphEdgeRecord, ...]


class GraphSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def publish_snapshot(self, snapshot: GraphSnapshot) -> PublishedGraphSnapshot:
        audit = self.session.get(AuditRecord, snapshot.audit_id)
        if audit is None:
            raise LookupError(f"Audit not found: {snapshot.audit_id}")
        self._assert_snapshot_can_be_created(snapshot.snapshot_id)
        now = datetime.now(UTC)
        snapshot_record = GraphSnapshotRecord(
            snapshot_id=snapshot.snapshot_id,
            project_id=snapshot.project_id,
            audit_id=snapshot.audit_id,
            repository_state_id=snapshot.repository_state_id,
            schema_version=snapshot.schema_version,
            status=GraphSnapshotStatus.PUBLISHED.value,
            summary={
                "node_count": len(snapshot.nodes),
                "edge_count": len(snapshot.edges),
                "issue_count": len(snapshot.issues),
            },
            published_at=now,
        )
        self.session.add(snapshot_record)
        self.session.flush()
        nodes = tuple(self._add_node(snapshot.snapshot_id, node) for node in snapshot.nodes)
        self.session.flush()
        edges = tuple(self._add_edge(snapshot.snapshot_id, edge) for edge in snapshot.edges)
        self.session.flush()
        return PublishedGraphSnapshot(snapshot=snapshot_record, nodes=nodes, edges=edges)

    def get_snapshot(self, snapshot_id: str) -> GraphSnapshotRecord | None:
        return self.session.get(GraphSnapshotRecord, snapshot_id)

    def get_snapshot_for_audit(self, audit_id: str) -> GraphSnapshotRecord | None:
        return self.session.scalar(
            select(GraphSnapshotRecord)
            .where(GraphSnapshotRecord.audit_id == audit_id)
            .order_by(GraphSnapshotRecord.published_at.desc())
            .limit(1)
        )

    def list_nodes(self, snapshot_id: str) -> tuple[GraphNodeRecord, ...]:
        return tuple(
            self.session.scalars(
                select(GraphNodeRecord)
                .where(GraphNodeRecord.snapshot_id == snapshot_id)
                .order_by(GraphNodeRecord.stable_key)
            ).all()
        )

    def list_edges(self, snapshot_id: str) -> tuple[GraphEdgeRecord, ...]:
        return tuple(
            self.session.scalars(
                select(GraphEdgeRecord)
                .where(GraphEdgeRecord.snapshot_id == snapshot_id)
                .order_by(GraphEdgeRecord.edge_id)
            ).all()
        )

    def get_node(self, *, snapshot_id: str, node_id: str) -> GraphNodeRecord | None:
        return self.session.scalar(
            select(GraphNodeRecord).where(
                GraphNodeRecord.snapshot_id == snapshot_id,
                GraphNodeRecord.node_id == node_id,
            )
        )

    def get_edge(self, *, snapshot_id: str, edge_id: str) -> GraphEdgeRecord | None:
        return self.session.scalar(
            select(GraphEdgeRecord).where(
                GraphEdgeRecord.snapshot_id == snapshot_id,
                GraphEdgeRecord.edge_id == edge_id,
            )
        )

    def update_summary(self, *, snapshot_id: str, summary: dict[str, Any]) -> GraphSnapshotRecord:
        snapshot = self._get_snapshot_or_raise(snapshot_id)
        if snapshot.status == GraphSnapshotStatus.PUBLISHED.value:
            raise GraphSnapshotImmutableError(f"GraphSnapshot is already published: {snapshot_id}")
        snapshot.summary = summary
        self.session.flush()
        return snapshot

    def _add_node(self, snapshot_id: str, node: GraphNode) -> GraphNodeRecord:
        node_record = GraphNodeRecord(
            node_id=node.node_id,
            snapshot_id=snapshot_id,
            stable_key=node.stable_key,
            node_type=node.node_type.value,
            name=node.name,
            origin=node.origin.value,
            validation_state=node.validation_state.value,
            confidence=node.confidence,
            evidence=[item.model_dump(mode="json") for item in node.evidence],
            validation_record=(
                node.validation_record.model_dump(mode="json")
                if node.validation_record is not None
                else None
            ),
            metadata_json=node.metadata,
        )
        self.session.add(node_record)
        return node_record

    def _add_edge(self, snapshot_id: str, edge: GraphEdge) -> GraphEdgeRecord:
        edge_record = GraphEdgeRecord(
            edge_id=edge.edge_id,
            snapshot_id=snapshot_id,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            edge_type=edge.edge_type.value,
            origin=edge.origin.value,
            validation_state=edge.validation_state.value,
            confidence=edge.confidence,
            contract=edge.contract,
            protocol=edge.protocol,
            evidence=[item.model_dump(mode="json") for item in edge.evidence],
            validation_record=(
                edge.validation_record.model_dump(mode="json")
                if edge.validation_record is not None
                else None
            ),
            metadata_json=edge.metadata,
        )
        self.session.add(edge_record)
        return edge_record

    def _assert_snapshot_can_be_created(self, snapshot_id: str) -> None:
        existing = self.session.get(GraphSnapshotRecord, snapshot_id)
        if existing is not None:
            raise GraphSnapshotImmutableError(f"GraphSnapshot already exists: {snapshot_id}")

    def _get_snapshot_or_raise(self, snapshot_id: str) -> GraphSnapshotRecord:
        snapshot = self.session.get(GraphSnapshotRecord, snapshot_id)
        if snapshot is None:
            raise LookupError(f"GraphSnapshot not found: {snapshot_id}")
        return snapshot


class GraphRevisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_revision(
        self,
        *,
        snapshot_id: str,
        parent_revision_id: str | None = None,
        title: str | None = None,
        created_by: str | None = None,
        revision_id: str | None = None,
    ) -> GraphRevisionRecord:
        snapshot = self.session.get(GraphSnapshotRecord, snapshot_id)
        if snapshot is None:
            raise LookupError(f"GraphSnapshot not found: {snapshot_id}")
        if parent_revision_id is not None:
            parent = self._get_revision_or_raise(parent_revision_id)
            if parent.status != GraphRevisionStatus.COMMITTED.value:
                raise GraphRevisionStateError("Parent revision must be committed")
            if parent.snapshot_id != snapshot_id:
                raise GraphRevisionStateError("Parent revision belongs to another snapshot")
        revision = GraphRevisionRecord(
            revision_id=revision_id or str(uuid4()),
            snapshot_id=snapshot_id,
            parent_revision_id=parent_revision_id,
            status=GraphRevisionStatus.DRAFT.value,
            title=title,
            created_by=created_by,
        )
        self.session.add(revision)
        self.session.flush()
        return revision

    def get_revision(self, revision_id: str) -> GraphRevisionRecord | None:
        return self.session.get(GraphRevisionRecord, revision_id)

    def list_revisions(self, snapshot_id: str) -> tuple[GraphRevisionRecord, ...]:
        return tuple(
            self.session.scalars(
                select(GraphRevisionRecord)
                .where(GraphRevisionRecord.snapshot_id == snapshot_id)
                .order_by(GraphRevisionRecord.created_at, GraphRevisionRecord.revision_id)
            ).all()
        )

    def list_overrides(self, revision_id: str) -> tuple[GraphOverrideRecord, ...]:
        return tuple(
            self.session.scalars(
                select(GraphOverrideRecord)
                .where(GraphOverrideRecord.revision_id == revision_id)
                .order_by(GraphOverrideRecord.created_at, GraphOverrideRecord.override_id)
            ).all()
        )

    def suppress_node(
        self,
        *,
        revision_id: str,
        node_id: str,
        reason: str | None = None,
        created_by: str | None = None,
        confirm_children_strategy: str | None = None,
        confirm_incident_edges: bool = False,
        confirm_high_impact: bool = False,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        node = self._get_snapshot_node_or_raise(revision.snapshot_id, node_id)
        self._assert_node_suppression_confirmed(
            revision=revision,
            node=node,
            confirm_children_strategy=confirm_children_strategy,
            confirm_incident_edges=confirm_incident_edges,
            confirm_high_impact=confirm_high_impact,
        )
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.SUPPRESS_NODE,
            entity_kind=GraphOverrideEntityKind.NODE,
            target_node_id=node_id,
            payload={
                "confirm_children_strategy": confirm_children_strategy,
                "confirm_incident_edges": confirm_incident_edges,
                "confirm_high_impact": confirm_high_impact,
            },
            reason=reason,
            created_by=created_by,
            override_id=override_id,
        )

    def restore_node(
        self,
        *,
        revision_id: str,
        node_id: str,
        reason: str | None = None,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        self._get_snapshot_node_or_raise(revision.snapshot_id, node_id)
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.RESTORE_NODE,
            entity_kind=GraphOverrideEntityKind.NODE,
            target_node_id=node_id,
            payload={},
            reason=reason,
            created_by=created_by,
            override_id=override_id,
        )

    def update_node(
        self,
        *,
        revision_id: str,
        node_id: str,
        updates: dict[str, Any],
        reason: str | None = None,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        self._assert_node_exists_in_revision(revision, node_id)
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.UPDATE_NODE,
            entity_kind=GraphOverrideEntityKind.NODE,
            target_node_id=node_id,
            payload={"updates": updates},
            reason=reason,
            created_by=created_by,
            override_id=override_id,
        )

    def move_node(
        self,
        *,
        revision_id: str,
        node_id: str,
        new_parent_node_id: str,
        reason: str | None = None,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        self._assert_node_exists_in_revision(revision, node_id)
        self._assert_node_exists_in_revision(revision, new_parent_node_id)
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.MOVE_NODE,
            entity_kind=GraphOverrideEntityKind.NODE,
            target_node_id=node_id,
            payload={"new_parent_node_id": new_parent_node_id},
            reason=reason,
            created_by=created_by,
            override_id=override_id,
        )

    def add_manual_node(
        self,
        *,
        revision_id: str,
        node: GraphNode,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.ADD_NODE,
            entity_kind=GraphOverrideEntityKind.NODE,
            target_node_id=node.node_id,
            payload=node.model_dump(mode="json"),
            created_by=created_by,
            override_id=override_id,
        )

    def delete_unsaved_manual_node(self, *, revision_id: str, node_id: str) -> None:
        revision = self._get_draft_revision_or_raise(revision_id)
        override = self.session.scalar(
            select(GraphOverrideRecord).where(
                GraphOverrideRecord.revision_id == revision.revision_id,
                GraphOverrideRecord.operation == OverrideOperation.ADD_NODE.value,
                GraphOverrideRecord.entity_kind == GraphOverrideEntityKind.NODE.value,
                GraphOverrideRecord.target_node_id == node_id,
            )
        )
        if override is None:
            raise LookupError(f"Unsaved manual node override not found: {node_id}")
        self.session.delete(override)
        self.session.flush()

    def add_contains_parent(
        self,
        *,
        revision_id: str,
        parent_node_id: str,
        child_node_id: str,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        self._assert_node_exists_in_revision(revision, parent_node_id)
        self._assert_node_exists_in_revision(revision, child_node_id)
        active_parent_ids = self._active_parent_ids(revision, child_node_id)
        if active_parent_ids:
            parents = ", ".join(sorted(active_parent_ids))
            raise ActiveParentConflictError(
                f"Node {child_node_id} already has active CONTAINS parent(s): {parents}"
            )
        payload = {
            "edge_id": override_id or str(uuid4()),
            "source_node_id": parent_node_id,
            "target_node_id": child_node_id,
            "edge_type": EdgeType.CONTAINS.value,
        }
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.ADD_EDGE,
            entity_kind=GraphOverrideEntityKind.EDGE,
            target_edge_id=payload["edge_id"],
            payload=payload,
            created_by=created_by,
            override_id=override_id,
        )

    def add_edge(
        self,
        *,
        revision_id: str,
        edge: GraphEdge,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        self._assert_node_exists_in_revision(revision, edge.source_node_id)
        self._assert_node_exists_in_revision(revision, edge.target_node_id)
        if edge.edge_type == EdgeType.CONTAINS:
            active_parent_ids = self._active_parent_ids(revision, edge.target_node_id)
            if active_parent_ids:
                parents = ", ".join(sorted(active_parent_ids))
                raise ActiveParentConflictError(
                    f"Node {edge.target_node_id} already has active CONTAINS parent(s): {parents}"
                )
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.ADD_EDGE,
            entity_kind=GraphOverrideEntityKind.EDGE,
            target_edge_id=edge.edge_id,
            payload=edge.model_dump(mode="json"),
            created_by=created_by,
            override_id=override_id,
        )

    def suppress_edge(
        self,
        *,
        revision_id: str,
        edge_id: str,
        reason: str | None = None,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        self._get_snapshot_edge_or_raise(revision.snapshot_id, edge_id)
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.SUPPRESS_EDGE,
            entity_kind=GraphOverrideEntityKind.EDGE,
            target_edge_id=edge_id,
            payload={},
            reason=reason,
            created_by=created_by,
            override_id=override_id,
        )

    def restore_edge(
        self,
        *,
        revision_id: str,
        edge_id: str,
        reason: str | None = None,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        self._get_snapshot_edge_or_raise(revision.snapshot_id, edge_id)
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.RESTORE_EDGE,
            entity_kind=GraphOverrideEntityKind.EDGE,
            target_edge_id=edge_id,
            payload={},
            reason=reason,
            created_by=created_by,
            override_id=override_id,
        )

    def update_edge(
        self,
        *,
        revision_id: str,
        edge_id: str,
        updates: dict[str, Any],
        reason: str | None = None,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        self._get_snapshot_edge_or_raise(revision.snapshot_id, edge_id)
        return self._add_override(
            revision=revision,
            operation=OverrideOperation.UPDATE_EDGE,
            entity_kind=GraphOverrideEntityKind.EDGE,
            target_edge_id=edge_id,
            payload={"updates": updates},
            reason=reason,
            created_by=created_by,
            override_id=override_id,
        )

    def commit_revision(self, revision_id: str) -> GraphRevisionRecord:
        revision = self._get_draft_revision_or_raise(revision_id)
        revision.status = GraphRevisionStatus.COMMITTED.value
        revision.committed_at = datetime.now(UTC)
        self.session.flush()
        return revision

    def _add_override(
        self,
        *,
        revision: GraphRevisionRecord,
        operation: OverrideOperation,
        entity_kind: GraphOverrideEntityKind,
        payload: dict[str, Any],
        target_node_id: str | None = None,
        target_edge_id: str | None = None,
        reason: str | None = None,
        created_by: str | None = None,
        override_id: str | None = None,
    ) -> GraphOverrideRecord:
        override = GraphOverrideRecord(
            override_id=override_id or str(uuid4()),
            revision_id=revision.revision_id,
            operation=operation.value,
            entity_kind=entity_kind.value,
            target_node_id=target_node_id,
            target_edge_id=target_edge_id,
            payload=payload,
            reason=reason,
            created_by=created_by,
        )
        self.session.add(override)
        self.session.flush()
        return override

    def _active_parent_ids(self, revision: GraphRevisionRecord, child_node_id: str) -> set[str]:
        suppressed_edge_ids = {
            override.target_edge_id
            for override in self._revision_overrides(revision)
            if override.operation == OverrideOperation.SUPPRESS_EDGE.value
            and override.target_edge_id is not None
        }
        parent_ids = set(
            self.session.scalars(
                select(GraphEdgeRecord.source_node_id).where(
                    GraphEdgeRecord.snapshot_id == revision.snapshot_id,
                    GraphEdgeRecord.edge_type == EdgeType.CONTAINS.value,
                    GraphEdgeRecord.target_node_id == child_node_id,
                    GraphEdgeRecord.edge_id.not_in(suppressed_edge_ids),
                )
            ).all()
        )
        for override in self._revision_overrides(revision):
            if override.operation != OverrideOperation.ADD_EDGE.value:
                continue
            if override.payload.get("edge_type") != EdgeType.CONTAINS.value:
                continue
            if override.payload.get("target_node_id") == child_node_id:
                parent_ids.add(str(override.payload["source_node_id"]))
        return parent_ids

    def _assert_node_suppression_confirmed(
        self,
        *,
        revision: GraphRevisionRecord,
        node: GraphNodeRecord,
        confirm_children_strategy: str | None,
        confirm_incident_edges: bool,
        confirm_high_impact: bool,
    ) -> None:
        child_count = self.session.scalar(
            select(func.count(GraphEdgeRecord.edge_id)).where(
                GraphEdgeRecord.snapshot_id == revision.snapshot_id,
                GraphEdgeRecord.edge_type == EdgeType.CONTAINS.value,
                GraphEdgeRecord.source_node_id == node.node_id,
            )
        )
        incident_edge_count = self.session.scalar(
            select(func.count(GraphEdgeRecord.edge_id)).where(
                GraphEdgeRecord.snapshot_id == revision.snapshot_id,
                (GraphEdgeRecord.source_node_id == node.node_id)
                | (GraphEdgeRecord.target_node_id == node.node_id),
            )
        )
        child_count = int(child_count or 0)
        incident_edge_count = int(incident_edge_count or 0)
        high_impact = node.node_type in {
            "AUTOMATED_SYSTEM",
            "FUNCTIONAL_SUBSYSTEM",
        }
        missing: list[str] = []
        if child_count and not confirm_children_strategy:
            missing.append("confirm_children_strategy")
        if incident_edge_count and not confirm_incident_edges:
            missing.append("confirm_incident_edges")
        if high_impact and not confirm_high_impact:
            missing.append("confirm_high_impact")
        if missing:
            raise DangerousNodeSuppressionError(
                "Node suppression requires explicit confirmation",
                {
                    "missing_confirmations": missing,
                    "child_count": child_count,
                    "incident_edge_count": incident_edge_count,
                    "high_impact": high_impact,
                },
            )

    def _revision_overrides(self, revision: GraphRevisionRecord) -> tuple[GraphOverrideRecord, ...]:
        return tuple(
            self.session.scalars(
                select(GraphOverrideRecord).where(
                    GraphOverrideRecord.revision_id == revision.revision_id
                )
            ).all()
        )

    def _assert_node_exists_in_revision(
        self,
        revision: GraphRevisionRecord,
        node_id: str,
    ) -> None:
        if self._get_snapshot_node(revision.snapshot_id, node_id) is not None:
            return
        manual_override = self.session.scalar(
            select(GraphOverrideRecord).where(
                GraphOverrideRecord.revision_id == revision.revision_id,
                GraphOverrideRecord.operation == OverrideOperation.ADD_NODE.value,
                GraphOverrideRecord.target_node_id == node_id,
            )
        )
        if manual_override is None:
            raise LookupError(f"Graph node not found in revision: {node_id}")

    def _get_snapshot_node_or_raise(self, snapshot_id: str, node_id: str) -> GraphNodeRecord:
        node = self._get_snapshot_node(snapshot_id, node_id)
        if node is None:
            raise LookupError(f"Graph node not found: {node_id}")
        return node

    def _get_snapshot_node(self, snapshot_id: str, node_id: str) -> GraphNodeRecord | None:
        return self.session.scalar(
            select(GraphNodeRecord).where(
                GraphNodeRecord.snapshot_id == snapshot_id,
                GraphNodeRecord.node_id == node_id,
            )
        )

    def _get_snapshot_edge_or_raise(self, snapshot_id: str, edge_id: str) -> GraphEdgeRecord:
        edge = self.session.scalar(
            select(GraphEdgeRecord).where(
                GraphEdgeRecord.snapshot_id == snapshot_id,
                GraphEdgeRecord.edge_id == edge_id,
            )
        )
        if edge is None:
            raise LookupError(f"Graph edge not found: {edge_id}")
        return edge

    def _get_draft_revision_or_raise(self, revision_id: str) -> GraphRevisionRecord:
        revision = self._get_revision_or_raise(revision_id)
        if revision.status != GraphRevisionStatus.DRAFT.value:
            raise GraphRevisionStateError(f"GraphRevision is not draft: {revision_id}")
        return revision

    def _get_revision_or_raise(self, revision_id: str) -> GraphRevisionRecord:
        revision = self.session.get(GraphRevisionRecord, revision_id)
        if revision is None:
            raise LookupError(f"GraphRevision not found: {revision_id}")
        return revision
