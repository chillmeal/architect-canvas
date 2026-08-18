from pathlib import Path

import pytest

from app.contracts.graph import CandidateFact, Evidence, ValidationResult
from app.domain.enums import (
    EdgeType,
    EvidenceSourceType,
    EvidenceStrength,
    LlmValidatorDecision,
    ReasonCode,
    ValidationState,
)
from app.infrastructure.llm import FakeLlmProvider, FakeStructuredResponse
from app.validation import IndependentLlmValidator, LlmValidationResponse


@pytest.mark.anyio
async def test_independent_llm_validator_supported_decision(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload=LlmValidationResponse(
                decision=LlmValidatorDecision.SUPPORTED,
                message="Evidence supports the edge.",
            )
        )
    )

    outcome = await IndependentLlmValidator(
        provider=provider,
        repository_root=repository,
    ).validate(make_edge_fact(), deterministic_results=())

    assert outcome.llm_called is True
    assert outcome.result.state == ValidationState.CONFIRMED
    assert outcome.result.metadata["decision"] == LlmValidatorDecision.SUPPORTED.value
    assert outcome.issue is None
    prompt = provider.requests[0].messages[1].content
    assert "fresh runtime call" in prompt
    assert "chain_of_thought" not in prompt
    assert "confidence" not in prompt
    assert "full analyzer response" not in prompt


@pytest.mark.anyio
async def test_independent_llm_validator_contradicted_decision(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "decision": LlmValidatorDecision.CONTRADICTED.value,
                "message": "Evidence contradicts the edge.",
            }
        )
    )

    outcome = await IndependentLlmValidator(
        provider=provider,
        repository_root=repository,
    ).validate(make_edge_fact(), deterministic_results=())

    assert outcome.result.state == ValidationState.REJECTED
    assert outcome.result.reason_codes == (ReasonCode.LLM_VALIDATOR_CONTRADICTED,)
    assert outcome.issue is not None
    assert outcome.issue.reason_code == ReasonCode.LLM_VALIDATOR_CONTRADICTED


@pytest.mark.anyio
async def test_independent_llm_validator_insufficient_evidence_decision(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path)
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "decision": LlmValidatorDecision.INSUFFICIENT_EVIDENCE.value,
                "message": "Evidence is too weak.",
            }
        )
    )

    outcome = await IndependentLlmValidator(
        provider=provider,
        repository_root=repository,
    ).validate(make_edge_fact(), deterministic_results=())

    assert outcome.result.state == ValidationState.REVIEW_REQUIRED
    assert outcome.result.reason_codes == (ReasonCode.LLM_VALIDATOR_INSUFFICIENT_EVIDENCE,)


@pytest.mark.anyio
async def test_independent_llm_validator_skips_hard_deterministic_rejection(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path)
    provider = FakeLlmProvider()

    outcome = await IndependentLlmValidator(
        provider=provider,
        repository_root=repository,
    ).validate(
        make_edge_fact(),
        deterministic_results=(
            ValidationResult(
                validator_name="deterministic_semantic",
                state=ValidationState.REJECTED,
                reason_codes=(ReasonCode.SOURCE_TARGET_MISSING,),
                message="missing target",
            ),
        ),
    )

    assert outcome.llm_called is False
    assert outcome.result.state == ValidationState.REJECTED
    assert outcome.result.reason_codes == (ReasonCode.SOURCE_TARGET_MISSING,)
    assert provider.requests == []


def make_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    source = repository / "src"
    source.mkdir(parents=True)
    (source / "main.py").write_text(
        "orders_client.call('fresh runtime call')\n",
        encoding="utf-8",
    )
    return repository


def make_edge_fact() -> CandidateFact:
    return CandidateFact(
        fact_id="fact-1",
        fact_kind="EDGE",
        candidate_schema_version="0.1.0",
        edge_type=EdgeType.SYNC_CALL,
        source_stable_key="project/MICROSERVICE/payments",
        target_stable_key="project/MICROSERVICE/orders",
        evidence=(
            Evidence(
                evidence_id="evidence-1",
                relative_path="src/main.py",
                file_hash="sha256:abc",
                line_start=1,
                line_end=1,
                source_fragment_marker="stale marker from analyzer",
                source_type=EvidenceSourceType.SOURCE_CODE,
                strength=EvidenceStrength.STRONG,
                analysis_unit_id="unit-1",
            ),
        ),
        metadata={
            "chain_of_thought": "do not send",
            "analyzer_confidence": 0.99,
            "full_analyzer_response": "do not send",
        },
    )
