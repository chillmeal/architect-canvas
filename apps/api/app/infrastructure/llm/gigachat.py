from __future__ import annotations

import asyncio
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from pydantic import SecretStr, ValidationError

from app.core.config import AppConfig, ConfigError
from app.infrastructure.llm.provider import (
    CancellationToken,
    LlmHealthStatus,
    LlmMessage,
    LlmModelInfo,
    LlmProviderError,
    LlmProviderErrorCode,
    LlmUsage,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenCountResult,
    TResponse,
    invalid_response_error,
    map_http_status_to_provider_error,
)

TOKEN_REFRESH_SKEW_SECONDS = 60
TRUNCATED_FINISH_REASONS = frozenset({"length", "token_limit"})
BLACKLIST_FINISH_REASONS = frozenset({"blacklist", "content_filter", "content-filter"})


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None = None
    timeout_seconds: int = 120
    verify_ssl_certs: bool = True
    ca_bundle_file: str | None = None


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]


class AsyncHttpTransport(Protocol):
    async def send(self, request: HttpRequest) -> HttpResponse:
        pass


@dataclass(frozen=True)
class CachedAccessToken:
    token: str
    expires_at: float

    def valid_at(self, now: float) -> bool:
        return now < self.expires_at - TOKEN_REFRESH_SKEW_SECONDS


class UrllibAsyncHttpTransport:
    async def send(self, request: HttpRequest) -> HttpResponse:
        return await asyncio.to_thread(_send_with_urllib, request)


