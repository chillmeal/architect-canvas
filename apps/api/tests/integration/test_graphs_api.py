from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.contracts.graph import Evidence, GraphEdge, GraphNode, GraphSnapshot
from app.core.config import AppConfig
from app.domain.enums import (
    EdgeType,
    EntityOrigin,
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ValidationState,
)
from app.infrastructure.db.repositories import (
    AuditRepository,
    GraphSnapshotRepository,
    ProjectRepository,
    RepositoryStateRepository,
)
from app.infrastructure.db.session import session_scope
from app.infrastructure.llm import FakeLlmProvider
from app.main import create_app


def test_graphs_api_returns_projection_and_entity_details(tmp_path: Path) -> None:
    client = create_client_with_published_snapshot(tmp_path)

    graph_response = client.get("/api/v1/audits/audit-1/graph")
    node_response = client.get("/api/v1/graphs/snapshot-1/nodes/child")
    edge_response = client.get("/api/v1/graphs/snapshot-1/edges/contains-1")

    assert graph_response.status_code == 200
    graph = graph_response.json()
    assert graph["graph_id"] == "snapshot-1"
    assert [node["node_id"] for node in graph["nodes"]] == ["parent-1", "child", "parent-2"]
    assert graph["hierarchy"] == [
        {"edge_id": "contains-1", "parent_node_id": "parent-1", "child_node_id": "child"}
    ]
    assert graph["issue_counters"] == {"total": 0}

    assert node_response.status_code == 200
    assert node_response.json()["evidence"][0]["relative_path"] == "src/main.py"
    assert edge_response.status_code == 200
    assert edge_response.json()["source_node_id"] == "parent-1"
    assert edge_response.json()["evidence"][0]["analysis_unit_id"] == "unit-1"


def test_revision_override_and_commit_do_not_mutate_historical_snapshot(tmp_path: Path) -> None:
    client = create_client_with_published_snapshot(tmp_path)

    revision_response = client.post(
        "/api/v1/graphs/snapshot-1/revisions",
        json={"title": "Hide child", "created_by": "tester"},
    )
    revision_id = revision_response.json()["revision_id"]
    override_response = client.post(
        f"/api/v1/revisions/{revision_id}/overrides",
        json={
            "operation": "SUPPRESS_NODE",
            "payload": {"node_id": "child", "confirm_incident_edges": True},
            "reason": "not in scope",
            "created_by": "tester",
        },
    )
    commit_response = client.post(f"/api/v1/revisions/{revision_id}/commit")
    historical_node_response = client.get("/api/v1/graphs/snapshot-1/nodes/child")

    assert revision_response.status_code == 201
    assert revision_response.json()["status"] == "DRAFT"
    assert override_response.status_code == 201
    assert override_response.json()["operation"] == "SUPPRESS_NODE"
    assert override_response.json()["target_node_id"] == "child"
    assert commit_response.status_code == 200
    assert commit_response.json()["status"] == "COMMITTED"
    assert historical_node_response.status_code == 200
    assert historical_node_response.json()["node_id"] == "child"


def test_graphs_api_lists_revisions(tmp_path: Path) -> None:
    client = create_client_with_published_snapshot(tmp_path)
    first = client.post(
        "/api/v1/graphs/snapshot-1/revisions",
        json={"title": "First", "created_by": "tester"},
    ).json()
    second = client.post(
        "/api/v1/graphs/snapshot-1/revisions",
        json={"title": "Second", "created_by": "tester"},
    ).json()

    response = client.get("/api/v1/graphs/snapshot-1/revisions")

    assert response.status_code == 200
    assert [revision["revision_id"] for revision in response.json()] == [
        first["revision_id"],
        second["revision_id"],
    ]


