from app.contracts.graph import CandidateFact, Evidence
from app.domain.enums import (
    EdgeType,
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ReasonCode,
    ValidationState,
)
from app.validation import (
    DeterministicSemanticValidator,
    SemanticEdgeKey,
    SemanticValidationContext,
)


def test_semantic_validator_confirms_runtime_call_with_url_signal() -> None:
    fact = make_edge_fact(
        edge_type=EdgeType.SYNC_CALL,
        source="project/MICROSERVICE/payments",
        target="project/MICROSERVICE/orders",
        evidence=(
            make_evidence(
                evidence_id="evidence-1",
                source_type=EvidenceSourceType.SOURCE_CODE,
                marker="ordersClient calls https://orders.internal/api/orders",
            ),
        ),
    )

    outcome = DeterministicSemanticValidator().validate(fact, make_context())

    assert outcome.accepted is True
    assert outcome.result.state == ValidationState.CONFIRMED


def test_semantic_validator_reviews_runtime_call_from_build_dependency_only() -> None:
    fact = make_edge_fact(
        edge_type=EdgeType.SYNC_CALL,
        source="project/MICROSERVICE/payments",
        target="project/MICROSERVICE/orders",
        evidence=(
            make_evidence(
                evidence_id="pom",
                source_type=EvidenceSourceType.MANIFEST,
                marker="<artifactId>orders-client</artifactId>",
            ),
        ),
    )

    outcome = DeterministicSemanticValidator().validate(fact, make_context())

    assert outcome.result.state == ValidationState.REVIEW_REQUIRED
    assert outcome.result.reason_codes == (ReasonCode.INSUFFICIENT_SOURCE_SIGNALS,)


def test_semantic_validator_confirms_kafka_topic_node_from_evidence() -> None:
    fact = make_node_fact(
        node_type=NodeType.TOPIC,
        name="orders.created",
        evidence=(
            make_evidence(
                evidence_id="topic",
                source_type=EvidenceSourceType.CONFIGURATION,
                marker="spring.cloud.stream.bindings.output.destination=orders.created",
            ),
        ),
    )

    outcome = DeterministicSemanticValidator().validate(fact, make_context())

    assert outcome.result.state == ValidationState.CONFIRMED


def test_semantic_validator_reviews_missing_datasource_signal() -> None:
    fact = make_node_fact(
        node_type=NodeType.DATABASE,
        name="payments",
        evidence=(
            make_evidence(
                evidence_id="readme",
                source_type=EvidenceSourceType.DOCUMENTATION,
                marker="payments storage",
            ),
        ),
    )

    outcome = DeterministicSemanticValidator().validate(fact, make_context())

    assert outcome.result.state == ValidationState.REVIEW_REQUIRED


def test_semantic_validator_rejects_missing_edge_source_or_target() -> None:
    fact = make_edge_fact(
        edge_type=EdgeType.SYNC_CALL,
        source="project/MICROSERVICE/missing",
        target="project/MICROSERVICE/orders",
        evidence=(make_evidence(marker="https://orders.internal"),),
    )

    outcome = DeterministicSemanticValidator().validate(fact, make_context())

    assert outcome.result.state == ValidationState.REJECTED
    assert outcome.result.reason_codes == (ReasonCode.SOURCE_TARGET_MISSING,)


def test_semantic_validator_rejects_duplicate_edge() -> None:
    fact = make_edge_fact(
        edge_type=EdgeType.SYNC_CALL,
        source="project/MICROSERVICE/payments",
        target="project/MICROSERVICE/orders",
        evidence=(make_evidence(marker="https://orders.internal"),),
    )
    context = make_context(
        existing_edges=(
            SemanticEdgeKey(
                source_stable_key="project/MICROSERVICE/payments",
                target_stable_key="project/MICROSERVICE/orders",
                edge_type=EdgeType.SYNC_CALL,
            ),
        )
    )

    outcome = DeterministicSemanticValidator().validate(fact, context)

    assert outcome.result.state == ValidationState.REJECTED
    assert outcome.result.reason_codes == (ReasonCode.DUPLICATE_EDGE,)


