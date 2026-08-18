from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath

from app.graph.assembler import ValidatedCandidateFact
from app.infrastructure.repository.unit_detector import AnalysisUnit


class IncrementalDecision(StrEnum):
    REUSE = "REUSE"
    ANALYZE = "ANALYZE"


class IncrementalReason(StrEnum):
    REUSABLE = "REUSABLE"
    NO_PREVIOUS_RESULT = "NO_PREVIOUS_RESULT"
    UNIT_FINGERPRINT_CHANGED = "UNIT_FINGERPRINT_CHANGED"
    POLICY_VERSION_CHANGED = "POLICY_VERSION_CHANGED"
    DEPENDENT_UNIT_CHANGED = "DEPENDENT_UNIT_CHANGED"


@dataclass(frozen=True)
class IncrementalPolicyVersions:
    prompt_version: str
    schema_version: str
    ontology_version: str
    validation_policy_version: str


@dataclass(frozen=True)
class AnalysisUnitFingerprint:
    unit_id: str
    file_hashes: tuple[tuple[str, str], ...]
    dependency_hints: tuple[str, ...]
    root_paths: tuple[str, ...]
    prompt_version: str
    schema_version: str
    ontology_version: str
    validation_policy_version: str
    parent_stable_key: str | None = None

    @classmethod
    def from_unit(
        cls,
        analysis_unit: AnalysisUnit,
        *,
        versions: IncrementalPolicyVersions,
        parent_stable_key: str | None = None,
    ) -> AnalysisUnitFingerprint:
        return cls(
            unit_id=analysis_unit.unit_id,
            file_hashes=tuple(sorted(analysis_unit.file_hashes.items())),
            dependency_hints=tuple(sorted(analysis_unit.dependency_hints)),
            root_paths=tuple(sorted(analysis_unit.root_paths)),
            prompt_version=versions.prompt_version,
            schema_version=versions.schema_version,
            ontology_version=versions.ontology_version,
            validation_policy_version=versions.validation_policy_version,
            parent_stable_key=parent_stable_key,
        )


@dataclass(frozen=True)
class ReusableAnalysisUnitResult:
    audit_id: str
    snapshot_id: str
    fingerprint: AnalysisUnitFingerprint
    validated_candidates: tuple[ValidatedCandidateFact, ...]


@dataclass(frozen=True)
class UnitDependencyGraph:
    depends_on: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def dependents_of(self, changed_unit_ids: frozenset[str]) -> frozenset[str]:
        dependents: set[str] = set()
        queue = list(changed_unit_ids)
        while queue:
            changed_unit_id = queue.pop()
            for unit_id, dependency_ids in self.depends_on.items():
                if changed_unit_id not in dependency_ids or unit_id in dependents:
                    continue
                dependents.add(unit_id)
                queue.append(unit_id)
        return frozenset(dependents)


