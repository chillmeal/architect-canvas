from app.analysis.incremental import (
    AnalysisUnitFingerprint,
    IncrementalDecision,
    IncrementalPolicyVersions,
    IncrementalReason,
    IncrementalReusePlanner,
    ReusableAnalysisUnitResult,
    UnitDependencyGraph,
)
from app.contracts.graph import CandidateFact, Evidence, ValidationRecord
from app.domain.enums import (
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ValidationState,
)
from app.graph.assembler import ValidatedCandidateFact

VERSIONS = IncrementalPolicyVersions(
    prompt_version="prompt-v1",
    schema_version="schema-v1",
    ontology_version="ontology-v1",
    validation_policy_version="validation-v1",
)


def test_reuses_unit_only_when_fingerprint_and_policy_versions_match() -> None:
    fingerprint = make_fingerprint(unit_id="unit-a")
    plan = IncrementalReusePlanner().plan(
        current_fingerprints=(fingerprint,),
        previous_results={"unit-a": make_previous_result(fingerprint)},
    )

    assert plan.reused_unit_ids == ("unit-a",)
    assert plan.items[0].decision == IncrementalDecision.REUSE
    assert plan.items[0].reason == IncrementalReason.REUSABLE


def test_policy_version_change_forces_reanalysis() -> None:
    previous = make_fingerprint(unit_id="unit-a")
    current = make_fingerprint(
        unit_id="unit-a",
        versions=IncrementalPolicyVersions(
            prompt_version="prompt-v2",
            schema_version="schema-v1",
            ontology_version="ontology-v1",
            validation_policy_version="validation-v1",
        ),
    )

    plan = IncrementalReusePlanner().plan(
        current_fingerprints=(current,),
        previous_results={"unit-a": make_previous_result(previous)},
    )

    assert plan.units_to_analyze == ("unit-a",)
    assert plan.items[0].reason == IncrementalReason.POLICY_VERSION_CHANGED
    assert plan.items[0].metadata["prompt_version_changed"] is True


def test_boundary_change_invalidates_dependent_units() -> None:
    previous_a = make_fingerprint(
        unit_id="unit-a",
        file_hashes={"openapi.yaml": "old-contract"},
    )
    current_a = make_fingerprint(
        unit_id="unit-a",
        file_hashes={"openapi.yaml": "new-contract"},
    )
    unit_b = make_fingerprint(unit_id="unit-b", file_hashes={"src/index.ts": "same"})

    plan = IncrementalReusePlanner().plan(
        current_fingerprints=(current_a, unit_b),
        previous_results={
            "unit-a": make_previous_result(previous_a),
            "unit-b": make_previous_result(unit_b),
        },
        dependency_graph=UnitDependencyGraph(depends_on={"unit-b": frozenset({"unit-a"})}),
    )

    by_unit = {item.unit_id: item for item in plan.items}
    assert by_unit["unit-a"].reason == IncrementalReason.UNIT_FINGERPRINT_CHANGED
    assert by_unit["unit-b"].reason == IncrementalReason.DEPENDENT_UNIT_CHANGED
    assert plan.units_to_analyze == ("unit-a", "unit-b")


def test_non_boundary_source_change_does_not_rerun_unchanged_dependent_unit() -> None:
    previous_a = make_fingerprint(unit_id="unit-a", file_hashes={"src/index.ts": "old"})
    current_a = make_fingerprint(unit_id="unit-a", file_hashes={"src/index.ts": "new"})
    unit_b = make_fingerprint(unit_id="unit-b", file_hashes={"src/client.ts": "same"})

    plan = IncrementalReusePlanner().plan(
        current_fingerprints=(current_a, unit_b),
        previous_results={
            "unit-a": make_previous_result(previous_a),
            "unit-b": make_previous_result(unit_b),
        },
        dependency_graph=UnitDependencyGraph(depends_on={"unit-b": frozenset({"unit-a"})}),
    )

    by_unit = {item.unit_id: item for item in plan.items}
    assert by_unit["unit-a"].decision == IncrementalDecision.ANALYZE
    assert by_unit["unit-b"].decision == IncrementalDecision.REUSE


def test_reused_candidates_are_cloned_without_old_snapshot_entity_ids() -> None:
    fingerprint = make_fingerprint(unit_id="unit-a")
    previous_result = make_previous_result(fingerprint)

    plan = IncrementalReusePlanner().plan(
        current_fingerprints=(fingerprint,),
        previous_results={"unit-a": previous_result},
    )

    reused_candidate = plan.items[0].reused_candidates[0].candidate
    assert reused_candidate.metadata["reused"] is True
    assert "node_id" not in reused_candidate.metadata
    assert "edge_id" not in reused_candidate.metadata
    assert previous_result.validated_candidates[0].candidate.metadata["node_id"] == "old-node-id"


def make_fingerprint(
    *,
    unit_id: str,
    file_hashes: dict[str, str] | None = None,
    versions: IncrementalPolicyVersions = VERSIONS,
    dependency_hints: tuple[str, ...] = ("fastapi",),
    parent_stable_key: str | None = "project-1/MODULE/root",
) -> AnalysisUnitFingerprint:
    return AnalysisUnitFingerprint(
        unit_id=unit_id,
        file_hashes=tuple(sorted((file_hashes or {"src/index.ts": "same"}).items())),
        dependency_hints=dependency_hints,
        root_paths=(unit_id.removeprefix("unit-"),),
        prompt_version=versions.prompt_version,
        schema_version=versions.schema_version,
        ontology_version=versions.ontology_version,
        validation_policy_version=versions.validation_policy_version,
        parent_stable_key=parent_stable_key,
    )


def make_previous_result(fingerprint: AnalysisUnitFingerprint) -> ReusableAnalysisUnitResult:
    return ReusableAnalysisUnitResult(
        audit_id="audit-old",
        snapshot_id="snapshot-old",
        fingerprint=fingerprint,
        validated_candidates=(validated_candidate(fingerprint.unit_id),),
    )


def validated_candidate(unit_id: str) -> ValidatedCandidateFact:
    evidence = make_evidence(unit_id)
    return ValidatedCandidateFact(
        candidate=CandidateFact(
            fact_id=f"{unit_id}-fact",
            fact_kind="NODE",
            candidate_schema_version="schema-v1",
            node_type=NodeType.MICROSERVICE,
            name=unit_id,
            evidence=(evidence,),
            metadata={"stable_key": f"project-1/MICROSERVICE/{unit_id}", "node_id": "old-node-id"},
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


def make_evidence(unit_id: str) -> Evidence:
    return Evidence(
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
