from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.contracts.graph import Evidence, GraphEdge, GraphNode, GraphSnapshot
from app.domain.enums import (
    EdgeType,
    EntityOrigin,
    EvidenceSourceType,
    EvidenceStrength,
    GraphRevisionStatus,
    NodeType,
    OverrideOperation,
    ValidationState,
)
from app.infrastructure.db.models import GraphNodeRecord, GraphOverrideRecord
from app.infrastructure.db.repositories import (
    ActiveParentConflictError,
    AuditRepository,
    GraphRevisionRepository,
    GraphRevisionStateError,
    GraphSnapshotImmutableError,
    GraphSnapshotRepository,
    ProjectRepository,
    RepositoryStateRepository,
)
from app.infrastructure.db.session import (
    create_session_factory,
    create_sqlite_engine,
    session_scope,
)


def test_published_graph_snapshot_is_immutable(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    snapshot = make_snapshot()

    with session_scope(session_factory) as session:
        create_audit_fixture(session, snapshot.audit_id)
        GraphSnapshotRepository(session).publish_snapshot(snapshot)

    with pytest.raises(GraphSnapshotImmutableError), session_scope(session_factory) as session:
        GraphSnapshotRepository(session).update_summary(
            snapshot_id=snapshot.snapshot_id,
            summary={"node_count": 99},
        )

    with session_scope(session_factory) as session:
        persisted = GraphSnapshotRepository(session).get_snapshot(snapshot.snapshot_id)
        assert persisted is not None
        assert persisted.summary == {"node_count": 3, "edge_count": 1, "issue_count": 0}


def test_suppression_override_does_not_delete_historical_node(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    snapshot = make_snapshot()

    with session_scope(session_factory) as session:
        create_audit_fixture(session, snapshot.audit_id)
        GraphSnapshotRepository(session).publish_snapshot(snapshot)
        revisions = GraphRevisionRepository(session)
        revision = revisions.create_revision(snapshot_id=snapshot.snapshot_id)
        revisions.suppress_node(
            revision_id=revision.revision_id,
            node_id="child",
            confirm_incident_edges=True,
        )
        revisions.commit_revision(revision.revision_id)

    with session_scope(session_factory) as session:
        node = session.get(GraphNodeRecord, "child")
        overrides = session.scalars(select(GraphOverrideRecord)).all()

        assert node is not None
        assert len(overrides) == 1
        assert overrides[0].operation == OverrideOperation.SUPPRESS_NODE.value
        assert overrides[0].target_node_id == "child"


def test_manual_unsaved_node_can_only_be_physically_deleted_before_commit(
    tmp_path: Path,
) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    snapshot = make_snapshot()

    with session_scope(session_factory) as session:
        create_audit_fixture(session, snapshot.audit_id)
        GraphSnapshotRepository(session).publish_snapshot(snapshot)
        revisions = GraphRevisionRepository(session)
        revision = revisions.create_revision(snapshot_id=snapshot.snapshot_id)
        revisions.add_manual_node(
            revision_id=revision.revision_id,
            node=make_node(
                node_id="manual-draft",
                stable_key="project/MODULE/manual-draft",
                name="manual draft",
                origin=EntityOrigin.MANUAL,
            ),
        )
        revisions.delete_unsaved_manual_node(
            revision_id=revision.revision_id,
            node_id="manual-draft",
        )
        overrides = session.scalars(select(GraphOverrideRecord)).all()
        assert overrides == []

        revisions.add_manual_node(
            revision_id=revision.revision_id,
            node=make_node(
                node_id="manual-saved",
                stable_key="project/MODULE/manual-saved",
                name="manual saved",
                origin=EntityOrigin.MANUAL,
            ),
        )
        revisions.commit_revision(revision.revision_id)

    with pytest.raises(GraphRevisionStateError), session_scope(session_factory) as session:
        GraphRevisionRepository(session).delete_unsaved_manual_node(
            revision_id=revision.revision_id,
            node_id="manual-saved",
        )

    with session_scope(session_factory) as session:
        override = session.scalar(select(GraphOverrideRecord))
        assert override is not None
        assert override.operation == OverrideOperation.ADD_NODE.value
        assert override.target_node_id == "manual-saved"


def test_revision_allows_only_one_active_contains_parent(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    snapshot = make_snapshot()

    with session_scope(session_factory) as session:
        create_audit_fixture(session, snapshot.audit_id)
        GraphSnapshotRepository(session).publish_snapshot(snapshot)
        revisions = GraphRevisionRepository(session)
        revision = revisions.create_revision(snapshot_id=snapshot.snapshot_id)

        with pytest.raises(ActiveParentConflictError):
            revisions.add_contains_parent(
                revision_id=revision.revision_id,
                parent_node_id="parent-2",
                child_node_id="child",
            )

        revisions.suppress_edge(revision_id=revision.revision_id, edge_id="contains-1")
        added = revisions.add_contains_parent(
            revision_id=revision.revision_id,
            parent_node_id="parent-2",
            child_node_id="child",
        )
        revisions.commit_revision(revision.revision_id)

        assert added.operation == OverrideOperation.ADD_EDGE.value
        assert added.payload["edge_type"] == EdgeType.CONTAINS.value
        assert revision.status == GraphRevisionStatus.COMMITTED.value


def create_migrated_session_factory(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'storage.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_sqlite_engine(database_url)
    return create_session_factory(engine)


def create_audit_fixture(session, audit_id: str) -> None:
    project = ProjectRepository(session).create_project(
        name="Payments",
        repository_root="/allowed/repos/payments",
        project_id="project-1",
    )
    repository_state = RepositoryStateRepository(session).create_repository_state(
        project_id=project.project_id,
        tree_hash="tree-hash",
        repository_state_id="repo-state-1",
    )
    AuditRepository(session).create_audit(
        project_id=project.project_id,
        repository_state_id=repository_state.repository_state_id,
        audit_id=audit_id,
    )


def make_snapshot() -> GraphSnapshot:
    return GraphSnapshot(
        snapshot_id="snapshot-1",
        project_id="project-1",
        audit_id="audit-1",
        repository_state_id="repo-state-1",
        nodes=(
            make_node(node_id="parent-1", stable_key="project/MODULE/parent-1", name="parent 1"),
            make_node(node_id="parent-2", stable_key="project/MODULE/parent-2", name="parent 2"),
            make_node(node_id="child", stable_key="project/MODULE/child", name="child"),
        ),
        edges=(
            GraphEdge(
                edge_id="contains-1",
                source_node_id="parent-1",
                target_node_id="child",
                edge_type=EdgeType.CONTAINS,
                origin=EntityOrigin.INFERRED,
                validation_state=ValidationState.CONFIRMED,
                confidence=0.9,
                evidence=(make_evidence("edge-evidence-1"),),
            ),
        ),
    )


def make_node(
    *,
    node_id: str,
    stable_key: str,
    name: str,
    origin: EntityOrigin = EntityOrigin.INFERRED,
) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        stable_key=stable_key,
        node_type=NodeType.MODULE,
        name=name,
        origin=origin,
        validation_state=ValidationState.CONFIRMED,
        confidence=1.0 if origin == EntityOrigin.MANUAL else 0.9,
        evidence=() if origin == EntityOrigin.MANUAL else (make_evidence(f"{node_id}-evidence"),),
    )


def make_evidence(evidence_id: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        relative_path="src/main.py",
        file_hash="sha256:abc",
        line_start=1,
        line_end=3,
        fragment_hash="sha256:def",
        source_type=EvidenceSourceType.SOURCE_CODE,
        strength=EvidenceStrength.STRONG,
        analysis_unit_id="unit-1",
    )
