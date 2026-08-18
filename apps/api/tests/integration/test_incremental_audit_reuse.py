from pathlib import Path

from app.analysis.incremental import (
    AnalysisUnitFingerprint,
    IncrementalDecision,
    IncrementalPolicyVersions,
    IncrementalReusePlanner,
    ReusableAnalysisUnitResult,
)
from app.contracts.graph import CandidateFact, Evidence, ValidationRecord
from app.domain.enums import EvidenceSourceType, EvidenceStrength, NodeType, ValidationState
from app.graph.assembler import ValidatedCandidateFact
from app.infrastructure.repository.scanner import RepositoryFileIndexer
from app.infrastructure.repository.unit_detector import AnalysisUnitDetector

VERSIONS = IncrementalPolicyVersions(
    prompt_version="prompt-v1",
    schema_version="schema-v1",
    ontology_version="ontology-v1",
    validation_policy_version="validation-v1",
)


def test_incremental_reuse_keeps_unchanged_units_when_one_service_changes(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    create_service(repository, "billing", "console.log('billing v1');")
    create_service(repository, "orders", "console.log('orders v1');")
    previous_fingerprints = detect_fingerprints(repository)

    (repository / "billing" / "src" / "index.ts").write_text(
        "console.log('billing v2');",
        encoding="utf-8",
    )
    current_fingerprints = detect_fingerprints(repository)

    previous_results = {
        fingerprint.unit_id: ReusableAnalysisUnitResult(
            audit_id="audit-previous",
            snapshot_id="snapshot-previous",
            fingerprint=fingerprint,
            validated_candidates=(validated_candidate(fingerprint.unit_id),),
        )
        for fingerprint in previous_fingerprints
    }

    plan = IncrementalReusePlanner().plan(
        current_fingerprints=current_fingerprints,
        previous_results=previous_results,
    )

    decisions = {item.unit_id: item.decision for item in plan.items}
    assert decisions["unit-billing"] == IncrementalDecision.ANALYZE
    assert decisions["unit-orders"] == IncrementalDecision.REUSE


def create_service(repository: Path, name: str, source: str) -> None:
    service_root = repository / name
    (service_root / "src").mkdir(parents=True, exist_ok=True)
    (service_root / "package.json").write_text(
        f'{{"name":"{name}","dependencies":{{}}}}',
        encoding="utf-8",
    )
    (service_root / "src" / "index.ts").write_text(source, encoding="utf-8")


def detect_fingerprints(repository: Path) -> tuple[AnalysisUnitFingerprint, ...]:
    file_index = RepositoryFileIndexer((repository,), max_file_bytes=100_000).index_files(repository)
    units = AnalysisUnitDetector(repository).detect(file_index)
    return tuple(
        AnalysisUnitFingerprint.from_unit(
            unit,
            versions=VERSIONS,
            parent_stable_key="project-1/MODULE/root",
        )
        for unit in units
    )


def validated_candidate(unit_id: str) -> ValidatedCandidateFact:
    evidence = Evidence(
        evidence_id=f"{unit_id}-evidence",
        relative_path="src/index.ts",
        file_hash="same",
        line_start=1,
        line_end=1,
        fragment_hash="fragment",
        source_type=EvidenceSourceType.SOURCE_CODE,
        strength=EvidenceStrength.STRONG,
        analysis_unit_id=unit_id,
    )
    return ValidatedCandidateFact(
        candidate=CandidateFact(
            fact_id=f"{unit_id}-fact",
            fact_kind="NODE",
            candidate_schema_version="schema-v1",
            node_type=NodeType.MICROSERVICE,
            name=unit_id,
            evidence=(evidence,),
            metadata={"stable_key": f"project-1/MICROSERVICE/{unit_id}"},
        ),
        validation_record=ValidationRecord(
            candidate_schema_version="schema-v1",
            evidence=(evidence,),
            policy_version="validation-v1",
            confidence=0.9,
            final_state=ValidationState.CONFIRMED,
            validated_at="2026-08-18T00:00:00Z",
        ),
    )
