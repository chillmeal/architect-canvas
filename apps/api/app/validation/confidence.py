from __future__ import annotations

from dataclasses import dataclass

from app.core.config import AppConfig
from app.domain.enums import (
    EvidenceStrength,
    LlmValidatorDecision,
    ReasonCode,
    ValidationState,
)

DEFAULT_CONFIDENCE_POLICY_VERSION = "confidence-policy-v0.1"

HARD_REJECTION_REASONS = frozenset(
    {
        ReasonCode.HARD_INVARIANT_VIOLATION,
        ReasonCode.INVALID_PARENT_TYPE,
        ReasonCode.INVALID_EDGE_DIRECTION,
        ReasonCode.CONTAINMENT_CYCLE,
        ReasonCode.DUPLICATE_EDGE,
        ReasonCode.SOURCE_TARGET_MISSING,
    }
)

EVIDENCE_REJECTION_REASONS = frozenset(
    {
        ReasonCode.EVIDENCE_MISSING,
        ReasonCode.EVIDENCE_INVALID,
    }
)


@dataclass(frozen=True)
class ConfidenceThresholds:
    confirmed_min: float = 0.85
    warnings_min: float = 0.70
    review_min: float = 0.40

    @classmethod
    def from_config(cls, config: AppConfig) -> ConfidenceThresholds:
        return cls(
            confirmed_min=config.confidence_confirmed_min,
            warnings_min=config.confidence_warnings_min,
            review_min=config.confidence_review_min,
        )

    def __post_init__(self) -> None:
        if not 0.0 <= self.review_min < self.warnings_min < self.confirmed_min <= 1.0:
            raise ValueError(
                "confidence thresholds must satisfy 0 <= review < warnings < confirmed <= 1"
            )


@dataclass(frozen=True)
class ConfidencePolicyInput:
    evidence_strengths: tuple[EvidenceStrength, ...]
    reason_codes: tuple[ReasonCode, ...] = ()
    deterministic_state: ValidationState | None = None
    llm_validator_decision: LlmValidatorDecision | None = None
    has_direct_strong_source_signal: bool = False
    independent_medium_source_signals: int = 0
    has_analyzer_support: bool = True
    conflict_count: int = 0
    stable_from_previous_audit: bool = False


@dataclass(frozen=True)
class ConfidencePolicyResult:
    final_state: ValidationState
    confidence: float
    reason_codes: tuple[ReasonCode, ...]
    policy_version: str


class ConfidencePolicy:
    def __init__(
        self,
        thresholds: ConfidenceThresholds | None = None,
        *,
        policy_version: str = DEFAULT_CONFIDENCE_POLICY_VERSION,
    ) -> None:
        self.thresholds = thresholds or ConfidenceThresholds()
        self.policy_version = policy_version

    def decide(self, policy_input: ConfidencePolicyInput) -> ConfidencePolicyResult:
        reason_codes = tuple(dict.fromkeys(policy_input.reason_codes))

        if ReasonCode.STALE_SOURCE in reason_codes:
            return self._result(ValidationState.STALE, 0.0, reason_codes)

        if HARD_REJECTION_REASONS.intersection(reason_codes):
            return self._result(ValidationState.REJECTED, 0.0, reason_codes)

        if EVIDENCE_REJECTION_REASONS.intersection(reason_codes) or not policy_input.evidence_strengths:
            return self._result(
                ValidationState.REJECTED,
                0.0,
                self._append_reason(reason_codes, ReasonCode.EVIDENCE_MISSING),
            )

        if policy_input.deterministic_state == ValidationState.REJECTED:
            return self._result(ValidationState.REJECTED, 0.0, reason_codes)

        if ReasonCode.NAMING_SIMILARITY_ONLY in reason_codes:
            return self._result(ValidationState.REJECTED, self._below_review(), reason_codes)

        if policy_input.llm_validator_decision == LlmValidatorDecision.CONTRADICTED:
            return self._result(
                ValidationState.REJECTED,
                self._below_review(),
                self._append_reason(reason_codes, ReasonCode.LLM_VALIDATOR_CONTRADICTED),
            )

        if policy_input.llm_validator_decision == LlmValidatorDecision.INVALID_SEMANTICS:
            return self._result(
                ValidationState.REJECTED,
                self._below_review(),
                self._append_reason(reason_codes, ReasonCode.LLM_VALIDATOR_INVALID_SEMANTICS),
            )

        if policy_input.llm_validator_decision == LlmValidatorDecision.INSUFFICIENT_EVIDENCE:
            return self._review_result(
                self._append_reason(
                    reason_codes,
                    ReasonCode.LLM_VALIDATOR_INSUFFICIENT_EVIDENCE,
                )
            )

        if policy_input.llm_validator_decision == LlmValidatorDecision.AMBIGUOUS:
            return self._review_result(
                self._append_reason(reason_codes, ReasonCode.LLM_VALIDATOR_AMBIGUOUS)
            )

        if policy_input.independent_medium_source_signals == 1:
            return self._review_result(
                self._append_reason(reason_codes, ReasonCode.INSUFFICIENT_SOURCE_SIGNALS)
            )

        if policy_input.llm_validator_decision != LlmValidatorDecision.SUPPORTED:
            return self._review_result(
                self._append_reason(reason_codes, ReasonCode.REVIEW_REQUIRED)
            )

        if policy_input.has_direct_strong_source_signal:
            return self._result(
                ValidationState.CONFIRMED,
                self._score_confirmed(policy_input),
                reason_codes,
            )

        if policy_input.independent_medium_source_signals >= 2:
            return self._result(
                ValidationState.CONFIRMED_WITH_WARNINGS,
                self._score_warnings(policy_input),
                reason_codes,
            )

        return self._review_result(
            self._append_reason(reason_codes, ReasonCode.INSUFFICIENT_SOURCE_SIGNALS)
        )

    def _review_result(self, reason_codes: tuple[ReasonCode, ...]) -> ConfidencePolicyResult:
        return self._result(ValidationState.REVIEW_REQUIRED, self.thresholds.review_min, reason_codes)

    def _result(
        self,
        state: ValidationState,
        confidence: float,
        reason_codes: tuple[ReasonCode, ...],
    ) -> ConfidencePolicyResult:
        return ConfidencePolicyResult(
            final_state=state,
            confidence=round(min(max(confidence, 0.0), 1.0), 3),
            reason_codes=reason_codes,
            policy_version=self.policy_version,
        )

    def _score_confirmed(self, policy_input: ConfidencePolicyInput) -> float:
        score = self.thresholds.confirmed_min
        if EvidenceStrength.STRONG in policy_input.evidence_strengths:
            score += 0.05
        if policy_input.stable_from_previous_audit:
            score += 0.03
        if policy_input.conflict_count:
            score -= min(policy_input.conflict_count * 0.05, 0.15)
        return score

    def _score_warnings(self, policy_input: ConfidencePolicyInput) -> float:
        score = self.thresholds.warnings_min
        if EvidenceStrength.STRONG in policy_input.evidence_strengths:
            score += 0.04
        if policy_input.stable_from_previous_audit:
            score += 0.02
        if policy_input.conflict_count:
            score -= min(policy_input.conflict_count * 0.04, 0.12)
        return min(score, self.thresholds.confirmed_min - 0.01)

    def _below_review(self) -> float:
        return max(0.0, self.thresholds.review_min - 0.01)

    @staticmethod
    def _append_reason(
        reason_codes: tuple[ReasonCode, ...],
        reason_code: ReasonCode,
    ) -> tuple[ReasonCode, ...]:
        if reason_code in reason_codes:
            return reason_codes
        return (*reason_codes, reason_code)