def test_graphs_api_projection_applies_revision_without_mutating_snapshot(tmp_path: Path) -> None:
    client = create_client_with_published_snapshot(tmp_path)
    revision_id = client.post(
        "/api/v1/graphs/snapshot-1/revisions",
        json={"title": "Hide child"},
    ).json()["revision_id"]
    override_response = client.post(
        f"/api/v1/revisions/{revision_id}/overrides",
        json={
            "operation": "SUPPRESS_NODE",
            "payload": {"node_id": "child", "confirm_incident_edges": True},
        },
    )

    revised = client.get(f"/api/v1/audits/audit-1/graph?revision_id={revision_id}")
    original = client.get("/api/v1/audits/audit-1/graph")

    assert override_response.status_code == 201
    assert revised.status_code == 200
    assert [node["node_id"] for node in revised.json()["nodes"]] == ["parent-1", "parent-2"]
    assert revised.json()["edges"] == []
    assert revised.json()["revision"]["revision_id"] == revision_id
    assert [node["node_id"] for node in original.json()["nodes"]] == [
        "parent-1",
        "child",
        "parent-2",
    ]


def test_manual_overrides_support_all_operation_types(tmp_path: Path) -> None:
    client = create_client_with_published_snapshot(tmp_path)
    revision_id = client.post("/api/v1/graphs/snapshot-1/revisions", json={}).json()["revision_id"]

    operations = [
        {
            "operation": "ADD_NODE",
            "payload": {"node": manual_node_payload("manual-1")},
        },
        {
            "operation": "UPDATE_NODE",
            "payload": {"node_id": "child", "updates": {"name": "child renamed"}},
        },
        {
            "operation": "MOVE_NODE",
            "payload": {"node_id": "child", "new_parent_node_id": "manual-1"},
        },
        {
            "operation": "SUPPRESS_NODE",
            "payload": {"node_id": "child", "confirm_incident_edges": True},
        },
        {
            "operation": "RESTORE_NODE",
            "payload": {"node_id": "child"},
        },
        {
            "operation": "ADD_EDGE",
            "payload": {"edge": manual_edge_payload("manual-edge-1", "manual-1", "child")},
        },
        {
            "operation": "UPDATE_EDGE",
            "payload": {"edge_id": "contains-1", "updates": {"protocol": "manual"}},
        },
        {
            "operation": "SUPPRESS_EDGE",
            "payload": {"edge_id": "contains-1"},
        },
        {
            "operation": "RESTORE_EDGE",
            "payload": {"edge_id": "contains-1"},
        },
    ]

    responses = [
        client.post(f"/api/v1/revisions/{revision_id}/overrides", json=operation)
        for operation in operations
    ]

    assert [response.status_code for response in responses] == [201] * len(operations)
    assert [response.json()["operation"] for response in responses] == [
        operation["operation"] for operation in operations
    ]


def test_dangerous_node_suppression_requires_explicit_confirmations(tmp_path: Path) -> None:
    client = create_client_with_published_snapshot(tmp_path)
    revision_id = client.post("/api/v1/graphs/snapshot-1/revisions", json={}).json()["revision_id"]

    rejected = client.post(
        f"/api/v1/revisions/{revision_id}/overrides",
        json={"operation": "SUPPRESS_NODE", "payload": {"node_id": "parent-1"}},
    )
    accepted = client.post(
        f"/api/v1/revisions/{revision_id}/overrides",
        json={
            "operation": "SUPPRESS_NODE",
            "payload": {
                "node_id": "parent-1",
                "confirm_children_strategy": "SUPPRESS_DESCENDANTS",
                "confirm_incident_edges": True,
                "confirm_high_impact": True,
            },
        },
    )

    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "GRAPH_DANGEROUS_SUPPRESSION_REQUIRES_CONFIRMATION"
    assert set(rejected.json()["details"]["missing_confirmations"]) == {
        "confirm_children_strategy",
        "confirm_incident_edges",
        "confirm_high_impact",
    }
    assert accepted.status_code == 201


def test_unsaved_manual_node_can_be_physically_deleted_only_before_commit(
    tmp_path: Path,
) -> None:
    client = create_client_with_published_snapshot(tmp_path)
    revision_id = client.post("/api/v1/graphs/snapshot-1/revisions", json={}).json()["revision_id"]
    add_response = client.post(
        f"/api/v1/revisions/{revision_id}/overrides",
        json={"operation": "ADD_NODE", "payload": {"node": manual_node_payload("manual-delete")}},
    )

    delete_response = client.delete(
        f"/api/v1/revisions/{revision_id}/manual-nodes/manual-delete"
    )
    second_delete_response = client.delete(
        f"/api/v1/revisions/{revision_id}/manual-nodes/manual-delete"
    )

    assert add_response.status_code == 201
    assert delete_response.status_code == 204
    assert second_delete_response.status_code == 404

    saved_revision_id = client.post("/api/v1/graphs/snapshot-1/revisions", json={}).json()[
        "revision_id"
    ]
    client.post(
        f"/api/v1/revisions/{saved_revision_id}/overrides",
        json={"operation": "ADD_NODE", "payload": {"node": manual_node_payload("manual-saved")}},
    )
    client.post(f"/api/v1/revisions/{saved_revision_id}/commit")

    saved_delete_response = client.delete(
        f"/api/v1/revisions/{saved_revision_id}/manual-nodes/manual-saved"
    )

    assert saved_delete_response.status_code == 409