class GigaChatProvider:
    provider_name = "gigachat"

    def __init__(
        self,
        *,
        credentials: SecretStr,
        scope: str,
        base_url: str,
        auth_url: str,
        timeout_seconds: int,
        verify_ssl_certs: bool,
        ca_bundle_file: str | None = None,
        transport: AsyncHttpTransport | None = None,
        clock: Any = time.time,
    ) -> None:
        self.credentials = credentials
        self.scope = scope
        self.base_url = base_url.rstrip("/")
        self.auth_url = auth_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.verify_ssl_certs = verify_ssl_certs
        self.ca_bundle_file = ca_bundle_file
        self.transport = transport or UrllibAsyncHttpTransport()
        self.clock = clock
        self._access_token: CachedAccessToken | None = None

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        response_model: type[TResponse],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> StructuredGenerationResult[TResponse]:
        _validate_system_message_first(request)
        response = await self._chat_completion(
            request=request,
            cancellation_token=cancellation_token,
        )
        try:
            return _parse_structured_generation_response(
                response=response,
                response_model=response_model,
                provider_name=self.provider_name,
            )
        except LlmProviderError as first_error:
            if first_error.code != LlmProviderErrorCode.INVALID_RESPONSE:
                raise
            if first_error.details.get("finish_reason") is not None:
                raise
            repair_response = await self._chat_completion(
                request=_repair_request(request, response.body.decode("utf-8", errors="replace")),
                cancellation_token=cancellation_token,
            )
            try:
                return _parse_structured_generation_response(
                    response=repair_response,
                    response_model=response_model,
                    provider_name=self.provider_name,
                )
            except LlmProviderError as repair_error:
                repair_error.details.setdefault("repair_attempted", True)
                raise

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        *,
        transport: AsyncHttpTransport | None = None,
        clock: Any = time.time,
    ) -> GigaChatProvider:
        if config.gigachat_credentials is None:
            raise ConfigError(["GIGACHAT_CREDENTIALS is required"])
        if not config.gigachat_verify_ssl_certs and (
            config.app_env != "local" or not config.gigachat_allow_insecure_tls_local_debug
        ):
            raise ConfigError(["GIGACHAT_VERIFY_SSL_CERTS=false requires local debug opt-in"])
        return cls(
            credentials=config.gigachat_credentials,
            scope=config.gigachat_scope,
            base_url=config.gigachat_base_url,
            auth_url=config.gigachat_auth_url,
            timeout_seconds=config.gigachat_request_timeout_seconds,
            verify_ssl_certs=config.gigachat_verify_ssl_certs,
            ca_bundle_file=(
                str(config.gigachat_ca_bundle_file) if config.gigachat_ca_bundle_file else None
            ),
            transport=transport,
            clock=clock,
        )

    async def list_models(
        self,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[LlmModelInfo, ...]:
        response = await self._authorized_request(
            method="GET",
            path="/models",
            cancellation_token=cancellation_token,
        )
        payload = _decode_json_response(response, provider_name=self.provider_name)
        raw_models = payload.get("data", [])
        if not isinstance(raw_models, list):
            raise LlmProviderError(
                code=LlmProviderErrorCode.INVALID_RESPONSE,
                message="GigaChat models response has invalid shape",
                provider_name=self.provider_name,
            )
        models: list[LlmModelInfo] = []
        for raw_model in raw_models:
            if not isinstance(raw_model, dict) or not raw_model.get("id"):
                continue
            owned_by = raw_model.get("owned_by")
            model_type = raw_model.get("type")
            models.append(
                LlmModelInfo(
                    model_id=str(raw_model["id"]),
                    owned_by=str(owned_by) if owned_by is not None else None,
                    capabilities=(str(model_type),) if model_type is not None else (),
                )
            )
        return tuple(models)

    async def health_check(
        self,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LlmHealthStatus:
        try:
            models = await self.list_models(cancellation_token=cancellation_token)
        except LlmProviderError as exc:
            return LlmHealthStatus(
                ok=False,
                provider_name=self.provider_name,
                models_available=0,
                message=f"{exc.code.value}: {exc}",
            )
        return LlmHealthStatus(
            ok=True,
            provider_name=self.provider_name,
            models_available=len(models),
        )

    async def count_tokens(
        self,
        messages: tuple[LlmMessage, ...],
        *,
        model: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TokenCountResult:
        if cancellation_token is not None:
            cancellation_token.throw_if_cancelled(provider_name=self.provider_name)
        text = "\n".join(message.content for message in messages)
        payload: dict[str, Any] = {"input": [text]}
        if model is not None:
            payload["model"] = model
        body = json.dumps(payload).encode("utf-8")
        response = await self._authorized_request(
            method="POST",
            path="/tokens/count",
            body=body,
            headers={"Content-Type": "application/json"},
            cancellation_token=cancellation_token,
        )
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LlmProviderError(
                code=LlmProviderErrorCode.INVALID_RESPONSE,
                message="GigaChat token count response is not valid JSON",
                provider_name=self.provider_name,
            ) from exc
        if not isinstance(payload, list) or not payload:
            raise LlmProviderError(
                code=LlmProviderErrorCode.INVALID_RESPONSE,
                message="GigaChat token count response has invalid shape",
                provider_name=self.provider_name,
            )
        tokens = sum(
            item.get("tokens", 0)
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("tokens"), int)
        )
        if tokens <= 0:
            raise LlmProviderError(
                code=LlmProviderErrorCode.INVALID_RESPONSE,
                message="GigaChat token count response has no token counts",
                provider_name=self.provider_name,
            )
        return TokenCountResult(tokens=tokens, model=model)

    async def _chat_completion(
        self,
        *,
        request: StructuredGenerationRequest,
        cancellation_token: CancellationToken | None = None,
    ) -> HttpResponse:
        if cancellation_token is not None:
            cancellation_token.throw_if_cancelled(provider_name=self.provider_name)
        body = json.dumps(_structured_chat_payload(request)).encode("utf-8")
        return await self._authorized_request(
            method="POST",
            path="/chat/completions",
            body=body,
            headers={"Content-Type": "application/json"},
            cancellation_token=cancellation_token,
        )

    async def _authorized_request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> HttpResponse:
        token = await self._get_access_token(cancellation_token=cancellation_token)
        response = await self._send_api_request(
            method=method,
            path=path,
            token=token,
            body=body,
            headers=headers,
            cancellation_token=cancellation_token,
        )
        if response.status_code == 401:
            self._access_token = None
            token = await self._get_access_token(cancellation_token=cancellation_token)
            response = await self._send_api_request(
                method=method,
                path=path,
                token=token,
                body=body,
                headers=headers,
                cancellation_token=cancellation_token,
            )
        if response.status_code >= 400:
            raise map_http_status_to_provider_error(
                status_code=response.status_code,
                provider_name=self.provider_name,
                message=f"GigaChat request failed with HTTP {response.status_code}",
            )
        return response

    async def _get_access_token(
        self,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> str:
        if cancellation_token is not None:
            cancellation_token.throw_if_cancelled(provider_name=self.provider_name)
        now = float(self.clock())
        if self._access_token is not None and self._access_token.valid_at(now):
            return self._access_token.token
        token_response = await self._request_access_token(cancellation_token=cancellation_token)
        self._access_token = token_response
        return token_response.token

    async def _request_access_token(
        self,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> CachedAccessToken:
        if cancellation_token is not None:
            cancellation_token.throw_if_cancelled(provider_name=self.provider_name)
        body = urllib.parse.urlencode({"scope": self.scope}).encode("utf-8")
        response = await self.transport.send(
            HttpRequest(
                method="POST",
                url=self.auth_url,
                headers={
                    "Authorization": f"Basic {self.credentials.get_secret_value()}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "RqUID": str(uuid4()),
                },
                body=body,
                timeout_seconds=self.timeout_seconds,
                verify_ssl_certs=self.verify_ssl_certs,
                ca_bundle_file=self.ca_bundle_file,
            )
        )
        if response.status_code >= 400:
            raise map_http_status_to_provider_error(
                status_code=response.status_code,
                provider_name=self.provider_name,
                message=f"GigaChat OAuth failed with HTTP {response.status_code}",
            )
        payload = _decode_json_response(response, provider_name=self.provider_name)
        token = payload.get("access_token")
        expires_at = payload.get("expires_at")
        if not isinstance(token, str) or not isinstance(expires_at, int | float):
            raise LlmProviderError(
                code=LlmProviderErrorCode.INVALID_RESPONSE,
                message="GigaChat OAuth response has invalid shape",
                provider_name=self.provider_name,
            )
        return CachedAccessToken(token=token, expires_at=_normalize_expiry_timestamp(float(expires_at)))

    async def _send_api_request(
        self,
        *,
        method: str,
        path: str,
        token: str,
        body: bytes | None,
        headers: dict[str, str] | None,
        cancellation_token: CancellationToken | None = None,
    ) -> HttpResponse:
        if cancellation_token is not None:
            cancellation_token.throw_if_cancelled(provider_name=self.provider_name)
        request_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **(headers or {}),
        }
        response = await self.transport.send(
            HttpRequest(
                method=method,
                url=f"{self.base_url}{path}",
                headers=request_headers,
                body=body,
                timeout_seconds=self.timeout_seconds,
                verify_ssl_certs=self.verify_ssl_certs,
                ca_bundle_file=self.ca_bundle_file,
            )
        )
        if cancellation_token is not None:
            cancellation_token.throw_if_cancelled(provider_name=self.provider_name)
        return response


def _send_with_urllib(request: HttpRequest) -> HttpResponse:
    urllib_request = urllib.request.Request(
        request.url,
        data=request.body,
        headers=request.headers,
        method=request.method,
    )
    try:
        if not request.verify_ssl_certs:
            ssl_context = ssl._create_unverified_context()
        elif request.ca_bundle_file:
            ssl_context = ssl.create_default_context(cafile=request.ca_bundle_file)
        else:
            ssl_context = None
        with urllib.request.urlopen(
            urllib_request,
            timeout=request.timeout_seconds,
            context=ssl_context,
        ) as response:
            return HttpResponse(
                status_code=response.status,
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status_code=exc.code,
            body=exc.read(),
            headers=dict(exc.headers.items()),
        )


def _normalize_expiry_timestamp(expires_at: float) -> float:
    # GigaChat currently documents expires_at as Unix seconds. Older examples and
    # some gateways may return milliseconds, so accept both without refreshing on
    # every request. Values above year 2286 in seconds are safely treated as ms.
    return expires_at / 1000.0 if expires_at > 10_000_000_000 else expires_at


def _decode_json_response(response: HttpResponse, *, provider_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LlmProviderError(
            code=LlmProviderErrorCode.INVALID_RESPONSE,
            message="GigaChat response is not valid JSON",
            provider_name=provider_name,
        ) from exc
    if not isinstance(payload, dict):
        raise LlmProviderError(
            code=LlmProviderErrorCode.INVALID_RESPONSE,
            message="GigaChat response root is not an object",
            provider_name=provider_name,
        )
    return payload


def _validate_system_message_first(request: StructuredGenerationRequest) -> None:
    if not request.messages or request.messages[0].role != "system":
        raise LlmProviderError(
            code=LlmProviderErrorCode.BAD_REQUEST,
            message="System message must be first",
            provider_name=GigaChatProvider.provider_name,
        )


def _structured_chat_payload(request: StructuredGenerationRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [
            {"role": message.role, "content": message.content} for message in request.messages
        ],
        "temperature": request.temperature,
        "response_format": {
            "type": "json_schema",
            "schema": request.json_schema,
            "strict": True,
        },
    }
    if request.model is not None:
        payload["model"] = request.model
    return payload


def _repair_request(request: StructuredGenerationRequest, raw_response: str) -> StructuredGenerationRequest:
    repair_messages = (
        request.messages[0],
        *request.messages[1:],
        LlmMessage(
            role="user",
            content=(
                "The previous response was not valid JSON for the requested schema. "
                "Return only a valid JSON object that conforms to the same schema. "
                f"Previous response:\n{raw_response}"
            ),
        ),
    )
    return StructuredGenerationRequest(
        messages=repair_messages,
        schema_name=request.schema_name,
        json_schema=request.json_schema,
        model=request.model,
        temperature=request.temperature,
        idempotency_key=request.idempotency_key,
        prompt_version=request.prompt_version,
    )


def _parse_structured_generation_response(
    *,
    response: HttpResponse,
    response_model: type[TResponse],
    provider_name: str,
) -> StructuredGenerationResult[TResponse]:
    payload = _decode_json_response(response, provider_name=provider_name)
    choice = _first_choice(payload, provider_name=provider_name)
    finish_reason = str(choice.get("finish_reason") or "")
    if finish_reason in TRUNCATED_FINISH_REASONS:
        raise LlmProviderError(
            code=LlmProviderErrorCode.INVALID_RESPONSE,
            message="GigaChat response was truncated",
            provider_name=provider_name,
            details={"finish_reason": finish_reason},
        )
    if finish_reason in BLACKLIST_FINISH_REASONS:
        raise LlmProviderError(
            code=LlmProviderErrorCode.INVALID_RESPONSE,
            message="GigaChat rejected the response by content policy",
            provider_name=provider_name,
            details={"finish_reason": finish_reason},
        )
    content = _choice_content(choice, provider_name=provider_name)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise invalid_response_error(
            provider_name=provider_name,
            message="GigaChat response content is not valid JSON",
        ) from exc
    try:
        value = response_model.model_validate(parsed)
    except ValidationError as exc:
        raise invalid_response_error(
            provider_name=provider_name,
            message="GigaChat response content does not match schema",
            validation_error=exc,
        ) from exc
    usage = _usage_from_payload(payload)
    return StructuredGenerationResult(
        value=value,
        model=str(payload.get("model") or ""),
        usage=usage,
        finish_reason=finish_reason,
        provider_metadata={"response_id": payload.get("id")},
    )


def _first_choice(payload: dict[str, Any], *, provider_name: str) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LlmProviderError(
            code=LlmProviderErrorCode.INVALID_RESPONSE,
            message="GigaChat chat response has no valid choice",
            provider_name=provider_name,
        )
    return choices[0]


def _choice_content(choice: dict[str, Any], *, provider_name: str) -> str:
    message = choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise LlmProviderError(
            code=LlmProviderErrorCode.INVALID_RESPONSE,
            message="GigaChat chat response choice has no content",
            provider_name=provider_name,
        )
    return str(message["content"])


def _usage_from_payload(payload: dict[str, Any]) -> LlmUsage:
    raw_usage = payload.get("usage")
    if not isinstance(raw_usage, dict):
        raw_usage = {}
    input_tokens = _int_usage(raw_usage.get("prompt_tokens"))
    output_tokens = _int_usage(raw_usage.get("completion_tokens"))
    total_tokens = _int_usage(raw_usage.get("total_tokens")) or input_tokens + output_tokens
    return LlmUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        provider_metadata={},
    )


def _int_usage(value: Any) -> int:
    return value if isinstance(value, int) else 0
