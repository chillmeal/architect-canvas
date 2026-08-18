from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.contracts.graph import CandidateFact, Evidence, ValidationIssue
from app.domain.enums import ReasonCode, ValidationState


@dataclass(frozen=True)
class CandidateDeduplicationResult:
    candidates: tuple[CandidateFact, ...]
    issues: tuple[ValidationIssue, ...]


class CandidateDeduplicator:
    def deduplicate(self, candidates: tuple[CandidateFact, ...]) -> CandidateDeduplicationResult:
        merged_by_key: dict[tuple[str, ...], CandidateFact] = {}
        issues: list[ValidationIssue] = []
        identity_index: dict[tuple[str, str], CandidateFact] = {}
        ambiguous_fact_ids: set[str] = set()

        for candidate in candidates:
            exact_key = _exact_key(candidate)
            existing = merged_by_key.get(exact_key)
            if existing is not None:
                merged_by_key[exact_key] = _merge_candidates(existing, candidate)
                continue

            identity_key = _identity_key(candidate)
            if identity_key is not None:
                identity_existing = identity_index.get(identity_key)
                if identity_existing is not None and _exact_key(identity_existing) != exact_key:
                    issues.append(_duplicate_candidate_issue(identity_existing, candidate))
                    ambiguous_fact_ids.update({identity_existing.fact_id, candidate.fact_id})
                else:
                    identity_index[identity_key] = candidate
            merged_by_key[exact_key] = candidate

        candidates_without_ambiguous = tuple(
            candidate
            for candidate in merged_by_key.values()
            if candidate.fact_id not in ambiguous_fact_ids
        )
        return CandidateDeduplicationResult(
            candidates=tuple(sorted(candidates_without_ambiguous, key=lambda item: item.fact_id)),
            issues=tuple(issues),
        )


def _merge_candidates(left: CandidateFact, right: CandidateFact) -> CandidateFact:
    evidence = _merge_evidence(left.evidence, right.evidence)
    metadata = {**left.metadata, **right.metadata}
    metadata["merged_fact_ids"] = tuple(
        sorted({left.fact_id, right.fact_id, *metadata.get("merged_fact_ids", ())})
    )
    return left.model_copy(update={"evidence": evidence, "metadata": metadata})


def _merge_evidence(left: tuple[Evidence, ...], right: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    by_id = {item.evidence_id: item for item in left}
    for item in right:
        by_id.setdefault(item.evidence_id, item)
    return tuple(by_id[key] for key in sorted(by_id))


def _exact_key(candidate: CandidateFact) -> tuple[str, ...]:
    if candidate.fact_kind == "NODE":
        return (
            "NODE",
            candidate.metadata.get("stable_key") or "",
            candidate.node_type.value if candidate.node_type else "",
            candidate.metadata.get("normalized_name") or candidate.name or "",
        )
    return (
        "EDGE",
        candidate.edge_type.value if candidate.edge_type else "",
        candidate.source_stable_key or "",
        candidate.target_stable_key or "",
    )


def _identity_key(candidate: CandidateFact) -> tuple[str, str] | None:
    if candidate.fact_kind != "NODE":
        return None
    for key in ("normalized_artifact_id", "normalized_deployment_name", "normalized_package_name"):
        value = candidate.metadata.get(key)
        if isinstance(value, str) and value:
            return key, value
    aliases = candidate.metadata.get("normalized_aliases")
    if isinstance(aliases, tuple) and aliases:
        return "alias", aliases[0]
    return None


def _duplicate_candidate_issue(left: CandidateFact, right: CandidateFact) -> ValidationIssue:
    return ValidationIssue(
        issue_id=str(uuid4()),
        reason_code=ReasonCode.DUPLICATE_CANDIDATE,
        state=ValidationState.REVIEW_REQUIRED,
        message="Ambiguous duplicate candidate requires review",
        related_fact_ids=(left.fact_id, right.fact_id),
        metadata={
            "left_node_type": left.node_type.value if left.node_type else None,
            "right_node_type": right.node_type.value if right.node_type else None,
        },
    )
