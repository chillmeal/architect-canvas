from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.contracts.graph import (
    CandidateFact,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    ValidationIssue,
    ValidationRecord,
)
from app.domain.enums import EntityOrigin, ValidationState
from app.infrastructure.db.repositories import GraphSnapshotRepository, PublishedGraphSnapshot
from app.validation import GraphLevelValidator, GraphValidationInput, GraphValidationOutcome

PUBLISHABLE_STATES = frozenset(
    {
        ValidationState.CONFIRMED,
        ValidationState.CONFIRMED_WITH_WARNINGS,
    }
)


@dataclass(frozen=True)
class ValidatedCandidateFact:
    candidate: CandidateFact
    validation_record: ValidationRecord


@dataclass(frozen=True)
class GraphAssemblyInput:
    snapshot_id: str
    project_id: str
    audit_id: str
    repository_state_id: str
    candidates: tuple[ValidatedCandidateFact, ...]
    issues: tuple[ValidationIssue, ...] = ()
    schema_version: str = "0.1.0"


@dataclass(frozen=True)
class GraphAssemblyResult:
    snapshot: GraphSnapshot
    validation: GraphValidationOutcome
    debug_candidates: tuple[ValidatedCandidateFact, ...]


class GraphAssemblyError(RuntimeError):
    def __init__(self, validation: GraphValidationOutcome) -> None:
        self.validation = validation
        super().__init__("Graph snapshot failed graph-level validation")


class GraphAssembler:
    def __init__(
        self,
        *,
        validator: GraphLevelValidator | None = None,
    ) -> None:
        self._validator = validator or GraphLevelValidator()

    def assemble(self, assembly_input: GraphAssemblyInput) -> GraphAssemblyResult:
        publishable_candidates = tuple(
            item
            for item in assembly_input.candidates
            if item.validation_record.final_state in PUBLISHABLE_STATES
        )
        debug_candidates = tuple(
            item
            for item in assembly_input.candidates
            if item.validation_record.final_state not in PUBLISHABLE_STATES
        )
        nodes = tuple(
            _candidate_to_node(item)
            for item in publishable_candidates
            if item.candidate.fact_kind == "NODE"
        )
        node_id_by_stable_key = {node.stable_key: node.node_id for node in nodes}
        edges = tuple(
            _candidate_to_edge(item, node_id_by_stable_key)
            for item in publishable_candidates
            if item.candidate.fact_kind == "EDGE"
        )
        snapshot = GraphSnapshot(
            schema_version=assembly_input.schema_version,
            snapshot_id=assembly_input.snapshot_id,
            project_id=assembly_input.project_id,
            audit_id=assembly_input.audit_id,
            repository_state_id=assembly_input.repository_state_id,
            nodes=tuple(sorted(nodes, key=lambda node: node.stable_key)),
            edges=tuple(sorted(edges, key=lambda edge: edge.edge_id)),
            issues=assembly_input.issues,
        )
        validation = self._validator.validate(GraphValidationInput(snapshot=snapshot))
        return GraphAssemblyResult(
            snapshot=snapshot,
            validation=validation,
            debug_candidates=debug_candidates,
        )

    def assemble_and_publish(
        self,
        *,
        assembly_input: GraphAssemblyInput,
        repository: GraphSnapshotRepository,
    ) -> PublishedGraphSnapshot:
        result = self.assemble(assembly_input)
        if not result.validation.auto_publish_allowed:
            raise GraphAssemblyError(result.validation)
        return repository.publish_snapshot(result.snapshot)


def _candidate_to_node(candidate: ValidatedCandidateFact) -> GraphNode:
    fact = candidate.candidate
    stable_key = fact.metadata.get("stable_key")
    if not isinstance(stable_key, str) or not stable_key:
        stable_key = fact.source_stable_key or fact.name or fact.fact_id
    return GraphNode(
        node_id=_entity_id("node", fact),
        stable_key=stable_key,
        node_type=fact.node_type,
        name=fact.name or fact.node_type.value,
        origin=EntityOrigin.INFERRED,
        validation_state=candidate.validation_record.final_state,
        confidence=candidate.validation_record.confidence,
        evidence=fact.evidence,
        validation_record=candidate.validation_record,
        metadata=fact.metadata,
    )


def _candidate_to_edge(
    candidate: ValidatedCandidateFact,
    node_id_by_stable_key: dict[str, str],
) -> GraphEdge:
    fact = candidate.candidate
    return GraphEdge(
        edge_id=_entity_id("edge", fact),
        source_node_id=node_id_by_stable_key.get(fact.source_stable_key, fact.source_stable_key),
        target_node_id=node_id_by_stable_key.get(fact.target_stable_key, fact.target_stable_key),
        edge_type=fact.edge_type,
        origin=EntityOrigin.INFERRED,
        validation_state=candidate.validation_record.final_state,
        confidence=candidate.validation_record.confidence,
        evidence=fact.evidence,
        validation_record=candidate.validation_record,
        metadata=fact.metadata,
    )


def _entity_id(prefix: str, fact: CandidateFact) -> str:
    value = fact.metadata.get(f"{prefix}_id")
    if isinstance(value, str) and value:
        return value
    return f"{prefix}-{uuid4()}"
