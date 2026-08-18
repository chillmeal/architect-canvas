from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from pydantic import ValidationError

from app.contracts.graph import CandidateFact, ValidationIssue, ValidationResult
from app.domain.enums import ReasonCode, ValidationState

TRUNCATED_FINISH_REASONS = frozenset({"length", "token_limit"})
BLACKLIST_FINISH_REASONS = frozenset({"blacklist", "content_filter", "content-filter"})


@dataclass(frozen=True)
class SchemaValidationOutcome:
    candidate_fact: CandidateFact | None
    result: ValidationResult
    issue: ValidationIssue | None = None

    @property
    def accepted(self) -> bool:
        return self.candidate_fact is not None and self.result.state == ValidationState.CONFIRMED


class StructuredOutputSchemaValidator:
    validator_name = "structured_output_schema"

    def validate_candidate_fact(
        self,
        *,
        raw_content: str,
        finish_reason: str | None,
        repair_attempted: bool = False,
    ) -> SchemaValidationOutcome:
        finish_issue = self._finish_reason_issue(finish_reason)
        if finish_issue is not None:
            return finish_issue
        try:
            payload = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            return self._reject(
                message="structured output is not valid JSON",
                reason_code=_schema_reason(repair_attempted),
                metadata={"error": exc.msg, "repair_attempted": repair_attempted},
            )
        try:
            candidate_fact = CandidateFact.model_validate(payload)
        except ValidationError as exc:
            return self._reject(
                message="structured output does not match CandidateFact schema",
                reason_code=_schema_reason(repair_attempted),
                metadata={
                    "validation_errors": exc.errors(include_input=False),
                    "repair_attempted": repair_attempted,
                },
            )
        return SchemaValidationOutcome(
            candidate_fact=candidate_fact,
            result=ValidationResult(
                validator_name=self.validator_name,
                state=ValidationState.CONFIRMED,
                reason_codes=(),
                message="structured output matches CandidateFact schema",
                metadata={"finish_reason": finish_reason},
            ),
        )

    def _finish_reason_issue(self, finish_reason: str | None) -> SchemaValidationOutcome | None:
        if finish_reason in TRUNCATED_FINISH_REASONS:
            return self._reject(
                message="structured output was truncated",
                reason_code=ReasonCode.FAILED_SCHEMA,
                metadata={"finish_reason": finish_reason},
            )
        if finish_reason in BLACKLIST_FINISH_REASONS:
            return self._reject(
                message="structured output was rejected by provider policy",
                reason_code=ReasonCode.FAILED_SCHEMA,
                metadata={"finish_reason": finish_reason},
            )
        return None

    def _reject(
        self,
        *,
        message: str,
        reason_code: ReasonCode,
        metadata: dict[str, object],
    ) -> SchemaValidationOutcome:
        result = ValidationResult(
            validator_name=self.validator_name,
            state=ValidationState.REJECTED,
            reason_codes=(reason_code,),
            message=message,
            metadata=metadata,
        )
        return SchemaValidationOutcome(
            candidate_fact=None,
            result=result,
            issue=ValidationIssue(
                issue_id=str(uuid4()),
                reason_code=reason_code,
                state=ValidationState.REJECTED,
                message=message,
                metadata=metadata,
            ),
        )


def _schema_reason(repair_attempted: bool) -> ReasonCode:
    return ReasonCode.FAILED_SCHEMA if repair_attempted else ReasonCode.SCHEMA_INVALID
