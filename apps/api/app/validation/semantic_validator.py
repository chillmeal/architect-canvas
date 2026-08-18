from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.contracts.graph import CandidateFact, ValidationIssue, ValidationResult
from app.domain.enums import EdgeType, EvidenceSourceType, NodeType, ReasonCode, ValidationState


@dataclass(frozen=True)
class SemanticEdgeKey:
    source_stable_key: str
    target_stable_key: str
    edge_type: EdgeType


@dataclass(frozen=True)
class SemanticValidationContext:
    node_types_by_stable_key: dict[str, NodeType]
    existing_edges: tuple[SemanticEdgeKey, ...] = ()
    evidence_fragments_by_id: dict[str, str] | None = None


@dataclass(frozen=True)
class SemanticValidationOutcome:
    result: ValidationResult
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.result.state in {
            ValidationState.CONFIRMED,
            ValidationState.CONFIRMED_WITH_WARNINGS,
        }


class DeterministicSemanticValidator:
    validator_name = "deterministic_semantic"

    def validate(
        self,
        fact: CandidateFact,
        context: SemanticValidationContext,
    ) -> SemanticValidationOutcome:
        if not fact.evidence:
            return self._reject("candidate fact has no evidence", ReasonCode.EVIDENCE_MISSING)
        if fact.fact_kind == "NODE":
            return self._validate_node(fact, context)
        return self._validate_edge(fact, context)

    def _validate_node(
        self,
        fact: CandidateFact,
        context: SemanticValidationContext,
    ) -> SemanticValidationOutcome:
        evidence_text = _combined_evidence_text(fact, context)
        name = (fact.name or "").lower()
        if fact.node_type == NodeType.TOPIC:
            return self._direct_signal_or_review(
                name in evidence_text and _has_any(evidence_text, ("topic", "kafka", "binding")),
                "Kafka topic is present in evidence",
                "Kafka topic is not present in producer or consumer evidence",
            )
        if fact.node_type == NodeType.DATABASE:
            return self._direct_signal_or_review(
                _has_any(evidence_text, ("datasource", "jdbc:", "postgres", "mysql", "mongodb", "redis")),
                "Datasource is present in evidence",
                "Datasource or database driver is not present in evidence",
            )
        if fact.node_type == NodeType.API_ENDPOINT:
            has_contract = any(
                evidence.source_type == EvidenceSourceType.API_CONTRACT for evidence in fact.evidence
            )
            return self._direct_signal_or_review(
                has_contract and name in evidence_text,
                "OpenAPI operation is present in evidence",
                "OpenAPI operation is not present in evidence",
            )
        if fact.node_type in {NodeType.MICROSERVICE, NodeType.APPLICATION_COMPONENT}:
            has_deployment = any(
                evidence.source_type == EvidenceSourceType.DEPLOYMENT for evidence in fact.evidence
            )
            return self._direct_signal_or_review(
                name in evidence_text and (has_deployment or "deployment" in evidence_text),
                "Deployment name is present in evidence",
                "Deployment name is not present in evidence",
            )
        return self._confirm("No hard deterministic semantic violation")

    def _validate_edge(
        self,
        fact: CandidateFact,
        context: SemanticValidationContext,
    ) -> SemanticValidationOutcome:
        assert fact.edge_type is not None
        assert fact.source_stable_key is not None
        assert fact.target_stable_key is not None
        source_type = context.node_types_by_stable_key.get(fact.source_stable_key)
        target_type = context.node_types_by_stable_key.get(fact.target_stable_key)
        if source_type is None or target_type is None:
            return self._reject(
                "edge source or target does not exist",
                ReasonCode.SOURCE_TARGET_MISSING,
            )
        if SemanticEdgeKey(
            source_stable_key=fact.source_stable_key,
            target_stable_key=fact.target_stable_key,
            edge_type=fact.edge_type,
        ) in context.existing_edges:
            return self._reject("duplicate edge", ReasonCode.DUPLICATE_EDGE)
        if fact.edge_type == EdgeType.CONTAINS:
            return self._validate_contains_edge(source_type, target_type)
        if fact.edge_type == EdgeType.SYNC_CALL:
            return self._validate_runtime_call(fact, context)
        if fact.edge_type in {EdgeType.ASYNC_PUBLISH, EdgeType.ASYNC_SUBSCRIBE}:
            return self._validate_kafka_edge(fact, context)
        if fact.edge_type in {EdgeType.DATA_READ, EdgeType.DATA_WRITE}:
            return self._validate_data_edge(fact, context)
        return self._confirm("No hard deterministic semantic violation")

    def _validate_contains_edge(
        self,
        source_type: NodeType,
        target_type: NodeType,
    ) -> SemanticValidationOutcome:
        if source_type not in CONTAINER_NODE_TYPES:
            return self._reject("CONTAINS source cannot be a child-only node", ReasonCode.INVALID_PARENT_TYPE)
        if target_type in {NodeType.AUTOMATED_SYSTEM, NodeType.FUNCTIONAL_SUBSYSTEM}:
            return self._reject("CONTAINS direction is invalid", ReasonCode.INVALID_EDGE_DIRECTION)
        if _containment_rank(source_type) >= _containment_rank(target_type):
            return self._reject("CONTAINS parent must be higher-level than child", ReasonCode.INVALID_EDGE_DIRECTION)
        return self._confirm("Parent type and direction are valid")

    def _validate_runtime_call(
        self,
        fact: CandidateFact,
        context: SemanticValidationContext,
    ) -> SemanticValidationOutcome:
        evidence_text = _combined_evidence_text(fact, context)
        if _has_any(evidence_text, ("http://", "https://", "feign", "resttemplate", "webclient", "openapi")):
            return self._confirm("Runtime call signal is present in evidence")
        if all(evidence.source_type == EvidenceSourceType.MANIFEST for evidence in fact.evidence):
            return self._review("Build dependency alone is not runtime call evidence")
        return self._review("Runtime URL or client name is not present in evidence")

    def _validate_kafka_edge(
        self,
        fact: CandidateFact,
        context: SemanticValidationContext,
    ) -> SemanticValidationOutcome:
        evidence_text = _combined_evidence_text(fact, context)
        if _has_any(evidence_text, ("topic", "kafka", "producer", "consumer", "binding")):
            return self._confirm("Kafka topic signal is present in evidence")
        return self._review("Kafka topic is not present in producer or consumer evidence")

    def _validate_data_edge(
        self,
        fact: CandidateFact,
        context: SemanticValidationContext,
    ) -> SemanticValidationOutcome:
        evidence_text = _combined_evidence_text(fact, context)
        if _has_any(evidence_text, ("datasource", "jdbc:", "repository", "sql", "mongodb", "redis")):
            return self._confirm("Datasource signal is present in evidence")
        return self._review("Datasource signal is not present in evidence")

    def _direct_signal_or_review(
        self,
        condition: bool,
        confirmed_message: str,
        review_message: str,
    ) -> SemanticValidationOutcome:
        if condition:
            return self._confirm(confirmed_message)
        return self._review(review_message)

    def _confirm(self, message: str) -> SemanticValidationOutcome:
        return SemanticValidationOutcome(
            result=ValidationResult(
                validator_name=self.validator_name,
                state=ValidationState.CONFIRMED,
                reason_codes=(),
                message=message,
            )
        )

    def _review(self, message: str) -> SemanticValidationOutcome:
        return SemanticValidationOutcome(
            result=ValidationResult(
                validator_name=self.validator_name,
                state=ValidationState.REVIEW_REQUIRED,
                reason_codes=(ReasonCode.INSUFFICIENT_SOURCE_SIGNALS,),
                message=message,
            ),
            issues=(
                ValidationIssue(
                    issue_id=str(uuid4()),
                    reason_code=ReasonCode.INSUFFICIENT_SOURCE_SIGNALS,
                    state=ValidationState.REVIEW_REQUIRED,
                    message=message,
                ),
            ),
        )

    def _reject(self, message: str, reason_code: ReasonCode) -> SemanticValidationOutcome:
        return SemanticValidationOutcome(
            result=ValidationResult(
                validator_name=self.validator_name,
                state=ValidationState.REJECTED,
                reason_codes=(reason_code,),
                message=message,
            ),
            issues=(
                ValidationIssue(
                    issue_id=str(uuid4()),
                    reason_code=reason_code,
                    state=ValidationState.REJECTED,
                    message=message,
                ),
            ),
        )


