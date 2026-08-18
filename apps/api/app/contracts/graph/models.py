from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    EdgeType,
    EntityOrigin,
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ReasonCode,
    ValidationState,
)


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class Evidence(ContractModel):
    evidence_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    file_hash: str = Field(min_length=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    fragment_hash: str | None = Field(default=None, min_length=1)
    source_fragment_marker: str | None = Field(default=None, min_length=1)
    source_type: EvidenceSourceType
    strength: EvidenceStrength
    analysis_unit_id: str = Field(min_length=1)
    llm_invocation_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_line_range_and_fragment_marker(self) -> Evidence:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        if not self.fragment_hash and not self.source_fragment_marker:
            raise ValueError("fragment_hash or source_fragment_marker is required")
        return self


class ValidationResult(ContractModel):
    validator_name: str = Field(min_length=1)
    state: ValidationState
    reason_codes: tuple[ReasonCode, ...] = ()
    message: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(ContractModel):
    issue_id: str = Field(min_length=1)
    reason_code: ReasonCode
    state: ValidationState = ValidationState.REVIEW_REQUIRED
    message: str = Field(min_length=1)
    related_fact_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationRecord(ContractModel):
    analyzer_invocation_id: str | None = Field(default=None, min_length=1)
    candidate_schema_version: str = Field(min_length=1)
    evidence: tuple[Evidence, ...]
    deterministic_results: tuple[ValidationResult, ...] = ()
    independent_validator_invocation_id: str | None = Field(default=None, min_length=1)
    validator_decision: str | None = Field(default=None, min_length=1)
    policy_version: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    final_state: ValidationState
    reason_codes: tuple[ReasonCode, ...] = ()
    validated_at: str = Field(min_length=1)


class CandidateFact(ContractModel):
    fact_id: str = Field(min_length=1)
    fact_kind: Literal["NODE", "EDGE"]
    candidate_schema_version: str = Field(min_length=1)
    node_type: NodeType | None = None
    edge_type: EdgeType | None = None
    name: str | None = Field(default=None, min_length=1)
    source_stable_key: str | None = Field(default=None, min_length=1)
    target_stable_key: str | None = Field(default=None, min_length=1)
    evidence: tuple[Evidence, ...]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fact_shape(self) -> CandidateFact:
        if self.fact_kind == "NODE" and not self.node_type:
            raise ValueError("node_type is required for NODE facts")
        if self.fact_kind == "EDGE":
            if not self.edge_type:
                raise ValueError("edge_type is required for EDGE facts")
            if not self.source_stable_key or not self.target_stable_key:
                raise ValueError("source_stable_key and target_stable_key are required for EDGE facts")
        if not self.evidence:
            raise ValueError("candidate fact evidence is required")
        return self


class GraphNode(ContractModel):
    node_id: str = Field(min_length=1)
    stable_key: str = Field(min_length=1)
    node_type: NodeType
    name: str = Field(min_length=1)
    origin: EntityOrigin
    validation_state: ValidationState
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[Evidence, ...] = ()
    validation_record: ValidationRecord | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_inferred_node_has_evidence(self) -> GraphNode:
        if self.origin == EntityOrigin.INFERRED and not self.evidence:
            raise ValueError("inferred node evidence is required")
        return self


class GraphEdge(ContractModel):
    edge_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    edge_type: EdgeType
    origin: EntityOrigin
    validation_state: ValidationState
    confidence: float = Field(ge=0.0, le=1.0)
    contract: str | None = Field(default=None, min_length=1)
    protocol: str | None = Field(default=None, min_length=1)
    evidence: tuple[Evidence, ...] = ()
    validation_record: ValidationRecord | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_inferred_edge_has_evidence(self) -> GraphEdge:
        if self.origin == EntityOrigin.INFERRED and not self.evidence:
            raise ValueError("inferred edge evidence is required")
        return self


class GraphSnapshot(ContractModel):
    schema_version: str = Field(default="0.1.0", min_length=1)
    snapshot_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    audit_id: str = Field(min_length=1)
    repository_state_id: str = Field(min_length=1)
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    issues: tuple[ValidationIssue, ...] = ()
