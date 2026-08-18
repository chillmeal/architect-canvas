from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from app.contracts.graph import CandidateFact
from app.domain.enums import NodeType
from app.domain.value_objects import (
    StableLogicalKey,
    StableLogicalKeyError,
    StableLogicalKeySource,
    normalize_key_part,
)


@dataclass(frozen=True)
class CandidateNormalizationIssue:
    fact_id: str
    message: str


@dataclass(frozen=True)
class CandidateNormalizationResult:
    candidates: tuple[CandidateFact, ...]
    issues: tuple[CandidateNormalizationIssue, ...]


class CandidateNormalizer:
    def normalize(
        self,
        *,
        project_id: str,
        candidates: tuple[CandidateFact, ...],
    ) -> CandidateNormalizationResult:
        normalized: list[CandidateFact] = []
        issues: list[CandidateNormalizationIssue] = []
        for candidate in candidates:
            try:
                normalized.append(_normalize_candidate(project_id=project_id, candidate=candidate))
            except StableLogicalKeyError as exc:
                issues.append(CandidateNormalizationIssue(fact_id=candidate.fact_id, message=str(exc)))
                normalized.append(_normalize_candidate_without_stable_key(candidate))
        return CandidateNormalizationResult(candidates=tuple(normalized), issues=tuple(issues))


def _normalize_candidate(*, project_id: str, candidate: CandidateFact) -> CandidateFact:
    base = _normalize_candidate_without_stable_key(candidate)
    if base.fact_kind != "NODE":
        return base
    node_type = base.node_type or NodeType.UNKNOWN
    stable_key = StableLogicalKey.from_source(
        StableLogicalKeySource(
            project_id=project_id,
            node_type=node_type,
            owner_path=_metadata_tuple(base.metadata, "owner_path"),
            name=base.name or node_type.value,
            artifact_id=_metadata_string(base.metadata, "artifact_id"),
            package_name=_metadata_string(base.metadata, "package_name"),
            deployment_name=_metadata_string(base.metadata, "deployment_name"),
            repository_path=_metadata_string(base.metadata, "repository_path"),
        )
    ).value
    metadata = {**base.metadata, "stable_key": stable_key}
    return base.model_copy(update={"metadata": metadata})


def _normalize_candidate_without_stable_key(candidate: CandidateFact) -> CandidateFact:
    metadata = _normalize_metadata(candidate.metadata)
    normalized_name = _normalize_display_text(candidate.name) if candidate.name is not None else None
    if normalized_name is not None:
        metadata["normalized_name"] = normalize_key_part(normalized_name)
    aliases = _metadata_tuple(metadata, "aliases")
    if aliases:
        metadata["normalized_aliases"] = tuple(sorted({normalize_key_part(alias) for alias in aliases if alias}))
    return candidate.model_copy(update={"name": normalized_name, "metadata": metadata})


def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(metadata)
    for key in ("artifact_id", "package_name", "deployment_name", "repository_path"):
        value = _metadata_string(normalized, key)
        if value is not None:
            normalized[key] = _normalize_display_text(value)
            normalized[f"normalized_{key}"] = normalize_key_part(value)
    if "owner_path" in normalized:
        normalized["owner_path"] = _metadata_tuple(normalized, "owner_path")
    return normalized


def _normalize_display_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = _normalize_display_text(value)
    return normalized or None


def _metadata_tuple(metadata: dict[str, Any], key: str) -> tuple[str, ...]:
    value = metadata.get(key)
    if value is None:
        return ()
    if isinstance(value, str):
        return (_normalize_display_text(value),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(
            normalized
            for item in value
            if isinstance(item, str) and (normalized := _normalize_display_text(item))
        )
    return ()