CONTAINER_NODE_TYPES = frozenset(
    {
        NodeType.AUTOMATED_SYSTEM,
        NodeType.FUNCTIONAL_SUBSYSTEM,
        NodeType.MODULE,
        NodeType.SUBMODULE,
    }
)

CONTAINMENT_RANK = {
    NodeType.AUTOMATED_SYSTEM: 0,
    NodeType.FUNCTIONAL_SUBSYSTEM: 1,
    NodeType.MODULE: 2,
    NodeType.SUBMODULE: 3,
    NodeType.MICROSERVICE: 4,
    NodeType.APPLICATION_COMPONENT: 4,
    NodeType.INFRA_COMPONENT: 4,
    NodeType.MESSAGE_BROKER: 4,
    NodeType.TOPIC: 5,
    NodeType.DATABASE: 5,
    NodeType.API_ENDPOINT: 5,
    NodeType.EXTERNAL_SYSTEM: 5,
    NodeType.UNKNOWN: 99,
}


def _combined_evidence_text(
    fact: CandidateFact,
    context: SemanticValidationContext,
) -> str:
    fragments_by_id = context.evidence_fragments_by_id or {}
    texts = []
    for evidence in fact.evidence:
        texts.append(fragments_by_id.get(evidence.evidence_id, evidence.source_fragment_marker or ""))
    return "\n".join(texts).lower()


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _containment_rank(node_type: NodeType) -> int:
    return CONTAINMENT_RANK.get(node_type, 99)
