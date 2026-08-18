from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.contracts.graph import CandidateFact, Evidence, ValidationRecord
from app.domain.enums import (
    EdgeType,
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ValidationState,
)
from app.graph.assembler import (
    GraphAssembler,
    GraphAssemblyError,
    GraphAssemblyInput,
    ValidatedCandidateFact,
)
from app.infrastructure.db.repositories import (
    AuditRepository,
    GraphSnapshotRepository,
    ProjectRepository,
    RepositoryStateRepository,
)
from app.infrastructure.db.session import (
    create_session_factory,
    create_sqlite_engine,
    session_scope,
)


def test_graph_assembler_publishes_snapshot_in_repository_transaction(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    with session_scope(session_factory) as session:
        create_audit_fixture(session)
        published = GraphAssembler().assemble_and_publish(
            assembly_input=valid_graph_input(snapshot_id="snapshot-1"),
            repository=GraphSnapshotRepository(session),
        )

        assert published.snapshot.snapshot_id == "snapshot-1"
        assert len(published.nodes) == 2
        assert len(published.edges) == 1

    with session_scope(session_factory) as session:
        snapshot = GraphSnapshotRepository(session).get_snapshot("snapshot-1")
        assert snapshot is not None
        assert snapshot.summary == {"node_count": 2, "edge_count": 1, "issue_count": 0}


def test_graph_assembler_does_not_publish_invalid_ambiguous_graph(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    with pytest.raises(GraphAssemblyError), session_scope(session_factory) as session:
        create_audit_fixture(session)
        GraphAssembler().assemble_and_publish(
            assembly_input=GraphAssemblyInput(
                snapshot_id="snapshot-invalid",
                project_id="project-1",
                audit_id="audit-1",
                repository_state_id="repo-state-1",
                candidates=(
                    validated_node("one", "duplicate-key", NodeType.MODULE),
                    validated_node("two", "duplicate-key", NodeType.MODULE),
                ),
            ),
            repository=GraphSnapshotRepository(session),
        )

    with session_scope(session_factory) as session:
        assert GraphSnapshotRepository(session).get_snapshot("snapshot-invalid") is None


def create_migrated_session_factory(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'storage.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_sqlite_engine(database_url)
    return create_session_factory(engine)


def create_audit_fixture(session) -> None:
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
        audit_id="audit-1",
    )


def valid_graph_input(*, snapshot_id: str) -> GraphAssemblyInput:
    module_key = "project-1/MODULE/_root/payments__path-payments"
    service_key = "project-1/MICROSERVICE/payments/payments-api__artifact-payments-api"
    return GraphAssemblyInput(
        snapshot_id=snapshot_id,
        project_id="project-1",
        audit_id="audit-1",
        repository_state_id="repo-state-1",
        candidates=(
            validated_node("module", module_key, NodeType.MODULE),
            validated_node("service", service_key, NodeType.MICROSERVICE),
            validated_edge("contains", module_key, service_key),
        ),
    )


def validated_node(
    fact_id: str,
    stable_key: str,
    node_type: NodeType,
) -> ValidatedCandidateFact:
    return ValidatedCandidateFact(
        candidate=CandidateFact(
            fact_id=fact_id,
            fact_kind="NODE",
            candidate_schema_version="0.1.0",
            node_type=node_type,
            name=fact_id,
            evidence=(make_evidence(f"{fact_id}-evidence"),),
            metadata={"stable_key": stable_key, "node_id": f"node-{fact_id}"},
        ),
        validation_record=make_validation_record(),
    )


def validated_edge(
    fact_id: str,
    source_stable_key: str,
    target_stable_key: str,
) -> ValidatedCandidateFact:
    return ValidatedCandidateFact(
        candidate=CandidateFact(
            fact_id=fact_id,
            fact_kind="EDGE",
            candidate_schema_version="0.1.0",
            edge_type=EdgeType.CONTAINS,
            source_stable_key=source_stable_key,
            target_stable_key=target_stable_key,
            evidence=(make_evidence(f"{fact_id}-evidence"),),
            metadata={"edge_id": f"edge-{fact_id}"},
        ),
        validation_record=make_validation_record(),
    )


def make_validation_record() -> ValidationRecord:
    return ValidationRecord(
        candidate_schema_version="0.1.0",
        evidence=(make_evidence("validation-evidence"),),
        policy_version="confidence-policy-v0.1",
        confidence=0.9,
        final_state=ValidationState.CONFIRMED,
        validated_at="2026-08-18T00:00:00Z",
    )


def make_evidence(evidence_id: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        relative_path="src/main.py",
        file_hash="sha256:abc",
        line_start=1,
        line_end=1,
        fragment_hash="sha256:def",
        source_type=EvidenceSourceType.SOURCE_CODE,
        strength=EvidenceStrength.STRONG,
        analysis_unit_id="unit-1",
    )
