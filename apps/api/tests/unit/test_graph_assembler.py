from app.contracts.graph import CandidateFact, Evidence, ValidationIssue, ValidationRecord
from app.domain.enums import (
    EdgeType,
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ReasonCode,
    ValidationState,
)
from app.graph.assembler import GraphAssembler, GraphAssemblyInput, ValidatedCandidateFact


def test_graph_assembler_uses_only_validated_publishable_facts() -> None:
    module_key = "project/MODULE/_root/payments__path-payments"
    service_key = "project/MICROSERVICE/payments/payments-api__artifact-payments-api"
    result = GraphAssembler().assemble(
        GraphAssemblyInput(
            snapshot_id="snapshot-1",
            project_id="project",
            audit_id="audit-1",
            repository_state_id="repo-state-1",
            candidates=(
                validated_node("module", module_key, NodeType.MODULE, ValidationState.CONFIRMED, 0.91),
                validated_node(
                    "service",
                    service_key,
                    NodeType.MICROSERVICE,
                    ValidationState.CONFIRMED_WITH_WARNINGS,
                    0.74,
                ),
                validated_edge(
                    "contains",
                    EdgeType.CONTAINS,
                    module_key,
                    service_key,
                    ValidationState.CONFIRMED,
                    0.9,
                ),
                validated_node(
                    "rejected",
                    "project/MICROSERVICE/payments/rejected__artifact-rejected",
                    NodeType.MICROSERVICE,
                    ValidationState.REJECTED,
                    0.0,
                ),
                validated_node(
                    "review",
                    "project/MICROSERVICE/payments/review__artifact-review",
                    NodeType.MICROSERVICE,
                    ValidationState.REVIEW_REQUIRED,
                    0.4,
                ),
            ),
        )
    )

    assert result.validation.valid is True
    assert [node.node_id for node in result.snapshot.nodes] == ["node-service", "node-module"]
    assert [edge.edge_id for edge in result.snapshot.edges] == ["edge-contains"]
    assert result.snapshot.edges[0].source_node_id == "node-module"
    assert result.snapshot.edges[0].target_node_id == "node-service"
    confidence_by_node_id = {node.node_id: node.confidence for node in result.snapshot.nodes}
    assert confidence_by_node_id["node-service"] == 0.74
    assert [item.candidate.fact_id for item in result.debug_candidates] == ["rejected", "review"]


def test_graph_assembler_keeps_input_issues_on_snapshot() -> None:
    issue = ValidationIssue(
        issue_id="issue-1",
        reason_code=ReasonCode.DUPLICATE_CANDIDATE,
        state=ValidationState.REVIEW_REQUIRED,
        message="ambiguous duplicate",
    )

    result = GraphAssembler().assemble(
        GraphAssemblyInput(
            snapshot_id="snapshot-1",
            project_id="project",
            audit_id="audit-1",
            repository_state_id="repo-state-1",
            candidates=(
                validated_node(
                    "module",
                    "project/MODULE/_root/payments__path-payments",
                    NodeType.MODULE,
                    ValidationState.CONFIRMED,
                    0.9,
                ),
            ),
            issues=(issue,),
        )
    )

    assert result.snapshot.issues == (issue,)


def validated_node(
    fact_id: str,
    stable_key: str,
    node_type: NodeType,
    state: ValidationState,
    confidence: float,
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
        validation_record=make_validation_record(state, confidence),
    )


def validated_edge(
    fact_id: str,
    edge_type: EdgeType,
    source_stable_key: str,
    target_stable_key: str,
    state: ValidationState,
    confidence: float,
) -> ValidatedCandidateFact:
    return ValidatedCandidateFact(
        candidate=CandidateFact(
            fact_id=fact_id,
            fact_kind="EDGE",
            candidate_schema_version="0.1.0",
            edge_type=edge_type,
            source_stable_key=source_stable_key,
            target_stable_key=target_stable_key,
            evidence=(make_evidence(f"{fact_id}-evidence"),),
            metadata={"edge_id": f"edge-{fact_id}"},
        ),
        validation_record=make_validation_record(state, confidence),
    )


def make_validation_record(state: ValidationState, confidence: float) -> ValidationRecord:
    return ValidationRecord(
        candidate_schema_version="0.1.0",
        evidence=(make_evidence("validation-evidence"),),
        policy_version="confidence-policy-v0.1",
        confidence=confidence,
        final_state=state,
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
