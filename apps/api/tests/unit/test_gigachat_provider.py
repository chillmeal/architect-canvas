import json
from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from app.contracts.graph import CandidateFact, Evidence
from app.core.config import AppConfig, ConfigError
from app.domain.enums import EvidenceSourceType, EvidenceStrength, NodeType
from app.infrastructure.llm import (
    GigaChatProvider,
    HttpRequest,
    HttpResponse,
    LlmMessage,
    LlmProviderError,
    LlmProviderErrorCode,
    StructuredGenerationRequest,
)


@pytest.mark.anyio
async def test_gigachat_provider_caches_access_token_until_refresh_window() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token-1", "expires_at": 2_000}),
            json_response({"data": [{"id": "GigaChat", "owned_by": "sber"}]}),
            json_response({"data": [{"id": "GigaChat", "owned_by": "sber"}]}),
            json_response({"access_token": "token-2", "expires_at": 2_200}),
            json_response({"data": [{"id": "GigaChat-Pro"}]}),
        ]
    )
    clock = MutableClock(1_000)
    provider = make_provider(transport=transport, clock=clock)

    first = await provider.list_models()
    second = await provider.list_models()
    clock.value = 1_950
    third = await provider.list_models()

    assert [model.model_id for model in first] == ["GigaChat"]
    assert [model.model_id for model in second] == ["GigaChat"]
    assert [model.model_id for model in third] == ["GigaChat-Pro"]
    assert [request.url for request in transport.requests] == [
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        "https://api.giga.chat/v1/models",
        "https://api.giga.chat/v1/models",
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        "https://api.giga.chat/v1/models",
    ]
    assert transport.requests[1].headers["Authorization"] == "Bearer token-1"
    assert transport.requests[4].headers["Authorization"] == "Bearer token-2"


@pytest.mark.anyio
async def test_gigachat_provider_accepts_millisecond_expiry_timestamp() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token", "expires_at": 2_000_000_000_000}),
            json_response({"data": [{"id": "GigaChat"}]}),
            json_response({"data": [{"id": "GigaChat"}]}),
        ]
    )
    provider = make_provider(transport=transport, clock=MutableClock(1_000_000_000))

    await provider.list_models()
    await provider.list_models()

    assert len([request for request in transport.requests if request.url.endswith("/oauth")]) == 1


@pytest.mark.anyio
async def test_gigachat_provider_refreshes_token_once_after_401() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "expired", "expires_at": 2_000}),
            json_response({"error": "unauthorized"}, status_code=401),
            json_response({"access_token": "fresh", "expires_at": 2_000}),
            json_response({"data": [{"id": "GigaChat"}]}),
        ]
    )
    provider = make_provider(transport=transport)

    models = await provider.list_models()

    assert [model.model_id for model in models] == ["GigaChat"]
    assert transport.requests[1].headers["Authorization"] == "Bearer expired"
    assert transport.requests[3].headers["Authorization"] == "Bearer fresh"


@pytest.mark.anyio
async def test_gigachat_provider_fails_after_second_401() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "expired", "expires_at": 2_000}),
            json_response({"error": "unauthorized"}, status_code=401),
            json_response({"access_token": "fresh", "expires_at": 2_000}),
            json_response({"error": "unauthorized"}, status_code=401),
        ]
    )
    provider = make_provider(transport=transport)

    with pytest.raises(LlmProviderError) as exc_info:
        await provider.list_models()

    assert exc_info.value.code == LlmProviderErrorCode.UNAUTHORIZED
    assert exc_info.value.retryable is True
    assert len([request for request in transport.requests if request.url.endswith("/oauth")]) == 2


