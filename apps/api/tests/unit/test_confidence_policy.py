from dataclasses import fields

import pytest

from app.domain.enums import EvidenceStrength, LlmValidatorDecision, ReasonCode, ValidationState
from app.validation.confidence import (
    ConfidencePolicy,
    ConfidencePolicyInput,
    ConfidenceThresholds,
)


def test_policy_input_does_not_accept_model_confidence() -> None:
    assert "model_confidence" not in {field.name for field in fields(ConfidencePolicyInput)}


def test_hard_domain_invariant_has_priority_over_llm_support() -> None:
    result = ConfidencePolicy().decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.STRONG,),
            reason_codes=(ReasonCode.HARD_INVARIANT_VIOLATION,),
            llm_validator_decision=LlmValidatorDecision.SUPPORTED,
            has_direct_strong_source_signal=True,
        )
    )

    assert result.final_state is ValidationState.REJECTED
    assert result.confidence == 0.0


def test_stale_source_has_priority_over_analyzer_and_validator_agreement() -> None:
    result = ConfidencePolicy().decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.STRONG,),
            reason_codes=(ReasonCode.STALE_SOURCE,),
            llm_validator_decision=LlmValidatorDecision.SUPPORTED,
            has_direct_strong_source_signal=True,
        )
    )

    assert result.final_state is ValidationState.STALE
    assert result.confidence == 0.0


def test_missing_evidence_rejects_even_when_llm_supports() -> None:
    result = ConfidencePolicy().decide(
        ConfidencePolicyInput(
            evidence_strengths=(),
            llm_validator_decision=LlmValidatorDecision.SUPPORTED,
            has_direct_strong_source_signal=True,
        )
    )

    assert result.final_state is ValidationState.REJECTED
    assert ReasonCode.EVIDENCE_MISSING in result.reason_codes


def test_llm_validator_contradiction_rejects_supported_analyzer_fact() -> None:
    result = ConfidencePolicy().decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.STRONG,),
            llm_validator_decision=LlmValidatorDecision.CONTRADICTED,
            has_direct_strong_source_signal=True,
            has_analyzer_support=True,
        )
    )

    assert result.final_state is ValidationState.REJECTED
    assert result.confidence < ConfidenceThresholds().review_min
    assert ReasonCode.LLM_VALIDATOR_CONTRADICTED in result.reason_codes


def test_llm_validator_insufficient_evidence_requires_review() -> None:
    result = ConfidencePolicy().decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.STRONG,),
            llm_validator_decision=LlmValidatorDecision.INSUFFICIENT_EVIDENCE,
            has_direct_strong_source_signal=True,
        )
    )

    assert result.final_state is ValidationState.REVIEW_REQUIRED
    assert result.confidence == ConfidenceThresholds().review_min
    assert ReasonCode.LLM_VALIDATOR_INSUFFICIENT_EVIDENCE in result.reason_codes


def test_one_direct_source_signal_and_validator_support_confirms() -> None:
    result = ConfidencePolicy().decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.STRONG,),
            llm_validator_decision=LlmValidatorDecision.SUPPORTED,
            has_direct_strong_source_signal=True,
        )
    )

    assert result.final_state is ValidationState.CONFIRMED
    assert result.confidence >= ConfidenceThresholds().confirmed_min


def test_two_medium_source_signals_and_validator_support_confirm_with_warnings() -> None:
    thresholds = ConfidenceThresholds()
    result = ConfidencePolicy(thresholds).decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.MEDIUM, EvidenceStrength.MEDIUM),
            llm_validator_decision=LlmValidatorDecision.SUPPORTED,
            independent_medium_source_signals=2,
        )
    )

    assert result.final_state is ValidationState.CONFIRMED_WITH_WARNINGS
    assert thresholds.warnings_min <= result.confidence < thresholds.confirmed_min


def test_one_medium_source_signal_requires_review() -> None:
    result = ConfidencePolicy().decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.MEDIUM,),
            llm_validator_decision=LlmValidatorDecision.SUPPORTED,
            independent_medium_source_signals=1,
        )
    )

    assert result.final_state is ValidationState.REVIEW_REQUIRED
    assert ReasonCode.INSUFFICIENT_SOURCE_SIGNALS in result.reason_codes


def test_naming_similarity_only_is_rejected() -> None:
    result = ConfidencePolicy().decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.WEAK,),
            reason_codes=(ReasonCode.NAMING_SIMILARITY_ONLY,),
            llm_validator_decision=LlmValidatorDecision.SUPPORTED,
        )
    )

    assert result.final_state is ValidationState.REJECTED
    assert result.confidence < ConfidenceThresholds().review_min


def test_thresholds_are_configurable_and_validated() -> None:
    policy = ConfidencePolicy(ConfidenceThresholds(confirmed_min=0.9, warnings_min=0.8, review_min=0.5))

    result = policy.decide(
        ConfidencePolicyInput(
            evidence_strengths=(EvidenceStrength.STRONG,),
            llm_validator_decision=LlmValidatorDecision.SUPPORTED,
            has_direct_strong_source_signal=True,
        )
    )

    assert result.confidence >= 0.9
    with pytest.raises(ValueError, match="confidence thresholds"):
        ConfidenceThresholds(confirmed_min=0.7, warnings_min=0.8, review_min=0.5)