def test_revision_rejects_second_active_contains_parent(tmp_path: Path) -> None:
    client = create_client_with_published_snapshot(tmp_path)
    revision_id = client.post("/api/v1/graphs/snapshot-1/revisions", json={}).json()["revision_id"]

    response = client.post(
        f"/api/v1/revisions/{revision_id}/overrides",
        json={
            "operation": "ADD_EDGE",
            "payload": {
                "edge_type": "CONTAINS",
                "source_node_id": "parent-2",
                "target_node_id": "child",
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "GRAPH_ACTIVE_PARENT_CONFLICT"


def test_graphs_api_returns_not_found_for_missing_graph(tmp_path: Path) -> None:
    client = create_client(tmp_path)

    response = client.get("/api/v1/audits/audit-missing/graph")

    assert response.status_code == 404
    assert response.json()["error_code"] == "GRAPH_NOT_FOUND"


def create_client_with_published_snapshot(tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'api.db'}"
    session_factory = migrate_and_create_app(tmp_path, database_url).state.session_factory
    with session_scope(session_factory) as session:
        create_audit_fixture(session)
        GraphSnapshotRepository(session).publish_snapshot(make_snapshot())
    return create_client(tmp_path, database_url=database_url)


def create_client(tmp_path: Path, *, database_url: str | None = None) -> TestClient:
    database_url = database_url or f"sqlite:///{tmp_path / 'api.db'}"
    run_migrations(database_url)
    app = create_app(
        config=AppConfig(
            app_env="test",
            database_url=database_url,
            repository_allowed_roots=(tmp_path,),
        ),
        llm_provider=FakeLlmProvider(),
    )
    return TestClient(app)


def migrate_and_create_app(tmp_path: Path, database_url: str):
    run_migrations(database_url)
    return create_app(
        config=AppConfig(
            app_env="test",
            database_url=database_url,
            repository_allowed_roots=(tmp_path,),
        ),
        llm_provider=FakeLlmProvider(),
    )


def run_migrations(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


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


def make_snapshot() -> GraphSnapshot:
    return GraphSnapshot(
        snapshot_id="snapshot-1",
        project_id="project-1",
        audit_id="audit-1",
        repository_state_id="repo-state-1",
        nodes=(
            make_node(
                node_id="parent-1",
                stable_key="project/FUNCTIONAL_SUBSYSTEM/parent-1",
                name="parent 1",
                node_type=NodeType.FUNCTIONAL_SUBSYSTEM,
            ),
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
    node_type: NodeType = NodeType.MODULE,
) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        stable_key=stable_key,
        node_type=node_type,
        name=name,
        origin=EntityOrigin.INFERRED,
        validation_state=ValidationState.CONFIRMED,
        confidence=0.9,
        evidence=(make_evidence(f"{node_id}-evidence"),),
    )


def manual_node_payload(node_id: str) -> dict[str, object]:
    return GraphNode(
        node_id=node_id,
        stable_key=f"project/MODULE/manual/{node_id}",
        node_type=NodeType.MODULE,
        name=node_id,
        origin=EntityOrigin.MANUAL,
        validation_state=ValidationState.CONFIRMED,
        confidence=1.0,
    ).model_dump(mode="json")


def manual_edge_payload(edge_id: str, source_node_id: str, target_node_id: str) -> dict[str, object]:
    return GraphEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=EdgeType.DEPENDS_ON,
        origin=EntityOrigin.MANUAL,
        validation_state=ValidationState.CONFIRMED,
        confidence=1.0,
    ).model_dump(mode="json")


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
