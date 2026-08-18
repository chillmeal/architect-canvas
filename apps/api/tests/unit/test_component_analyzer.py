import pytest

from app.analysis.agents.component_analyzer import ComponentAnalyzer, ComponentAnalyzerOutput
from app.analysis.context_builder import AnalysisUnitContext, PromptManifest
from app.contracts.graph import CandidateFact, Evidence
from app.domain.enums import EdgeType, EvidenceSourceType, EvidenceStrength, NodeType
from app.infrastructure.llm import (
    FakeLlmProvider,
    FakeStructuredResponse,
    LlmMessage,
    LlmProviderError,
    LlmProviderErrorCode,
)


@pytest.mark.anyio
async def test_component_analyzer_returns_structured_component_facts() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload=ComponentAnalyzerOutput(
                facts=(
                    make_node_fact(
                        fact_id="component-identity",
                        node_type=NodeType.MICROSERVICE,
                        name="payments-api",
                        metadata={"role": "component_identity", "model_confidence": 0.99},
                    ),
                    make_node_fact(
                        fact_id="api-provider",
                        node_type=NodeType.API_ENDPOINT,
                        name="GET /payments",
                        metadata={"role": "api_provider"},
                    ),
                    make_edge_fact(
                        fact_id="candidate-edge",
                        edge_type=EdgeType.SYNC_CALL,
                        source_stable_key="project/MICROSERVICE/payments-api",
                        target_stable_key="project/MICROSERVICE/accounts-api",
                        metadata={"role": "candidate_edge"},
                    ),
                )
            ),
            input_tokens=15,
            output_tokens=8,
        )
    )

    result = await ComponentAnalyzer(provider=provider, model="fake-analysis").analyze(make_context())

    assert [fact.fact_id for fact in result.facts] == [
        "component-identity",
        "api-provider",
        "candidate-edge",
    ]
    assert result.facts[0].metadata == {"role": "component_identity"}
    assert result.metadata["fact_count"] == 3
    assert result.metadata["provider"] == "fake"
    assert provider.requests[0].schema_name == "ComponentAnalyzerOutput"
    assert provider.requests[0].model == "fake-analysis"


@pytest.mark.anyio
async def test_component_analyzer_preserves_unknown_instead_of_guessing() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "facts": [
                    make_node_fact(
                        fact_id="unknown-component",
                        node_type=NodeType.UNKNOWN,
                        name="ambiguous-runtime",
                        metadata={"role": "component_identity"},
                    ).model_dump(mode="json"),
                    make_edge_fact(
                        fact_id="unknown-edge",
                        edge_type=EdgeType.UNKNOWN,
                        source_stable_key="project/UNKNOWN/ambiguous-runtime",
                        target_stable_key="project/MICROSERVICE/accounts-api",
                    ).model_dump(mode="json"),
                ]
            }
        )
    )

    result = await ComponentAnalyzer(provider=provider).analyze(make_context())

    assert result.facts[0].node_type == NodeType.UNKNOWN
    assert result.facts[1].edge_type == EdgeType.UNKNOWN


@pytest.mark.anyio
async def test_component_analyzer_rejects_missing_evidence() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "facts": [
                    {
                        "fact_id": "missing-evidence",
                        "fact_kind": "NODE",
                        "candidate_schema_version": "0.1.0",
                        "node_type": "MICROSERVICE",
                        "name": "payments",
                        "evidence": [],
                    }
                ]
            }
        )
    )

    with pytest.raises(LlmProviderError) as exc_info:
        await ComponentAnalyzer(provider=provider).analyze(make_context())

    assert exc_info.value.code == LlmProviderErrorCode.INVALID_RESPONSE
    assert "validation_errors" in exc_info.value.details


@pytest.mark.anyio
async def test_component_analyzer_allows_unresolved_question_without_fact() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "facts": [],
                "unresolved_questions": [
                    {
                        "question_id": "question-1",
                        "message": "Kafka topic name is configured externally",
                        "related_paths": ["application.yml"],
                    }
                ],
            }
        )
    )

    result = await ComponentAnalyzer(provider=provider).analyze(make_context())

    assert result.facts == ()
    assert result.unresolved_questions[0].question_id == "question-1"


def make_context() -> AnalysisUnitContext:
    return AnalysisUnitContext(
        unit_id="unit-payments",
        prompt_manifest=PromptManifest(
            name="component_analysis",
            version="0.1.0",
            content_hash="prompt-hash",
        ),
        messages=(
            LlmMessage(role="system", content="Return JSON."),
            LlmMessage(role="user", content="Analyze component."),
        ),
        selected_fragments=(),
        omitted_fragments=(),
        selected_tokens=0,
        omitted_tokens=0,
        metadata={"analysis_unit_id": "unit-payments", "prompt_hash": "prompt-hash"},
    )


def make_node_fact(
    *,
    fact_id: str,
    node_type: NodeType,
    name: str,
    metadata: dict[str, object] | None = None,
) -> CandidateFact:
    return CandidateFact(
        fact_id=fact_id,
        fact_kind="NODE",
        candidate_schema_version="0.1.0",
        node_type=node_type,
        name=name,
        evidence=(make_evidence(),),
        metadata=metadata or {},
    )


def make_edge_fact(
    *,
    fact_id: str,
    edge_type: EdgeType,
    source_stable_key: str,
    target_stable_key: str,
    metadata: dict[str, object] | None = None,
) -> CandidateFact:
    return CandidateFact(
        fact_id=fact_id,
        fact_kind="EDGE",
        candidate_schema_version="0.1.0",
        edge_type=edge_type,
        source_stable_key=source_stable_key,
        target_stable_key=target_stable_key,
        evidence=(make_evidence(),),
        metadata=metadata or {},
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
        analysis_unit_id="unit-payments",
    )
