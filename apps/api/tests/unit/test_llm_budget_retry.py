import asyncio
from dataclasses import dataclass

import pytest

from app.infrastructure.llm import (
    LlmProviderError,
    LlmProviderErrorCode,
    LlmRetryPolicy,
    SourceContextFragment,
    TokenBudget,
    TokenBudgetPlanner,
    map_http_status_to_provider_error,
)
from app.infrastructure.queue.semaphore import BoundedLlmExecutor


def test_token_budget_is_split_and_context_is_reduced_deterministically() -> None:
    budget = TokenBudget(
        system_prompt=100,
        task_prompt=200,
        source_context=50,
        output_reserve=150,
        hard_input_limit=500,
    )
    plan = TokenBudgetPlanner(budget).plan_source_context(
        (
            SourceContextFragment("b", "src/b.py", token_count=30, priority=10),
            SourceContextFragment("a", "src/a.py", token_count=25, priority=10),
            SourceContextFragment("low", "README.md", token_count=20, priority=1),
        )
    )

    assert budget.max_input_tokens == 350
    assert [fragment.fragment_id for fragment in plan.selected] == ["a", "low"]
    assert [fragment.fragment_id for fragment in plan.omitted] == ["b"]
    assert plan.selected_tokens == 45
    assert plan.omitted_tokens == 30


def test_token_budget_rejects_over_allocated_budget() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        TokenBudget(
            system_prompt=100,
            task_prompt=100,
            source_context=100,
            output_reserve=300,
            hard_input_limit=500,
        ).validate()


@pytest.mark.parametrize(
    ("status_code", "code", "should_retry", "max_attempts"),
    [
        (400, LlmProviderErrorCode.BAD_REQUEST, False, 1),
        (401, LlmProviderErrorCode.UNAUTHORIZED, False, 1),
        (413, LlmProviderErrorCode.PAYLOAD_TOO_LARGE, True, 2),
        (422, LlmProviderErrorCode.SCHEMA_REJECTED, False, 1),
        (429, LlmProviderErrorCode.RATE_LIMITED, True, 4),
        (500, LlmProviderErrorCode.SERVER_ERROR, True, 4),
        (503, LlmProviderErrorCode.SERVER_ERROR, True, 4),
    ],
)
def test_retry_policy_matches_architecture_table(
    status_code: int,
    code: LlmProviderErrorCode,
    should_retry: bool,
    max_attempts: int,
) -> None:
    error = map_http_status_to_provider_error(
        status_code=status_code,
        provider_name="gigachat",
        message="failed",
    )
    decision = LlmRetryPolicy().decision_for(error)

    assert error.code == code
    assert decision.should_retry is should_retry
    assert decision.max_attempts == max_attempts


def test_retry_policy_maps_timeout_to_two_retries() -> None:
    error = LlmProviderError(
        code=LlmProviderErrorCode.TIMEOUT,
        message="timeout",
        provider_name="gigachat",
        retryable=True,
    )

    decision = LlmRetryPolicy().decision_for(error)

    assert decision.should_retry is True
    assert decision.max_attempts == 3


@pytest.mark.anyio
async def test_retries_do_not_bypass_semaphore_concurrency_limit() -> None:
    state = ConcurrencyState()
    executor = BoundedLlmExecutor(
        max_concurrency=1,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    async def operation(name: str) -> str:
        state.active += 1
        state.max_active = max(state.max_active, state.active)
        await asyncio.sleep(0)
        state.active -= 1
        state.attempts[name] = state.attempts.get(name, 0) + 1
        if state.attempts[name] == 1:
            raise LlmProviderError(
                code=LlmProviderErrorCode.RATE_LIMITED,
                message="rate limited",
                provider_name="fake",
                retryable=True,
            )
        return name

    results = await asyncio.gather(
        executor.run(lambda: operation("first")),
        executor.run(lambda: operation("second")),
    )

    assert results == ["first", "second"]
    assert state.max_active == 1
    assert state.attempts == {"first": 2, "second": 2}


@dataclass
class ConcurrencyState:
    active: int = 0
    max_active: int = 0
    attempts: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.attempts is None:
            self.attempts = {}
