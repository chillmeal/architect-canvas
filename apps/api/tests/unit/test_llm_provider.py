import pytest

from app.contracts.graph import CandidateFact, Evidence
from app.domain.enums import EvidenceSourceType, EvidenceStrength, NodeType
from app.infrastructure.llm import (
    CancellationToken,
    FakeLlmProvider,
    FakeStructuredResponse,
    LlmCancelledError,
    LlmMessage,
    LlmProviderError,
    LlmProviderErrorCode,
    StructuredGenerationRequest,
    map_http_status_to_provider_error,
)


@pytest.mark.anyio
async def test_fake_provider_returns_contract_type_and_usage_metadata() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload=make_candidate_fact().model_dump(mode="json"),
            input_tokens=11,
            output_tokens=7,
            provider_metadata={"request_id": "fake-1"},
        )
    )

    result = await provider.generate_structured(
        make_request(),
        CandidateFact,
    )

    assert isinstance(result.value, CandidateFact)
    assert result.value.node_type == NodeType.MICROSERVICE
    assert result.model == "fake-model"
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert result.usage.total_tokens == 18
    assert result.provider_metadata == {"request_id": "fake-1"}
    assert provider.requests[0].schema_name == "CandidateFact"


@pytest.mark.anyio
async def test_fake_provider_supports_count_models_and_health() -> None:
    provider = FakeLlmProvider()

    token_count = await provider.count_tokens(
        (LlmMessage(role="user", content="01234567"),),
        model="fake-model",
    )
    models = await provider.list_models()
    health = await provider.health_check()

    assert token_count.tokens == 2
    assert token_count.model == "fake-model"
    assert models[0].model_id == "fake-model"
    assert health.ok is True
    assert health.models_available == 1


@pytest.mark.anyio
async def test_fake_provider_honors_cancellation() -> None:
    token = CancellationToken()
    token.cancel()

    with pytest.raises(LlmCancelledError) as exc_info:
        await FakeLlmProvider().generate_structured(
            make_request(),
            CandidateFact,
            cancellation_token=token,
        )

    assert exc_info.value.code == LlmProviderErrorCode.CANCELLED
    assert exc_info.value.retryable is False


@pytest.mark.anyio
async def test_fake_provider_maps_invalid_payload_to_provider_error() -> None:
    provider = FakeLlmProvider()
    provider.enqueue_structured_response(FakeStructuredResponse(payload={"fact_kind": "NODE"}))

    with pytest.raises(LlmProviderError) as exc_info:
        await provider.generate_structured(make_request(), CandidateFact)

    assert exc_info.value.code == LlmProviderErrorCode.INVALID_RESPONSE
    assert exc_info.value.retryable is False
    assert "validation_errors" in exc_info.value.details


def test_provider_http_error_mapping_contract() -> None:
    expected = {
        400: (LlmProviderErrorCode.BAD_REQUEST, False),
        401: (LlmProviderErrorCode.UNAUTHORIZED, True),
        402: (LlmProviderErrorCode.QUOTA_EXCEEDED, False),
        403: (LlmProviderErrorCode.FORBIDDEN, False),
        413: (LlmProviderErrorCode.PAYLOAD_TOO_LARGE, True),
        422: (LlmProviderErrorCode.SCHEMA_REJECTED, False),
        429: (LlmProviderErrorCode.RATE_LIMITED, True),
        500: (LlmProviderErrorCode.SERVER_ERROR, True),
        503: (LlmProviderErrorCode.SERVER_ERROR, True),
    }

    for status_code, (code, retryable) in expected.items():
        error = map_http_status_to_provider_error(
            status_code=status_code,
            provider_name="gigachat",
            message="provider failed",
        )
        assert error.code == code
        assert error.retryable is retryable
        assert error.status_code == status_code
        assert error.provider_name == "gigachat"


def make_request() -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        messages=(
            LlmMessage(role="system", content="Return JSON."),
            LlmMessage(role="user", content="Find facts."),
        ),
        schema_name="CandidateFact",
        json_schema=CandidateFact.model_json_schema(),
        model="fake-model",
        prompt_version="test-v1",
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
        analysis_unit_id="unit-1",
    )
