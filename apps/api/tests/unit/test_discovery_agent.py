import pytest

from app.analysis.agents.discovery import DiscoveryAgent, DiscoveryAgentOutput
from app.analysis.context_builder import AnalysisUnitContext, PromptManifest
from app.contracts.graph import CandidateFact, Evidence
from app.domain.enums import EvidenceSourceType, EvidenceStrength, NodeType
from app.infrastructure.llm import (
    FakeLlmProvider,
    FakeStructuredResponse,
    LlmMessage,
    LlmProviderError,
    LlmProviderErrorCode,
)


@pytest.mark.anyio
async def test_discovery_agent_returns_schema_valid_candidates() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload=DiscoveryAgentOutput(candidates=(make_candidate_fact(),)),
            input_tokens=10,
            output_tokens=5,
        )
    )

    result = await DiscoveryAgent(provider=provider, model="fake-model").discover(make_context())

    assert [candidate.fact_id for candidate in result.candidates] == ["fact-1"]
    assert result.unresolved_questions == ()
    assert result.metadata["candidate_count"] == 1
    assert result.metadata["provider"] == "fake"
    assert provider.requests[0].schema_name == "DiscoveryAgentOutput"
    assert provider.requests[0].prompt_version == "0.1.0"
    assert provider.requests[0].model == "fake-model"


@pytest.mark.anyio
async def test_discovery_agent_allows_unresolved_question_without_candidate() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "candidates": [],
                "unresolved_questions": [
                    {
                        "question_id": "question-1",
                        "message": "No source evidence for component ownership",
                        "related_paths": ["README.md"],
                    }
                ],
            }
        )
    )

    result = await DiscoveryAgent(provider=provider).discover(make_context())

    assert result.candidates == ()
    assert result.unresolved_questions[0].question_id == "question-1"
    assert result.metadata["unresolved_question_count"] == 1


@pytest.mark.anyio
async def test_discovery_agent_rejects_schema_invalid_output() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(payload={"candidates": [{"fact_kind": "NODE"}]})
    )

    with pytest.raises(LlmProviderError) as exc_info:
        await DiscoveryAgent(provider=provider).discover(make_context())

    assert exc_info.value.code == LlmProviderErrorCode.INVALID_RESPONSE
    assert "validation_errors" in exc_info.value.details


def make_context() -> AnalysisUnitContext:
    return AnalysisUnitContext(
        unit_id="unit-root",
        prompt_manifest=PromptManifest(
            name="discovery",
            version="0.1.0",
            content_hash="prompt-hash",
        ),
        messages=(
            LlmMessage(role="system", content="Return JSON."),
            LlmMessage(role="user", content="Find candidates."),
        ),
        selected_fragments=(),
        omitted_fragments=(),
        selected_tokens=0,
        omitted_tokens=0,
        metadata={"analysis_unit_id": "unit-root", "prompt_hash": "prompt-hash"},
    )


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
        analysis_unit_id="unit-root",
    )
