from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis.context_builder import AnalysisUnitContext
from app.contracts.graph import CandidateFact
from app.infrastructure.llm import (
    CancellationToken,
    LlmProvider,
    LlmUsage,
    StructuredGenerationRequest,
)


class DiscoveryUnresolvedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    related_paths: tuple[str, ...] = ()


class DiscoveryAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: tuple[CandidateFact, ...] = ()
    unresolved_questions: tuple[DiscoveryUnresolvedQuestion, ...] = ()

    @model_validator(mode="after")
    def validate_candidates_or_questions(self) -> DiscoveryAgentOutput:
        if not self.candidates and not self.unresolved_questions:
            raise ValueError("discovery output must contain candidates or unresolved questions")
        return self


@dataclass(frozen=True)
class DiscoveryAgentResult:
    analysis_unit_id: str
    candidates: tuple[CandidateFact, ...]
    unresolved_questions: tuple[DiscoveryUnresolvedQuestion, ...]
    model: str
    usage: LlmUsage
    finish_reason: str
    metadata: dict[str, object]


class DiscoveryAgent:
    schema_name = "DiscoveryAgentOutput"

    def __init__(self, *, provider: LlmProvider, model: str | None = None) -> None:
        self._provider = provider
        self._model = model

    async def discover(
        self,
        context: AnalysisUnitContext,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> DiscoveryAgentResult:
        response = await self._provider.generate_structured(
            StructuredGenerationRequest(
                messages=context.messages,
                schema_name=self.schema_name,
                json_schema=DiscoveryAgentOutput.model_json_schema(),
                model=self._model,
                temperature=0.0,
                prompt_version=context.prompt_manifest.version,
            ),
            DiscoveryAgentOutput,
            cancellation_token=cancellation_token,
        )
        return DiscoveryAgentResult(
            analysis_unit_id=context.unit_id,
            candidates=response.value.candidates,
            unresolved_questions=response.value.unresolved_questions,
            model=response.model,
            usage=response.usage,
            finish_reason=response.finish_reason,
            metadata={
                **context.metadata,
                "provider": self._provider.provider_name,
                "candidate_count": len(response.value.candidates),
                "unresolved_question_count": len(response.value.unresolved_questions),
            },
        )
