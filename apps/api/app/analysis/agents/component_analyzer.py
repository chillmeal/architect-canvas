from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis.context_builder import AnalysisUnitContext
from app.contracts.graph import CandidateFact
from app.infrastructure.llm import (
    CancellationToken,
    LlmProvider,
    LlmUsage,
    StructuredGenerationRequest,
)


class ComponentAnalyzerUnresolvedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    related_paths: tuple[str, ...] = ()


class ComponentAnalyzerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: tuple[CandidateFact, ...] = ()
    unresolved_questions: tuple[ComponentAnalyzerUnresolvedQuestion, ...] = ()

    @model_validator(mode="after")
    def validate_facts_or_questions(self) -> ComponentAnalyzerOutput:
        if not self.facts and not self.unresolved_questions:
            raise ValueError("component analyzer output must contain facts or unresolved questions")
        return self


@dataclass(frozen=True)
class ComponentAnalyzerResult:
    analysis_unit_id: str
    facts: tuple[CandidateFact, ...]
    unresolved_questions: tuple[ComponentAnalyzerUnresolvedQuestion, ...]
    model: str
    usage: LlmUsage
    finish_reason: str
    metadata: dict[str, object]


class ComponentAnalyzer:
    schema_name = "ComponentAnalyzerOutput"

    def __init__(self, *, provider: LlmProvider, model: str | None = None) -> None:
        self._provider = provider
        self._model = model

    async def analyze(
        self,
        context: AnalysisUnitContext,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> ComponentAnalyzerResult:
        response = await self._provider.generate_structured(
            StructuredGenerationRequest(
                messages=context.messages,
                schema_name=self.schema_name,
                json_schema=ComponentAnalyzerOutput.model_json_schema(),
                model=self._model,
                temperature=0.0,
                prompt_version=context.prompt_manifest.version,
            ),
            ComponentAnalyzerOutput,
            cancellation_token=cancellation_token,
        )
        facts = tuple(_strip_model_confidence(fact) for fact in response.value.facts)
        return ComponentAnalyzerResult(
            analysis_unit_id=context.unit_id,
            facts=facts,
            unresolved_questions=response.value.unresolved_questions,
            model=response.model,
            usage=response.usage,
            finish_reason=response.finish_reason,
            metadata={
                **context.metadata,
                "provider": self._provider.provider_name,
                "fact_count": len(facts),
                "unresolved_question_count": len(response.value.unresolved_questions),
            },
        )


def _strip_model_confidence(fact: CandidateFact) -> CandidateFact:
    metadata = _strip_confidence_keys(fact.metadata)
    if metadata == fact.metadata:
        return fact
    return fact.model_copy(update={"metadata": metadata})


def _strip_confidence_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_confidence_keys(item)
            for key, item in value.items()
            if key.lower() not in {"confidence", "final_confidence", "model_confidence"}
        }
    if isinstance(value, list):
        return [_strip_confidence_keys(item) for item in value]
    return value
