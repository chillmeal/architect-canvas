from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.llm.provider import LlmProviderError, LlmProviderErrorCode


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    max_attempts: int
    reason: str


class LlmRetryPolicy:
    def decision_for(self, error: LlmProviderError) -> RetryDecision:
        if error.code == LlmProviderErrorCode.BAD_REQUEST:
            return RetryDecision(False, 1, "bad request")
        if error.code == LlmProviderErrorCode.UNAUTHORIZED:
            return RetryDecision(False, 1, "token refresh is handled by provider")
        if error.code == LlmProviderErrorCode.QUOTA_EXCEEDED:
            return RetryDecision(False, 1, "quota exceeded")
        if error.code == LlmProviderErrorCode.FORBIDDEN:
            return RetryDecision(False, 1, "forbidden")
        if error.code == LlmProviderErrorCode.PAYLOAD_TOO_LARGE:
            return RetryDecision(True, 2, "rebuild smaller context")
        if error.code == LlmProviderErrorCode.SCHEMA_REJECTED:
            return RetryDecision(False, 1, "schema rejected")
        if error.code == LlmProviderErrorCode.RATE_LIMITED:
            return RetryDecision(True, 4, "rate limited")
        if error.code == LlmProviderErrorCode.SERVER_ERROR:
            return RetryDecision(True, 4, "server error")
        if error.code == LlmProviderErrorCode.TIMEOUT:
            return RetryDecision(True, 3, "timeout")
        if error.code == LlmProviderErrorCode.INVALID_RESPONSE:
            return RetryDecision(False, 1, "invalid response handled by structured call")
        if error.code == LlmProviderErrorCode.CANCELLED:
            return RetryDecision(False, 1, "cancelled")
        return RetryDecision(False, 1, "provider unavailable")

    def should_retry(self, error: LlmProviderError, *, attempt: int) -> bool:
        decision = self.decision_for(error)
        return decision.should_retry and attempt < decision.max_attempts

    def backoff_seconds(self, *, attempt: int) -> float:
        return min(8.0, 0.25 * (2 ** max(0, attempt - 1)))
