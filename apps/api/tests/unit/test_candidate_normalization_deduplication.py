from app.contracts.graph import CandidateFact, Evidence
from app.domain.enums import (
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ReasonCode,
)
from app.graph.deduplicator import CandidateDeduplicator
from app.graph.normalizer import CandidateNormalizer


def test_candidate_normalizer_trims_unicode_aliases_and_builds_stable_key() -> None:
    candidate = make_node_fact(
        fact_id="fact-1",
        node_type=NodeType.MICROSERVICE,
        name="  Cafe\u0301 API  ",
        metadata={
            "owner_path": ["Subsystem", "Payments"],
            "artifact_id": " cafe-api ",
            "package_name": "com.example.cafe",
            "deployment_name": "cafe-prod",
            "repository_path": "services/cafe",
            "aliases": [" CAFE API ", "cafe-api"],
        },
    )

    result = CandidateNormalizer().normalize(project_id="Project A", candidates=(candidate,))
    normalized = result.candidates[0]

    assert result.issues == ()
    assert normalized.name == "Café API"
    assert normalized.metadata["normalized_name"] == "café-api"
    assert normalized.metadata["normalized_aliases"] == ("cafe-api",)
    assert normalized.metadata["stable_key"] == (
        "project-a/MICROSERVICE/subsystem/payments/"
        "café-api__artifact-cafe-api__deployment-cafe-prod__"
        "package-com.example.cafe__path-services-cafe"
    )


def test_deduplicator_merges_exact_duplicates_and_evidence() -> None:
    normalized = CandidateNormalizer().normalize(
        project_id="project",
        candidates=(
            make_node_fact("fact-1", evidence_id="evidence-1"),
            make_node_fact("fact-2", evidence_id="evidence-2"),
        ),
    ).candidates

    result = CandidateDeduplicator().deduplicate(normalized)

    assert result.issues == ()
    assert len(result.candidates) == 1
    assert [evidence.evidence_id for evidence in result.candidates[0].evidence] == [
        "evidence-1",
        "evidence-2",
    ]
    assert result.candidates[0].metadata["merged_fact_ids"] == ("fact-1", "fact-2")


def test_deduplicator_flags_ambiguous_artifact_match_with_conflicting_type() -> None:
    normalized = CandidateNormalizer().normalize(
        project_id="project",
        candidates=(
            make_node_fact("fact-1", node_type=NodeType.MICROSERVICE),
            make_node_fact("fact-2", node_type=NodeType.INFRA_COMPONENT),
        ),
    ).candidates

    result = CandidateDeduplicator().deduplicate(normalized)

    assert result.candidates == ()
    assert len(result.issues) == 1
    assert result.issues[0].reason_code == ReasonCode.DUPLICATE_CANDIDATE
    assert result.issues[0].related_fact_ids == ("fact-1", "fact-2")


def test_deduplicator_uses_deployment_package_and_alias_identity() -> None:
    normalized = CandidateNormalizer().normalize(
        project_id="project",
        candidates=(
            make_node_fact(
                "deployment-1",
                name="billing api",
                metadata={"deployment_name": "billing-prod", "repository_path": "svc/a"},
            ),
            make_node_fact(
                "deployment-2",
                name="billing service",
                metadata={"deployment_name": "billing-prod", "repository_path": "svc/b"},
            ),
            make_node_fact(
                "package-1",
                name="accounts api",
                metadata={"package_name": "com.example.accounts", "repository_path": "svc/c"},
            ),
            make_node_fact(
                "package-2",
                name="accounts worker",
                metadata={"package_name": "com.example.accounts", "repository_path": "svc/d"},
            ),
            make_node_fact(
                "alias-1",
                name="catalog api",
                metadata={"aliases": ["catalog"], "repository_path": "svc/e"},
            ),
            make_node_fact(
                "alias-2",
                name="catalog service",
                metadata={"aliases": ["catalog"], "repository_path": "svc/f"},
            ),
        ),
    ).candidates

    result = CandidateDeduplicator().deduplicate(normalized)

    assert result.candidates == ()
    assert len(result.issues) == 3
    assert {issue.reason_code for issue in result.issues} == {ReasonCode.DUPLICATE_CANDIDATE}


def make_node_fact(
    fact_id: str,
    *,
    node_type: NodeType = NodeType.MICROSERVICE,
    name: str = "billing api",
    evidence_id: str = "evidence-1",
    metadata: dict[str, object] | None = None,
) -> CandidateFact:
    return CandidateFact(
        fact_id=fact_id,
        fact_kind="NODE",
        candidate_schema_version="0.1.0",
        node_type=node_type,
        name=name,
        evidence=(make_evidence(evidence_id),),
        metadata=metadata
        or {
            "artifact_id": "billing-api",
            "repository_path": "services/billing",
        },
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