def test_semantic_validator_rejects_invalid_parent_type() -> None:
    fact = make_edge_fact(
        edge_type=EdgeType.CONTAINS,
        source="project/MICROSERVICE/payments",
        target="project/MICROSERVICE/orders",
        evidence=(make_evidence(marker="payments contains orders"),),
    )

    outcome = DeterministicSemanticValidator().validate(fact, make_context())

    assert outcome.result.state == ValidationState.REJECTED
    assert outcome.result.reason_codes == (ReasonCode.INVALID_PARENT_TYPE,)


def test_semantic_validator_rejects_invalid_contains_direction() -> None:
    fact = make_edge_fact(
        edge_type=EdgeType.CONTAINS,
        source="project/MODULE/payments-module",
        target="project/FUNCTIONAL_SUBSYSTEM/payments-subsystem",
        evidence=(make_evidence(marker="module contains subsystem"),),
    )
    context = make_context(
        extra_nodes={
            "project/MODULE/payments-module": NodeType.MODULE,
            "project/FUNCTIONAL_SUBSYSTEM/payments-subsystem": NodeType.FUNCTIONAL_SUBSYSTEM,
        }
    )

    outcome = DeterministicSemanticValidator().validate(fact, context)

    assert outcome.result.state == ValidationState.REJECTED
    assert outcome.result.reason_codes == (ReasonCode.INVALID_EDGE_DIRECTION,)


def test_semantic_validator_confirms_valid_contains_edge() -> None:
    fact = make_edge_fact(
        edge_type=EdgeType.CONTAINS,
        source="project/FUNCTIONAL_SUBSYSTEM/payments",
        target="project/MICROSERVICE/payments",
        evidence=(make_evidence(marker="payments subsystem contains payments service"),),
    )
    context = make_context(
        extra_nodes={"project/FUNCTIONAL_SUBSYSTEM/payments": NodeType.FUNCTIONAL_SUBSYSTEM}
    )

    outcome = DeterministicSemanticValidator().validate(fact, context)

    assert outcome.result.state == ValidationState.CONFIRMED


def make_context(
    *,
    existing_edges: tuple[SemanticEdgeKey, ...] = (),
    extra_nodes: dict[str, NodeType] | None = None,
) -> SemanticValidationContext:
    nodes = {
        "project/MICROSERVICE/payments": NodeType.MICROSERVICE,
        "project/MICROSERVICE/orders": NodeType.MICROSERVICE,
    }
    nodes.update(extra_nodes or {})
    return SemanticValidationContext(node_types_by_stable_key=nodes, existing_edges=existing_edges)


def make_node_fact(
    *,
    node_type: NodeType,
    name: str,
    evidence: tuple[Evidence, ...],
) -> CandidateFact:
    return CandidateFact(
        fact_id="fact-node",
        fact_kind="NODE",
        candidate_schema_version="0.1.0",
        node_type=node_type,
        name=name,
        evidence=evidence,
    )


def make_edge_fact(
    *,
    edge_type: EdgeType,
    source: str,
    target: str,
    evidence: tuple[Evidence, ...],
) -> CandidateFact:
    return CandidateFact(
        fact_id="fact-edge",
        fact_kind="EDGE",
        candidate_schema_version="0.1.0",
        edge_type=edge_type,
        source_stable_key=source,
        target_stable_key=target,
        evidence=evidence,
    )


def make_evidence(
    *,
    evidence_id: str = "evidence-1",
    source_type: EvidenceSourceType = EvidenceSourceType.SOURCE_CODE,
    marker: str,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        relative_path="src/main.py",
        file_hash="sha256:abc",
        line_start=1,
        line_end=1,
        source_fragment_marker=marker,
        source_type=source_type,
        strength=EvidenceStrength.STRONG,
        analysis_unit_id="unit-1",
    )
