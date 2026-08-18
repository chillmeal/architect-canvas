from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBudget:
    system_prompt: int
    task_prompt: int
    source_context: int
    output_reserve: int
    hard_input_limit: int

    @property
    def max_input_tokens(self) -> int:
        return self.hard_input_limit - self.output_reserve

    def validate(self) -> None:
        values = (
            self.system_prompt,
            self.task_prompt,
            self.source_context,
            self.output_reserve,
            self.hard_input_limit,
        )
        if any(value < 0 for value in values):
            raise ValueError("Token budget values must be non-negative")
        if self.system_prompt + self.task_prompt + self.source_context > self.max_input_tokens:
            raise ValueError("Token budget exceeds hard input limit")


@dataclass(frozen=True)
class SourceContextFragment:
    fragment_id: str
    relative_path: str
    token_count: int
    priority: int = 0


@dataclass(frozen=True)
class SourceContextPlan:
    selected: tuple[SourceContextFragment, ...]
    omitted: tuple[SourceContextFragment, ...]
    selected_tokens: int
    omitted_tokens: int


class TokenBudgetPlanner:
    def __init__(self, budget: TokenBudget) -> None:
        budget.validate()
        self.budget = budget

    def plan_source_context(
        self,
        fragments: tuple[SourceContextFragment, ...],
    ) -> SourceContextPlan:
        selected: list[SourceContextFragment] = []
        omitted: list[SourceContextFragment] = []
        selected_tokens = 0
        available_tokens = self.budget.source_context
        for fragment in sorted(
            fragments,
            key=lambda item: (-item.priority, item.relative_path, item.fragment_id),
        ):
            if fragment.token_count <= 0:
                omitted.append(fragment)
                continue
            if selected_tokens + fragment.token_count <= available_tokens:
                selected.append(fragment)
                selected_tokens += fragment.token_count
            else:
                omitted.append(fragment)
        return SourceContextPlan(
            selected=tuple(selected),
            omitted=tuple(
                sorted(omitted, key=lambda item: (item.relative_path, item.fragment_id))
            ),
            selected_tokens=selected_tokens,
            omitted_tokens=sum(fragment.token_count for fragment in omitted),
        )
