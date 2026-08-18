from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.graph import CandidateFact, ValidationIssue, ValidationResult
from app.domain.enums import LlmValidatorDecision, ReasonCode, ValidationState
from app.infrastructure.llm import (
    CancellationToken,
    LlmMessage,
    LlmProvider,
    StructuredGenerationRequest,
)
from app.infrastructure.repository.file_reader import SafeFileReader


class LlmValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: LlmValidatorDecision
    reason_codes: tuple[ReasonCode, ...] = ()
    message: str = Field(min_length=1)


@dataclass(frozen=True)
class IndependentLlmValidationOutcome:
    result: ValidationResult
    issue: ValidationIssue | None = None
    llm_called: bool = False


class IndependentLlmValidator:
    validator_name = "independent_llm"

    def __init__(
        self,
        *,
        provider: LlmProvider,
        repository_root: str | Path,
        model: str | None = None,
        prompt_version: str = "independent-llm-validator-v0.1",
    ) -> None:
        self.provider = provider
        self.reader = SafeFileReader(repository_root)
        self.model = model
        self.prompt_version = prompt_version

    async def validate(
        self,
        fact: CandidateFact,
        *,
        deterministic_results: tuple[ValidationResult, ...],
        cancellation_token: CancellationToken | None = None,
    ) -> IndependentLlmValidationOutcome:
        hard_rejection = _first_rejected_result(deterministic_results)
        if hard_rejection is not None:
            return self._skipped(hard_rejection)
        fragments = self._fresh_fragments(fact)
        request = StructuredGenerationRequest(
            messages=(
                LlmMessage(
                    role="system",
                    content=(
                        "You are an independent architecture evidence validator. "
                        "Decide only from the provided fact and fresh source fragments. "
                        "Do not infer from analyzer confidence or prior analyzer output."
                    ),
                ),
                LlmMessage(role="user", content=_validation_prompt(fact, fragments)),
            ),
            schema_name="LlmValidationResponse",
            json_schema=LlmValidationResponse.model_json_schema(),
            model=self.model,
            temperature=0.0,
            prompt_version=self.prompt_version,
        )
        response = await self.provider.generate_structured(
            request,
            LlmValidationResponse,
            cancellation_token=cancellation_token,
        )
        return self._from_decision(response.value)

    def _fresh_fragments(self, fact: CandidateFact) -> tuple[str, ...]:
        fragments: list[str] = []
        for evidence in fact.evidence:
            content = self.reader.read_text(evidence.relative_path)
            lines = content.splitlines()
            fragment = "\n".join(lines[evidence.line_start - 1 : evidence.line_end])
            fragments.append(
                "\n".join(
                    (
                        f"Evidence: {evidence.evidence_id}",
                        f"Path: {evidence.relative_path}",
                        f"Lines: {evidence.line_start}-{evidence.line_end}",
                        fragment,
                    )
                )
            )
        return tuple(fragments)

    def _from_decision(
        self,
        decision: LlmValidationResponse,
    ) -> IndependentLlmValidationOutcome:
        state = _state_for_decision(decision.decision)
        reason_codes = _reason_codes_for_decision(decision)
        result = ValidationResult(
            validator_name=self.validator_name,
            state=state,
            reason_codes=reason_codes,
            message=decision.message,
            metadata={"decision": decision.decision.value},
        )
        issue = None
        if state != ValidationState.CONFIRMED:
            reason_code = reason_codes[0] if reason_codes else ReasonCode.REVIEW_REQUIRED
            issue = ValidationIssue(
                issue_id=str(uuid4()),
                reason_code=reason_code,
                state=state,
                message=decision.message,
                metadata={"decision": decision.decision.value},
            )
        return IndependentLlmValidationOutcome(result=result, issue=issue, llm_called=True)

    def _skipped(self, deterministic_result: ValidationResult) -> IndependentLlmValidationOutcome:
        reason_codes = deterministic_result.reason_codes or (ReasonCode.HARD_INVARIANT_VIOLATION,)
        return IndependentLlmValidationOutcome(
            result=ValidationResult(
                validator_name=self.validator_name,
                state=ValidationState.REJECTED,
                reason_codes=reason_codes,
                message="skipped independent LLM validation after deterministic rejection",
                metadata={"skipped": True},
            ),
            issue=ValidationIssue(
                issue_id=str(uuid4()),
                reason_code=reason_codes[0],
                state=ValidationState.REJECTED,
                message="skipped independent LLM validation after deterministic rejection",
                metadata={"skipped": True},
            ),
            llm_called=False,
        )


def _first_rejected_result(
    deterministic_results: tuple[ValidationResult, ...],
) -> ValidationResult | None:
    for result in deterministic_results:
        if result.state == ValidationState.REJECTED:
            return result
    return None


def _validation_prompt(fact: CandidateFact, fragments: tuple[str, ...]) -> str:
    fact_lines = [
        f"fact_id: {fact.fact_id}",
        f"fact_kind: {fact.fact_kind}",
        f"node_type: {fact.node_type.value if fact.node_type else ''}",
        f"edge_type: {fact.edge_type.value if fact.edge_type else ''}",
        f"name: {fact.name or ''}",
        f"source_stable_key: {fact.source_stable_key or ''}",
        f"target_stable_key: {fact.target_stable_key or ''}",
    ]
    return "\n".join(
        (
            "Validate this candidate fact.",
            "Allowed decisions: SUPPORTED, CONTRADICTED, INSUFFICIENT_EVIDENCE, AMBIGUOUS, INVALID_SEMANTICS.",
            "\n".join(fact_lines),
            "Fresh evidence fragments:",
            "\n\n".join(fragments),
        )
    )


def _state_for_decision(decision: LlmValidatorDecision) -> ValidationState:
    if decision == LlmValidatorDecision.SUPPORTED:
        return ValidationState.CONFIRMED
    if decision in {
        LlmValidatorDecision.INSUFFICIENT_EVIDENCE,
        LlmValidatorDecision.AMBIGUOUS,
    }:
        return ValidationState.REVIEW_REQUIRED
    return ValidationState.REJECTED


def _reason_codes_for_decision(response: LlmValidationResponse) -> tuple[ReasonCode, ...]:
    if response.reason_codes:
        return response.reason_codes
    if response.decision == LlmValidatorDecision.CONTRADICTED:
        return (ReasonCode.LLM_VALIDATOR_CONTRADICTED,)
    if response.decision == LlmValidatorDecision.INSUFFICIENT_EVIDENCE:
        return (ReasonCode.LLM_VALIDATOR_INSUFFICIENT_EVIDENCE,)
    if response.decision == LlmValidatorDecision.AMBIGUOUS:
        return (ReasonCode.LLM_VALIDATOR_AMBIGUOUS,)
    if response.decision == LlmValidatorDecision.INVALID_SEMANTICS:
        return (ReasonCode.LLM_VALIDATOR_INVALID_SEMANTICS,)
    return ()