@dataclass(frozen=True)
class IncrementalPlanItem:
    unit_id: str
    decision: IncrementalDecision
    reason: IncrementalReason
    reused_candidates: tuple[ValidatedCandidateFact, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class IncrementalReusePlan:
    items: tuple[IncrementalPlanItem, ...]

    @property
    def reused_unit_ids(self) -> tuple[str, ...]:
        return tuple(item.unit_id for item in self.items if item.decision == IncrementalDecision.REUSE)

    @property
    def units_to_analyze(self) -> tuple[str, ...]:
        return tuple(item.unit_id for item in self.items if item.decision == IncrementalDecision.ANALYZE)


class IncrementalReusePlanner:
    def plan(
        self,
        *,
        current_fingerprints: tuple[AnalysisUnitFingerprint, ...],
        previous_results: Mapping[str, ReusableAnalysisUnitResult],
        dependency_graph: UnitDependencyGraph | None = None,
    ) -> IncrementalReusePlan:
        direct_changes = {
            fingerprint.unit_id: _direct_change_reason(fingerprint, previous_results.get(fingerprint.unit_id))
            for fingerprint in current_fingerprints
        }
        changed_unit_ids = frozenset(
            unit_id for unit_id, reason in direct_changes.items() if reason is not None
        )
        boundary_changed_unit_ids = frozenset(
            fingerprint.unit_id
            for fingerprint in current_fingerprints
            if _has_boundary_change(fingerprint, previous_results.get(fingerprint.unit_id))
        )
        dependent_invalidations = (dependency_graph or UnitDependencyGraph()).dependents_of(
            boundary_changed_unit_ids
        )

        items: list[IncrementalPlanItem] = []
        for fingerprint in sorted(current_fingerprints, key=lambda item: item.unit_id):
            previous_result = previous_results.get(fingerprint.unit_id)
            direct_reason = direct_changes[fingerprint.unit_id]
            if direct_reason is not None:
                items.append(
                    IncrementalPlanItem(
                        unit_id=fingerprint.unit_id,
                        decision=IncrementalDecision.ANALYZE,
                        reason=direct_reason,
                        metadata=_change_metadata(fingerprint, previous_result),
                    )
                )
                continue
            if fingerprint.unit_id in dependent_invalidations and fingerprint.unit_id not in changed_unit_ids:
                items.append(
                    IncrementalPlanItem(
                        unit_id=fingerprint.unit_id,
                        decision=IncrementalDecision.ANALYZE,
                        reason=IncrementalReason.DEPENDENT_UNIT_CHANGED,
                        metadata={"invalidated_by": sorted(boundary_changed_unit_ids)},
                    )
                )
                continue
            items.append(
                IncrementalPlanItem(
                    unit_id=fingerprint.unit_id,
                    decision=IncrementalDecision.REUSE,
                    reason=IncrementalReason.REUSABLE,
                    reused_candidates=_clone_for_new_snapshot(previous_result.validated_candidates),
                    metadata={
                        "reused_from_audit_id": previous_result.audit_id,
                        "reused_from_snapshot_id": previous_result.snapshot_id,
                    },
                )
            )
        return IncrementalReusePlan(items=tuple(items))


def _direct_change_reason(
    current: AnalysisUnitFingerprint,
    previous_result: ReusableAnalysisUnitResult | None,
) -> IncrementalReason | None:
    if previous_result is None:
        return IncrementalReason.NO_PREVIOUS_RESULT
    previous = previous_result.fingerprint
    if (
        current.prompt_version,
        current.schema_version,
        current.ontology_version,
        current.validation_policy_version,
    ) != (
        previous.prompt_version,
        previous.schema_version,
        previous.ontology_version,
        previous.validation_policy_version,
    ):
        return IncrementalReason.POLICY_VERSION_CHANGED
    if (
        current.file_hashes,
        current.dependency_hints,
        current.root_paths,
        current.parent_stable_key,
    ) != (
        previous.file_hashes,
        previous.dependency_hints,
        previous.root_paths,
        previous.parent_stable_key,
    ):
        return IncrementalReason.UNIT_FINGERPRINT_CHANGED
    return None


def _has_boundary_change(
    current: AnalysisUnitFingerprint,
    previous_result: ReusableAnalysisUnitResult | None,
) -> bool:
    if previous_result is None:
        return True
    previous = previous_result.fingerprint
    if current.dependency_hints != previous.dependency_hints:
        return True
    if current.parent_stable_key != previous.parent_stable_key:
        return True
    current_hashes = dict(current.file_hashes)
    previous_hashes = dict(previous.file_hashes)
    changed_paths = {
        path
        for path in set(current_hashes) | set(previous_hashes)
        if current_hashes.get(path) != previous_hashes.get(path)
    }
    return any(_is_boundary_path(path) for path in changed_paths)


def _is_boundary_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    name = path.name.lower()
    return (
        name in {"openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.yml"}
        or name in {"deployment.yaml", "deployment.yml"}
        or "deploy" in path.parts
        or "topic" in name
        or "kafka" in name
        or "parent" in name
    )


def _clone_for_new_snapshot(
    candidates: tuple[ValidatedCandidateFact, ...],
) -> tuple[ValidatedCandidateFact, ...]:
    cloned: list[ValidatedCandidateFact] = []
    for item in candidates:
        metadata = dict(item.candidate.metadata)
        metadata.pop("node_id", None)
        metadata.pop("edge_id", None)
        metadata["reused"] = True
        cloned.append(
            ValidatedCandidateFact(
                candidate=item.candidate.model_copy(update={"metadata": metadata}),
                validation_record=item.validation_record,
            )
        )
    return tuple(cloned)


def _change_metadata(
    current: AnalysisUnitFingerprint,
    previous_result: ReusableAnalysisUnitResult | None,
) -> dict[str, object]:
    if previous_result is None:
        return {}
    previous = previous_result.fingerprint
    current_hashes = dict(current.file_hashes)
    previous_hashes = dict(previous.file_hashes)
    changed_paths = sorted(
        path
        for path in set(current_hashes) | set(previous_hashes)
        if current_hashes.get(path) != previous_hashes.get(path)
    )
    return {
        "changed_paths": changed_paths,
        "dependency_hints_changed": current.dependency_hints != previous.dependency_hints,
        "parent_changed": current.parent_stable_key != previous.parent_stable_key,
        "prompt_version_changed": current.prompt_version != previous.prompt_version,
        "schema_version_changed": current.schema_version != previous.schema_version,
        "ontology_version_changed": current.ontology_version != previous.ontology_version,
        "validation_policy_version_changed": (
            current.validation_policy_version != previous.validation_policy_version
        ),
    }
