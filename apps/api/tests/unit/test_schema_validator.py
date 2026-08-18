import json

from app.contracts.graph import CandidateFact, Evidence
from app.domain.enums import (
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ReasonCode,
    ValidationState,
)
from app.validation import StructuredOutputSchemaValidator


def test_schema_validator_accepts_valid_candidate_fact() -> None:
    payload = make_candidate_fact().model_dump(mode="json")

    outcome = StructuredOutputSchemaValidator().validate_candidate_fact(
        raw_content=json.dumps(payload),
        finish_reason="stop",
    )

    assert outcome.accepted is True
    assert outcome.candidate_fact is not None
    assert outcome.candidate_fact.fact_id == "fact-1"
    assert outcome.result.state == ValidationState.CONFIRMED
    assert outcome.issue is None


def test_schema_validator_rejects_invalid_json_without_regex_fallback() -> None:
    outcome = StructuredOutputSchemaValidator().validate_candidate_fact(
        raw_content='Here is the JSON: {"fact_id": "fact-1"}',
        finish_reason="stop",
    )

    assert outcome.accepted is False
    assert outcome.candidate_fact is None
    assert outcome.result.reason_codes == (ReasonCode.SCHEMA_INVALID,)
    assert outcome.issue is not None
    assert outcome.issue.reason_code == ReasonCode.SCHEMA_INVALID


def test_schema_validator_marks_failed_schema_after_repair_attempt() -> None:
    outcome = StructuredOutputSchemaValidator().validate_candidate_fact(
        raw_content="{not-json",
        finish_reason="stop",
        repair_attempted=True,
    )

    assert outcome.result.reason_codes == (ReasonCode.FAILED_SCHEMA,)
    assert outcome.issue is not None
    assert outcome.issue.reason_code == ReasonCode.FAILED_SCHEMA
    assert outcome.result.metadata["repair_attempted"] is True


def test_schema_validator_rejects_missing_required_fields() -> None:
    outcome = StructuredOutputSchemaValidator().validate_candidate_fact(
        raw_content=json.dumps({"fact_kind": "NODE"}),
        finish_reason="stop",
    )

    assert outcome.result.state == ValidationState.REJECTED
    assert outcome.result.reason_codes == (ReasonCode.SCHEMA_INVALID,)
    assert "validation_errors" in outcome.result.metadata


def test_schema_validator_rejects_unknown_enum_values() -> None:
    payload = make_candidate_fact().model_dump(mode="json")
    payload["node_type"] = "SERVICE_GUESS"

    outcome = StructuredOutputSchemaValidator().validate_candidate_fact(
        raw_content=json.dumps(payload),
        finish_reason="stop",
    )

    assert outcome.accepted is False
    assert outcome.result.reason_codes == (ReasonCode.SCHEMA_INVALID,)


def test_schema_validator_rejects_missing_evidence_refs() -> None:
    payload = make_candidate_fact().model_dump(mode="json")
    payload["evidence"] = []

    outcome = StructuredOutputSchemaValidator().validate_candidate_fact(
        raw_content=json.dumps(payload),
        finish_reason="stop",
    )

    assert outcome.accepted is False
    assert outcome.result.reason_codes == (ReasonCode.SCHEMA_INVALID,)


def test_schema_validator_rejects_truncated_finish_reason() -> None:
    outcome = StructuredOutputSchemaValidator().validate_candidate_fact(
        raw_content=json.dumps(make_candidate_fact().model_dump(mode="json")),
        finish_reason="length",
    )

    assert outcome.accepted is False
    assert outcome.result.reason_codes == (ReasonCode.FAILED_SCHEMA,)
    assert outcome.result.metadata["finish_reason"] == "length"


def test_schema_validator_rejects_blacklist_finish_reason() -> None:
    outcome = StructuredOutputSchemaValidator().validate_candidate_fact(
        raw_content=json.dumps(make_candidate_fact().model_dump(mode="json")),
        finish_reason="blacklist",
    )

    assert outcome.accepted is False
    assert outcome.result.reason_codes == (ReasonCode.FAILED_SCHEMA,)


def make_candidate_fact() -> CandidateFact:
    return CandidateFact(
        fact_id="fact-1",
        fact_kind="NODE",
        candidate_schema_version="0.1.0",
        node_type=NodeType.MICROSERVICE,
        name="payments",
        evidence=(make_evidence(),),
    )


def make_evidence() -> Evidence:
    return Evidence(
        evidence_id="evidence-1",
        relative_path="src/main.py",
        file_hash="sha256:abc",
        line_start=1,
        line_end=1,
        fragment_hash="sha256:def",
        source_type=EvidenceSourceType.SOURCE_CODE,
        strength=EvidenceStrength.STRONG,
        analysis_unit_id="unit-1",
    )
