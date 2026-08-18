from app.contracts.graph import GraphEdge, GraphNode, GraphSnapshot
from app.domain.enums import EdgeType, EntityOrigin, NodeType, ReasonCode, ValidationState
from app.validation import GraphLevelValidator, GraphValidationInput


def test_graph_validator_accepts_valid_hierarchy() -> None:
    outcome = GraphLevelValidator().validate(GraphValidationInput(snapshot=valid_snapshot()))

    assert outcome.valid is True
    assert outcome.auto_publish_allowed is True


def test_graph_validator_rejects_containment_cycle() -> None:
    snapshot = make_snapshot(
        nodes=(node("root", NodeType.MODULE), node("child", NodeType.SUBMODULE)),
        edges=(
            edge("e1", "root", "child", EdgeType.CONTAINS),
            edge("e2", "child", "root", EdgeType.CONTAINS),
        ),
    )

    outcome = GraphLevelValidator().validate(GraphValidationInput(snapshot=snapshot))

    assert ReasonCode.CONTAINMENT_CYCLE in reason_codes(outcome)
    assert outcome.auto_publish_allowed is False


def test_graph_validator_rejects_more_than_one_active_parent() -> None:
    snapshot = make_snapshot(
        nodes=(
            node("root", NodeType.MODULE),
            node("other", NodeType.MODULE),
            node("child", NodeType.MICROSERVICE),
        ),
        edges=(
            edge("e1", "root", "child", EdgeType.CONTAINS),
            edge("e2", "other", "child", EdgeType.CONTAINS),
        ),
    )

    outcome = GraphLevelValidator().validate(GraphValidationInput(snapshot=snapshot))

    assert ReasonCode.HARD_INVARIANT_VIOLATION in reason_codes(outcome)
    assert outcome.auto_publish_allowed is False


def test_graph_validator_requires_root_hierarchy() -> None:
    snapshot = make_snapshot(nodes=(node("svc", NodeType.MICROSERVICE),), edges=())

    outcome = GraphLevelValidator().validate(GraphValidationInput(snapshot=snapshot))

    assert ReasonCode.HARD_INVARIANT_VIOLATION in reason_codes(outcome)
    assert outcome.auto_publish_allowed is True


def test_graph_validator_marks_orphan_nodes_for_review() -> None:
    snapshot = make_snapshot(
        nodes=(node("root", NodeType.MODULE), node("svc", NodeType.MICROSERVICE)),
        edges=(),
    )

    outcome = GraphLevelValidator().validate(GraphValidationInput(snapshot=snapshot))

    assert any(issue.metadata.get("node_id") == "svc" for issue in outcome.issues)
    assert outcome.auto_publish_allowed is True


def test_graph_validator_rejects_duplicate_nodes() -> None:
    snapshot = make_snapshot(
        nodes=(
            node("root", NodeType.MODULE, stable_key="same"),
            node("other", NodeType.MODULE, stable_key="same"),
        ),
        edges=(),
    )

    outcome = GraphLevelValidator().validate(GraphValidationInput(snapshot=snapshot))

    assert ReasonCode.DUPLICATE_NODE in reason_codes(outcome)
    assert outcome.auto_publish_allowed is False


def test_graph_validator_rejects_duplicate_edges() -> None:
    snapshot = make_snapshot(
        nodes=(node("root", NodeType.MODULE), node("svc", NodeType.MICROSERVICE)),
        edges=(
            edge("e1", "root", "svc", EdgeType.CONTAINS),
            edge("e2", "root", "svc", EdgeType.CONTAINS),
        ),
    )

    outcome = GraphLevelValidator().validate(GraphValidationInput(snapshot=snapshot))

    assert ReasonCode.DUPLICATE_EDGE in reason_codes(outcome)
    assert outcome.auto_publish_allowed is False


def test_graph_validator_rejects_impossible_edge_type() -> None:
    snapshot = make_snapshot(
        nodes=(node("root", NodeType.MODULE), node("svc", NodeType.MICROSERVICE)),
        edges=(edge("e1", "root", "svc", EdgeType.DATA_READ),),
    )

    outcome = GraphLevelValidator().validate(GraphValidationInput(snapshot=snapshot))

    assert ReasonCode.INVALID_EDGE_DIRECTION in reason_codes(outcome)
    assert outcome.auto_publish_allowed is False


def test_graph_validator_rejects_edges_on_suppressed_nodes() -> None:
    snapshot = valid_snapshot()

    outcome = GraphLevelValidator().validate(
        GraphValidationInput(snapshot=snapshot, suppressed_node_ids=frozenset({"svc"}))
    )

    assert ReasonCode.HARD_INVARIANT_VIOLATION in reason_codes(outcome)
    assert outcome.auto_publish_allowed is False


def test_graph_validator_blocks_auto_publish_on_mass_disappearance() -> None:
    snapshot = valid_snapshot()

    outcome = GraphLevelValidator().validate(
        GraphValidationInput(
            snapshot=snapshot,
            previous_confirmed_stable_keys=frozenset(
                {"project/root", "project/svc", "project/old-a", "project/old-b"}
            ),
            max_confirmed_disappearance_ratio=0.25,
        )
    )

    assert ReasonCode.REVIEW_REQUIRED in reason_codes(outcome)
    assert outcome.auto_publish_allowed is False


def valid_snapshot() -> GraphSnapshot:
    return make_snapshot(
        nodes=(node("root", NodeType.MODULE), node("svc", NodeType.MICROSERVICE)),
        edges=(edge("contains", "root", "svc", EdgeType.CONTAINS),),
    )


def make_snapshot(
    *,
    nodes: tuple[GraphNode, ...],
    edges: tuple[GraphEdge, ...],
) -> GraphSnapshot:
    return GraphSnapshot(
        snapshot_id="snapshot-1",
        project_id="project-1",
        audit_id="audit-1",
        repository_state_id="repo-state-1",
        nodes=nodes,
        edges=edges,
    )


def node(
    node_id: str,
    node_type: NodeType,
    *,
    stable_key: str | None = None,
) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        stable_key=stable_key or f"project/{node_id}",
        node_type=node_type,
        name=node_id,
        origin=EntityOrigin.MANUAL,
        validation_state=ValidationState.CONFIRMED,
        confidence=1.0,
    )


def edge(
    edge_id: str,
    source: str,
    target: str,
    edge_type: EdgeType,
) -> GraphEdge:
    return GraphEdge(
        edge_id=edge_id,
        source_node_id=source,
        target_node_id=target,
        edge_type=edge_type,
        origin=EntityOrigin.MANUAL,
        validation_state=ValidationState.CONFIRMED,
        confidence=1.0,
    )


def reason_codes(outcome) -> set[ReasonCode]:
    return {issue.reason_code for issue in outcome.issues}
