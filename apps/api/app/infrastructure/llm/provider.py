from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

TResponse = TypeVar("TResponse", bound=BaseModel)


class LlmProviderErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    SCHEMA_REJECTED = "SCHEMA_REJECTED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class LlmProviderError(RuntimeError):
    def __init__(
        self,
        *,
        code: LlmProviderErrorCode,
        message: str,
        provider_name: str,
        retryable: bool = False,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.provider_name = provider_name
        self.retryable = retryable
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class LlmCancelledError(LlmProviderError):
    def __init__(self, provider_name: str = "unknown") -> None:
        super().__init__(
            code=LlmProviderErrorCode.CANCELLED,
            message="LLM request was cancelled",
            provider_name=provider_name,
            retryable=False,
        )


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def throw_if_cancelled(self, provider_name: str = "unknown") -> None:
        if self._cancelled:
            raise LlmCancelledError(provider_name=provider_name)


@dataclass(frozen=True)
class LlmMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LlmModelInfo:
    model_id: str
    owned_by: str | None = None
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class LlmHealthStatus:
    ok: bool
    provider_name: str
    models_available: int
    message: str | None = None


@dataclass(frozen=True)
class StructuredGenerationRequest:
    messages: tuple[LlmMessage, ...]
    schema_name: str
    json_schema: dict[str, Any]
    model: str | None = None
    temperature: float = 0.0
    idempotency_key: str | None = None
    prompt_version: str | None = None


@dataclass(frozen=True)
class StructuredGenerationResult(Generic[TResponse]):
    value: TResponse
    model: str
    usage: LlmUsage
    finish_reason: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TokenCountResult:
    tokens: int
    model: str | None = None


class LlmProvider(Protocol):
    provider_name: str

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        response_model: type[TResponse],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> StructuredGenerationResult[TResponse]:
        pass

    async def count_tokens(
        self,
        messages: tuple[LlmMessage, ...],
        *,
        model: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TokenCountResult:
        pass

    async def list_models(
        self,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[LlmModelInfo, ...]:
        pass

    async def health_check(
        self,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LlmHealthStatus:
        pass


def map_http_status_to_provider_error(
    *,
    status_code: int,
    provider_name: str,
    message: str,
) -> LlmProviderError:
    code, retryable = _http_error_policy(status_code)
    return LlmProviderError(
        code=code,
        message=message,
        provider_name=provider_name,
        retryable=retryable,
        status_code=status_code,
    )


def invalid_response_error(
    *,
    provider_name: str,
    message: str,
    validation_error: ValidationError | None = None,
) -> LlmProviderError:
    details: dict[str, Any] = {}
    if validation_error is not None:
        details["validation_errors"] = validation_error.errors(include_input=False)
    return LlmProviderError(
        code=LlmProviderErrorCode.INVALID_RESPONSE,
        message=message,
        provider_name=provider_name,
        retryable=False,
        details=details,
    )


def _http_error_policy(status_code: int) -> tuple[LlmProviderErrorCode, bool]:
    if status_code == 400:
        return LlmProviderErrorCode.BAD_REQUEST, False
    if status_code == 401:
        return LlmProviderErrorCode.UNAUTHORIZED, True
    if status_code == 402:
        return LlmProviderErrorCode.QUOTA_EXCEEDED, False
    if status_code == 403:
        return LlmProviderErrorCode.FORBIDDEN, False
    if status_code == 413:
        return LlmProviderErrorCode.PAYLOAD_TOO_LARGE, True
    if status_code == 422:
        return LlmProviderErrorCode.SCHEMA_REJECTED, False
    if status_code == 429:
        return LlmProviderErrorCode.RATE_LIMITED, True
    if status_code in {500, 502, 503, 504}:
        return LlmProviderErrorCode.SERVER_ERROR, True
    return LlmProviderErrorCode.PROVIDER_UNAVAILABLE, False
