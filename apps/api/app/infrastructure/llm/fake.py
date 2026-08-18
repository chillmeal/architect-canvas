from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.infrastructure.llm.provider import (
    CancellationToken,
    LlmHealthStatus,
    LlmMessage,
    LlmModelInfo,
    LlmProviderError,
    LlmUsage,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenCountResult,
    invalid_response_error,
)


@dataclass(frozen=True)
class FakeStructuredResponse:
    payload: BaseModel | dict[str, Any]
    model: str = "fake-model"
    finish_reason: str = "stop"
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_metadata: dict[str, Any] | None = None


class FakeLlmProvider:
    provider_name = "fake"

    def __init__(
        self,
        *,
        models: tuple[LlmModelInfo, ...] | None = None,
        healthy: bool = True,
    ) -> None:
        self._responses: deque[FakeStructuredResponse | LlmProviderError] = deque()
        self._models = models or (
            LlmModelInfo(model_id="fake-model", owned_by="test", capabilities=("json_schema",)),
        )
        self._healthy = healthy
        self.requests: list[StructuredGenerationRequest] = []

    def enqueue_structured_response(self, response: FakeStructuredResponse) -> None:
        self._responses.append(response)

    def enqueue_error(self, error: LlmProviderError) -> None:
        self._responses.append(error)

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        response_model: type[BaseModel],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> StructuredGenerationResult:
        _throw_if_cancelled(cancellation_token)
        self.requests.append(request)
        queued = self._responses.popleft() if self._responses else FakeStructuredResponse(payload={})
        if isinstance(queued, LlmProviderError):
            raise queued
        _throw_if_cancelled(cancellation_token)
        try:
            value = (
                queued.payload
                if isinstance(queued.payload, response_model)
                else response_model.model_validate(queued.payload)
            )
        except ValidationError as exc:
            raise invalid_response_error(
                provider_name=self.provider_name,
                message="Fake provider response does not match response model",
                validation_error=exc,
            ) from exc
        usage = LlmUsage(
            input_tokens=queued.input_tokens
            if queued.input_tokens is not None
            else _estimate_message_tokens(request.messages),
            output_tokens=queued.output_tokens
            if queued.output_tokens is not None
            else _estimate_output_tokens(value),
            total_tokens=0,
            provider_metadata=queued.provider_metadata or {},
        )
        usage = LlmUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.input_tokens + usage.output_tokens,
            provider_metadata=usage.provider_metadata,
        )
        return StructuredGenerationResult(
            value=value,
            model=queued.model,
            usage=usage,
            finish_reason=queued.finish_reason,
            provider_metadata=queued.provider_metadata or {},
        )

    async def count_tokens(
        self,
        messages: tuple[LlmMessage, ...],
        *,
        model: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TokenCountResult:
        _throw_if_cancelled(cancellation_token)
        return TokenCountResult(tokens=_estimate_message_tokens(messages), model=model)

    async def list_models(
        self,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[LlmModelInfo, ...]:
        _throw_if_cancelled(cancellation_token)
        return self._models

    async def health_check(
        self,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LlmHealthStatus:
        _throw_if_cancelled(cancellation_token)
        return LlmHealthStatus(
            ok=self._healthy,
            provider_name=self.provider_name,
            models_available=len(self._models),
            message=None if self._healthy else "Fake provider is unhealthy",
        )


def _throw_if_cancelled(cancellation_token: CancellationToken | None) -> None:
    if cancellation_token is not None:
        cancellation_token.throw_if_cancelled(provider_name=FakeLlmProvider.provider_name)


def _estimate_message_tokens(messages: tuple[LlmMessage, ...]) -> int:
    return sum(_estimate_text_tokens(message.content) for message in messages)


def _estimate_output_tokens(value: BaseModel) -> int:
    return _estimate_text_tokens(value.model_dump_json())


def _estimate_text_tokens(text: str) -> int:
    return max(1, len(text) // 4)