@pytest.mark.anyio
async def test_gigachat_provider_health_check_uses_models_endpoint() -> None:
    healthy_transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token", "expires_at": 2_000}),
            json_response({"data": [{"id": "GigaChat"}, {"id": "GigaChat-Pro"}]}),
        ]
    )
    provider = make_provider(transport=healthy_transport)

    health = await provider.health_check()

    assert health.ok is True
    assert health.models_available == 2

    unhealthy = make_provider(
        transport=FakeHttpTransport(
            responses=[
                json_response({"access_token": "token", "expires_at": 2_000}),
                json_response({"error": "forbidden"}, status_code=403),
            ]
        )
    )

    failed_health = await unhealthy.health_check()

    assert failed_health.ok is False
    assert failed_health.models_available == 0
    assert "FORBIDDEN" in (failed_health.message or "")


@pytest.mark.anyio
async def test_gigachat_provider_exposes_model_type_as_capability() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token", "expires_at": 2_000}),
            json_response({"data": [{"id": "GigaChat-Pro", "type": "chat"}]}),
        ]
    )
    provider = make_provider(transport=transport)

    models = await provider.list_models()

    assert models[0].capabilities == ("chat",)


@pytest.mark.anyio
async def test_gigachat_token_count_sends_input_array_and_parses_list_response() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token", "expires_at": 2_000}),
            HttpResponse(
                status_code=200,
                body=json.dumps([{"tokens": 7, "characters": 18}]).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            ),
        ]
    )
    provider = make_provider(transport=transport)

    result = await provider.count_tokens(
        (LlmMessage(role="user", content="hello architecture"),),
        model="GigaChat-Pro",
    )

    assert result.tokens == 7
    request_body = json.loads(transport.requests[1].body or b"{}")
    assert request_body == {"input": ["hello architecture"], "model": "GigaChat-Pro"}


def test_gigachat_provider_requires_explicit_local_debug_for_insecure_tls() -> None:
    with pytest.raises(ConfigError, match="local debug opt-in"):
        GigaChatProvider.from_config(
            AppConfig.from_environment(
                {
                    "APP_ENV": "local",
                    "GIGACHAT_CREDENTIALS": "secret",
                    "GIGACHAT_VERIFY_SSL_CERTS": "false",
                }
            ),
            transport=FakeHttpTransport(),
        )

    provider = GigaChatProvider.from_config(
        AppConfig.from_environment(
            {
                "APP_ENV": "local",
                "GIGACHAT_CREDENTIALS": "secret",
                "GIGACHAT_VERIFY_SSL_CERTS": "false",
                "GIGACHAT_ALLOW_INSECURE_TLS_LOCAL_DEBUG": "true",
            }
        ),
        transport=FakeHttpTransport(),
    )

    assert provider.verify_ssl_certs is False


@pytest.mark.anyio
async def test_gigachat_provider_errors_do_not_include_credentials() -> None:
    transport = FakeHttpTransport(responses=[json_response({"error": "bad"}, status_code=400)])
    provider = make_provider(transport=transport, credentials="super-secret")

    with pytest.raises(LlmProviderError) as exc_info:
        await provider.list_models()

    assert "super-secret" not in str(exc_info.value)
    assert transport.requests[0].headers["Authorization"] == "Basic super-secret"


@pytest.mark.anyio
async def test_gigachat_structured_call_sends_strict_json_schema_payload() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token", "expires_at": 2_000}),
            chat_response(make_candidate_fact().model_dump(mode="json")),
        ]
    )
    provider = make_provider(transport=transport)

    result = await provider.generate_structured(make_structured_request(), CandidateFact)

    assert result.value.fact_id == "fact-1"
    assert result.finish_reason == "stop"
    assert result.usage.total_tokens == 15
    request_body = json.loads(transport.requests[1].body or b"{}")
    assert request_body["messages"][0]["role"] == "system"
    assert request_body["response_format"]["type"] == "json_schema"
    assert request_body["response_format"]["strict"] is True
    assert request_body["response_format"]["schema"]["title"] == "CandidateFact"


@pytest.mark.anyio
async def test_gigachat_structured_call_requires_system_message_first() -> None:
    provider = make_provider(transport=FakeHttpTransport())
    request = StructuredGenerationRequest(
        messages=(LlmMessage(role="user", content="No system"),),
        schema_name="CandidateFact",
        json_schema=CandidateFact.model_json_schema(),
    )

    with pytest.raises(LlmProviderError) as exc_info:
        await provider.generate_structured(request, CandidateFact)

    assert exc_info.value.code == LlmProviderErrorCode.BAD_REQUEST


