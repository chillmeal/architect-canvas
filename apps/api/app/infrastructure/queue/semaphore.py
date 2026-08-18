from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.infrastructure.llm.provider import LlmProviderError
from app.infrastructure.llm.retry import LlmRetryPolicy

TResult = TypeVar("TResult")


class BoundedLlmExecutor:
    def __init__(
        self,
        *,
        max_concurrency: int,
        retry_policy: LlmRetryPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._retry_policy = retry_policy or LlmRetryPolicy()
        self._sleep = sleep

    async def run(self, operation: Callable[[], Awaitable[TResult]]) -> TResult:
        async with self._semaphore:
            attempt = 1
            while True:
                try:
                    return await operation()
                except LlmProviderError as exc:
                    if not self._retry_policy.should_retry(exc, attempt=attempt):
                        raise
                    await self._sleep(self._retry_policy.backoff_seconds(attempt=attempt))
                    attempt += 1