@pytest.mark.anyio
async def test_gigachat_structured_call_repairs_invalid_json_once() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token", "expires_at": 2_000}),
            raw_chat_response("{not-json"),
            chat_response(make_candidate_fact(fact_id="fact-repaired").model_dump(mode="json")),
        ]
    )
    provider = make_provider(transport=transport)

    result = await provider.generate_structured(make_structured_request(), CandidateFact)

    assert result.value.fact_id == "fact-repaired"
    assert len([request for request in transport.requests if request.url.endswith("/chat/completions")]) == 2
    repair_body = json.loads(transport.requests[2].body or b"{}")
    assert repair_body["messages"][0]["role"] == "system"
    assert "Previous response" in repair_body["messages"][-1]["content"]


@pytest.mark.anyio
async def test_gigachat_structured_call_fails_after_schema_repair_failure() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token", "expires_at": 2_000}),
            chat_response({"fact_kind": "NODE"}),
            chat_response({"fact_kind": "NODE"}),
        ]
    )
    provider = make_provider(transport=transport)

    with pytest.raises(LlmProviderError) as exc_info:
        await provider.generate_structured(make_structured_request(), CandidateFact)

    assert exc_info.value.code == LlmProviderErrorCode.INVALID_RESPONSE
    assert exc_info.value.details["repair_attempted"] is True
    assert len([request for request in transport.requests if request.url.endswith("/chat/completions")]) == 2


@pytest.mark.anyio
async def test_gigachat_structured_call_rejects_truncated_without_repair() -> None:
    transport = FakeHttpTransport(
        responses=[
            json_response({"access_token": "token", "expires_at": 2_000}),
            chat_response(make_candidate_fact().model_dump(mode="json"), finish_reason="length"),
        ]
    )
    provider = make_provider(transport=transport)

    with pytest.raises(LlmProviderError) as exc_info:
        await provider.generate_structured(make_structured_request(), CandidateFact)

    assert exc_info.value.code == LlmProviderErrorCode.INVALID_RESPONSE
    assert exc_info.value.details["finish_reason"] == "length"
    assert len([request for request in transport.requests if request.url.endswith("/chat/completions")]) == 1


@dataclass
class MutableClock:
    value: float

    def __call__(self) -> float:
        return self.value


@dataclass
class FakeHttpTransport:
    responses: list[HttpResponse] = field(default_factory=list)
    requests: list[HttpRequest] = field(default_factory=list)

    async def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(f"Unexpected HTTP request: {request.method} {request.url}")
        return self.responses.pop(0)


def make_provider(
    *,
    transport: FakeHttpTransport,
    clock=None,
    credentials: str = "credentials",
) -> GigaChatProvider:
    return GigaChatProvider(
        credentials=SecretStr(credentials),
        scope="GIGACHAT_API_CORP",
        base_url="https://api.giga.chat/v1",
        auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        timeout_seconds=30,
        verify_ssl_certs=True,
        transport=transport,
        clock=clock or MutableClock(1_000),
    )


def json_response(payload: dict[str, object], *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def chat_response(payload: dict[str, object], *, finish_reason: str = "stop") -> HttpResponse:
    return raw_chat_response(json.dumps(payload), finish_reason=finish_reason)


def raw_chat_response(content: str, *, finish_reason: str = "stop") -> HttpResponse:
    return json_response(
        {
            "id": "chat-1",
            "model": "GigaChat",
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )


def make_structured_request() -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        messages=(
            LlmMessage(role="system", content="Return JSON."),
            LlmMessage(role="user", content="Find facts."),
        ),
        schema_name="CandidateFact",
        json_schema=CandidateFact.model_json_schema(),
        model="GigaChat",
    )


def make_candidate_fact(*, fact_id: str = "fact-1") -> CandidateFact:
    return CandidateFact(
        fact_id=fact_id,
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
