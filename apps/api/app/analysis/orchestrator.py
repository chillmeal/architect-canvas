from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from app.analysis.agents import ComponentAnalyzer, DiscoveryAgent
from app.analysis.context_builder import AnalysisUnitContextBuilder
from app.contracts.graph import CandidateFact, ValidationIssue, ValidationRecord, ValidationResult
from app.core.config import AppConfig
from app.domain.enums import (
    AuditStageName,
    AuditStatus,
    EvidenceStrength,
    LlmValidatorDecision,
    ReasonCode,
    ValidationState,
)
from app.graph.assembler import GraphAssembler, GraphAssemblyInput, GraphAssemblyResult, ValidatedCandidateFact
from app.graph.deduplicator import CandidateDeduplicator
from app.graph.normalizer import CandidateNormalizer
from app.infrastructure.llm import LlmModelInfo, LlmProvider, TokenBudget
from app.infrastructure.queue.in_memory import AuditCancellationToken
from app.infrastructure.repository.file_reader import SafeFileReader
from app.infrastructure.repository.scanner import RepositoryFileIndexer, RepositoryFileIndex
from app.infrastructure.repository.unit_detector import AnalysisUnit, AnalysisUnitDetector
from app.validation.confidence import ConfidencePolicy, ConfidencePolicyInput, ConfidenceThresholds
from app.validation.evidence_validator import EvidenceIntegrityValidator
from app.validation.llm_validator import IndependentLlmValidator
from app.validation.semantic_validator import DeterministicSemanticValidator, SemanticValidationContext

StageCallback = Callable[[AuditStatus, AuditStageName, dict[str, object]], None]

DISCOVERY_TASK_PROMPT = """
Discover architecture candidates in this analysis unit. Return only facts supported by evidence from the supplied files.
For NODE facts provide a useful component name and repository_path metadata when known.
For EDGE facts source_stable_key and target_stable_key may be the exact component names, artifact ids, deployment names, package names, or stable keys used by NODE facts in this response.
Evidence must reference the exact relative_path and sha256 shown in the source header and an exact line range from that file.
For every evidence item set source_fragment_marker to a short exact verbatim substring from the cited source lines. Do not invent fragment_hash; leave fragment_hash null unless it was explicitly supplied.
Source lines are prefixed with line numbers for citation only; do not include the numeric prefix in source_fragment_marker.
Prefer UNKNOWN or an unresolved question over guessing.
""".strip()

ANALYSIS_TASK_PROMPT = """
Analyze this unit as a software architecture component. Extract deployable/application components, APIs, topics, databases, external systems, and runtime/configuration relationships.
Every fact must have evidence from the supplied source files. For each evidence item use the exact relative_path and sha256 from the source header, exact cited line numbers, and source_fragment_marker containing a short exact verbatim substring from those lines. Do not invent fragment_hash; leave fragment_hash null unless it was explicitly supplied. Source lines are prefixed with line numbers only to make citation reliable; exclude that numeric prefix from source_fragment_marker.
For NODE facts include repository_path and any artifact_id, deployment_name, package_name or aliases you can prove.
For EDGE source_stable_key and target_stable_key may use exact component names, artifact ids, deployment names, package names, or stable keys of corresponding NODE facts.
Do not invent hierarchy, protocols, endpoints, topics, databases, or dependencies that are not present in evidence. Use unresolved_questions for ambiguity.
""".strip()


@dataclass(frozen=True)
class ResolvedAuditModels:
    discovery: str
    analysis: str
    validation: str


@dataclass(frozen=True)
class AuditPipelineResult:
    assembly: GraphAssemblyResult
    file_index: RepositoryFileIndex
    unit_count: int
    raw_candidate_count: int
    normalized_candidate_count: int
    validated_candidate_count: int
    warnings: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]


class _AuditLlmCancellationToken:
    """Adapter between queue cancellation and the LLM provider cancellation contract."""

    def __init__(self, token: AuditCancellationToken) -> None:
        self._token = token

    @property
    def cancelled(self) -> bool:
        return self._token.cancelled

    def throw_if_cancelled(self, provider_name: str = "unknown") -> None:  # noqa: ARG002
        self._token.throw_if_cancelled()


class AuditOrchestrator:
    def __init__(self, *, config: AppConfig, provider: LlmProvider) -> None:
        self._config = config
        self._provider = provider
        self._normalizer = CandidateNormalizer()
        self._deduplicator = CandidateDeduplicator()
        self._semantic_validator = DeterministicSemanticValidator()
        self._graph_assembler = GraphAssembler()
        self._confidence_policy = ConfidencePolicy(ConfidenceThresholds.from_config(config))

    async def run(
        self,
        *,
        project_id: str,
        audit_id: str,
        repository_state_id: str,
        repository_root: str | Path,
        cancellation_token: AuditCancellationToken,
        on_stage: StageCallback,
    ) -> AuditPipelineResult:
        root = Path(repository_root)
        llm_cancellation = _AuditLlmCancellationToken(cancellation_token)
        warnings: list[str] = []
        issues: list[ValidationIssue] = []

        on_stage(AuditStatus.SCANNING, AuditStageName.SCANNING, {})
        cancellation_token.throw_if_cancelled()
        file_index = RepositoryFileIndexer(
            self._config.repository_allowed_roots,
            max_file_bytes=self._config.audit_max_file_bytes,
        ).index_files(root)
        warnings.extend(f"{warning.code}:{warning.path}" for warning in file_index.warnings)
        units = AnalysisUnitDetector(root).detect(file_index)
        models = await self._resolve_models(cancellation_token=llm_cancellation)

        on_stage(
            AuditStatus.DISCOVERING,
            AuditStageName.DISCOVERING,
            {"unit_count": len(units), "indexed_file_count": sum(1 for item in file_index.files if item.readable)},
        )
        discovery_candidates, discovery_warnings = await self._discover_units(
            root=root,
            units=units,
            model=models.discovery,
            cancellation_token=llm_cancellation,
        )
        warnings.extend(discovery_warnings)

        on_stage(
            AuditStatus.ANALYZING,
            AuditStageName.ANALYZING,
            {"discovery_candidate_count": len(discovery_candidates)},
        )
        analyzed_candidates, analysis_warnings = await self._analyze_units(
            root=root,
            units=units,
            model=models.analysis,
            cancellation_token=llm_cancellation,
        )
        warnings.extend(analysis_warnings)
        raw_candidates = (*discovery_candidates, *analyzed_candidates)

        normalization = self._normalizer.normalize(project_id=project_id, candidates=raw_candidates)
        warnings.extend(f"NORMALIZATION:{item.fact_id}:{item.message}" for item in normalization.issues)
        resolved_candidates = _resolve_edge_references(normalization.candidates)
        deduplication = self._deduplicator.deduplicate(resolved_candidates)
        issues.extend(deduplication.issues)

        on_stage(
            AuditStatus.VALIDATING,
            AuditStageName.DETERMINISTIC_VALIDATION,
            {"candidate_count": len(deduplication.candidates)},
        )
        validated_candidates, validation_issues = await self._validate_candidates(
            root=root,
            file_index=file_index,
            candidates=deduplication.candidates,
            model=models.validation,
            cancellation_token=llm_cancellation,
        )
        issues.extend(validation_issues)

        on_stage(
            AuditStatus.ASSEMBLING,
            AuditStageName.ASSEMBLING,
            {"validated_candidate_count": len(validated_candidates)},
        )
        assembly = self._graph_assembler.assemble(
            GraphAssemblyInput(
                snapshot_id=str(uuid4()),
                project_id=project_id,
                audit_id=audit_id,
                repository_state_id=repository_state_id,
                candidates=validated_candidates,
                issues=tuple(issues),
            )
        )
        issues.extend(assembly.validation.issues)
        return AuditPipelineResult(
            assembly=assembly,
            file_index=file_index,
            unit_count=len(units),
            raw_candidate_count=len(raw_candidates),
            normalized_candidate_count=len(deduplication.candidates),
            validated_candidate_count=len(validated_candidates),
            warnings=tuple(dict.fromkeys(warnings)),
            issues=tuple(issues),
        )

    async def _discover_units(
        self,
        *,
        root: Path,
        units: tuple[AnalysisUnit, ...],
        model: str,
        cancellation_token: _AuditLlmCancellationToken,
    ) -> tuple[tuple[CandidateFact, ...], tuple[str, ...]]:
        agent = DiscoveryAgent(provider=self._provider, model=model)
        return await self._run_unit_agent(
            root=root,
            units=units,
            task_prompt=DISCOVERY_TASK_PROMPT,
            prompt_name="discovery",
            operation=lambda context: agent.discover(context, cancellation_token=cancellation_token),
            result_facts=lambda result: result.candidates,
            cancellation_token=cancellation_token,
            warning_prefix="DISCOVERY_FAILED",
        )

    async def _analyze_units(
        self,
        *,
        root: Path,
        units: tuple[AnalysisUnit, ...],
        model: str,
        cancellation_token: _AuditLlmCancellationToken,
    ) -> tuple[tuple[CandidateFact, ...], tuple[str, ...]]:
        agent = ComponentAnalyzer(provider=self._provider, model=model)
        return await self._run_unit_agent(
            root=root,
            units=units,
            task_prompt=ANALYSIS_TASK_PROMPT,
            prompt_name="component_analysis",
            operation=lambda context: agent.analyze(context, cancellation_token=cancellation_token),
            result_facts=lambda result: result.facts,
            cancellation_token=cancellation_token,
            warning_prefix="ANALYSIS_FAILED",
        )

    async def _run_unit_agent(
        self,
        *,
        root: Path,
        units: tuple[AnalysisUnit, ...],
        task_prompt: str,
        prompt_name: str,
        operation,
        result_facts,
        cancellation_token: _AuditLlmCancellationToken,
        warning_prefix: str,
    ) -> tuple[tuple[CandidateFact, ...], tuple[str, ...]]:
        budget = _token_budget(self._config.audit_max_input_tokens)
        manifest_path = Path(__file__).parent / "agents" / "prompts" / prompt_name / "manifest.json"
        builder = AnalysisUnitContextBuilder(
            repository_root=root,
            token_budget=budget,
            prompt_manifest_path=manifest_path,
        )
        semaphore = asyncio.Semaphore(self._config.gigachat_max_concurrency)

        async def run_one(unit: AnalysisUnit):
            async with semaphore:
                cancellation_token.throw_if_cancelled()
                context = builder.build(analysis_unit=unit, task_prompt=task_prompt)
                try:
                    result = await operation(context)
                    return tuple(result_facts(result)), None
                except Exception as exc:  # noqa: BLE001
                    if cancellation_token.cancelled:
                        cancellation_token.throw_if_cancelled()
                    return (), f"{warning_prefix}:{unit.unit_id}:{type(exc).__name__}:{exc}"

        results = await asyncio.gather(*(run_one(unit) for unit in units))
        facts: list[CandidateFact] = []
        warnings: list[str] = []
        for unit_facts, warning in results:
            facts.extend(unit_facts)
            if warning:
                warnings.append(warning)
        return tuple(facts), tuple(warnings)

    async def _validate_candidates(
        self,
        *,
        root: Path,
        file_index: RepositoryFileIndex,
        candidates: tuple[CandidateFact, ...],
        model: str,
        cancellation_token: _AuditLlmCancellationToken,
    ) -> tuple[tuple[ValidatedCandidateFact, ...], tuple[ValidationIssue, ...]]:
        evidence_validator = EvidenceIntegrityValidator(root, file_index)
        llm_validator = IndependentLlmValidator(
            provider=self._provider,
            repository_root=root,
            model=model,
        )
        reader = SafeFileReader(root)
        node_types_by_stable_key = {
            str(candidate.metadata["stable_key"]): candidate.node_type
            for candidate in candidates
            if candidate.fact_kind == "NODE"
            and candidate.node_type is not None
            and isinstance(candidate.metadata.get("stable_key"), str)
        }
        semantic_context = SemanticValidationContext(
            node_types_by_stable_key=node_types_by_stable_key,
            evidence_fragments_by_id=_evidence_fragments(candidates, reader),
        )
        validated: list[ValidatedCandidateFact] = []
        issues: list[ValidationIssue] = []

        for candidate in candidates:
            cancellation_token.throw_if_cancelled()
            evidence_outcomes = tuple(evidence_validator.validate(item) for item in candidate.evidence)
            deterministic_results: list[ValidationResult] = [item.result for item in evidence_outcomes]
            for outcome in evidence_outcomes:
                issues.extend(outcome.issues)
            semantic = self._semantic_validator.validate(candidate, semantic_context)
            deterministic_results.append(semantic.result)
            issues.extend(semantic.issues)

            llm_outcome = await llm_validator.validate(
                candidate,
                deterministic_results=tuple(deterministic_results),
                cancellation_token=cancellation_token,
            )
            if llm_outcome.issue is not None:
                issues.append(llm_outcome.issue)
            decision = _llm_decision(llm_outcome.result)
            reason_codes = tuple(
                dict.fromkeys(
                    reason
                    for result in (*deterministic_results, llm_outcome.result)
                    for reason in result.reason_codes
                )
            )
            strengths = tuple(item.strength for item in candidate.evidence)
            policy = self._confidence_policy.decide(
                ConfidencePolicyInput(
                    evidence_strengths=strengths,
                    reason_codes=reason_codes,
                    deterministic_state=_worst_deterministic_state(tuple(deterministic_results)),
                    llm_validator_decision=decision,
                    has_direct_strong_source_signal=EvidenceStrength.STRONG in strengths,
                    independent_medium_source_signals=sum(
                        1 for strength in strengths if strength == EvidenceStrength.MEDIUM
                    ),
                )
            )
            validated.append(
                ValidatedCandidateFact(
                    candidate=candidate,
                    validation_record=ValidationRecord(
                        analyzer_invocation_id=_metadata_string(candidate.metadata, "llm_invocation_id"),
                        candidate_schema_version=candidate.candidate_schema_version,
                        evidence=candidate.evidence,
                        deterministic_results=tuple(deterministic_results),
                        independent_validator_invocation_id=None,
                        validator_decision=decision.value if decision is not None else None,
                        policy_version=policy.policy_version,
                        confidence=policy.confidence,
                        final_state=policy.final_state,
                        reason_codes=policy.reason_codes,
                        validated_at=datetime.now(UTC).isoformat(),
                    ),
                )
            )
        return tuple(validated), tuple(issues)

    async def _resolve_models(
        self,
        *,
        cancellation_token: _AuditLlmCancellationToken,
    ) -> ResolvedAuditModels:
        configured = (
            self._config.gigachat_model_discovery,
            self._config.gigachat_model_analysis,
            self._config.gigachat_model_validation,
        )
        if all(configured):
            return ResolvedAuditModels(
                discovery=str(configured[0]),
                analysis=str(configured[1]),
                validation=str(configured[2]),
            )

        models = await self._provider.list_models(cancellation_token=cancellation_token)
        fallback = _preferred_chat_model(models)
        if fallback is None:
            raise RuntimeError("LLM provider returned no models for audit execution")
        return ResolvedAuditModels(
            discovery=self._config.gigachat_model_discovery or fallback,
            analysis=self._config.gigachat_model_analysis or fallback,
            validation=self._config.gigachat_model_validation or fallback,
        )


def _preferred_chat_model(models: tuple[LlmModelInfo, ...]) -> str | None:
    for model in models:
        if any("chat" in capability.lower() for capability in model.capabilities):
            return model.model_id
    return models[0].model_id if models else None


def _token_budget(hard_input_limit: int) -> TokenBudget:
    output_reserve = max(512, min(4096, hard_input_limit // 5))
    fixed = min(1500, max(200, (hard_input_limit - output_reserve) // 10))
    source_context = max(1, hard_input_limit - output_reserve - fixed * 2)
    return TokenBudget(
        system_prompt=fixed,
        task_prompt=fixed,
        source_context=source_context,
        output_reserve=output_reserve,
        hard_input_limit=hard_input_limit,
    )


def _resolve_edge_references(candidates: tuple[CandidateFact, ...]) -> tuple[CandidateFact, ...]:
    aliases: dict[str, set[str]] = {}
    stable_keys: set[str] = set()
    for candidate in candidates:
        if candidate.fact_kind != "NODE":
            continue
        stable_key = candidate.metadata.get("stable_key")
        if not isinstance(stable_key, str) or not stable_key:
            continue
        stable_keys.add(stable_key)
        for alias in _candidate_aliases(candidate):
            aliases.setdefault(_alias_key(alias), set()).add(stable_key)

    def resolve(value: str | None) -> str | None:
        if value is None or value in stable_keys:
            return value
        matches = aliases.get(_alias_key(value), set())
        return next(iter(matches)) if len(matches) == 1 else value

    return tuple(
        candidate.model_copy(
            update={
                "source_stable_key": resolve(candidate.source_stable_key),
                "target_stable_key": resolve(candidate.target_stable_key),
            }
        )
        if candidate.fact_kind == "EDGE"
        else candidate
        for candidate in candidates
    )


def _candidate_aliases(candidate: CandidateFact) -> tuple[str, ...]:
    values: list[str] = []
    if candidate.name:
        values.append(candidate.name)
    if candidate.source_stable_key:
        values.append(candidate.source_stable_key)
    stable_key = candidate.metadata.get("stable_key")
    if isinstance(stable_key, str):
        values.append(stable_key)
    for key in ("artifact_id", "deployment_name", "package_name", "repository_path"):
        value = candidate.metadata.get(key)
        if isinstance(value, str):
            values.append(value)
    raw_aliases = candidate.metadata.get("aliases")
    if isinstance(raw_aliases, (list, tuple)):
        values.extend(item for item in raw_aliases if isinstance(item, str))
    return tuple(values)


def _alias_key(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _evidence_fragments(candidates: tuple[CandidateFact, ...], reader: SafeFileReader) -> dict[str, str]:
    fragments: dict[str, str] = {}
    for candidate in candidates:
        for evidence in candidate.evidence:
            if evidence.evidence_id in fragments:
                continue
            try:
                content = reader.read_text(evidence.relative_path)
                lines = content.splitlines()
                fragments[evidence.evidence_id] = "\n".join(
                    lines[evidence.line_start - 1 : evidence.line_end]
                )
            except Exception:  # noqa: BLE001
                fragments[evidence.evidence_id] = evidence.source_fragment_marker or ""
    return fragments


def _llm_decision(result: ValidationResult) -> LlmValidatorDecision | None:
    value = result.metadata.get("decision")
    if not isinstance(value, str):
        return None
    try:
        return LlmValidatorDecision(value)
    except ValueError:
        return None


def _worst_deterministic_state(results: tuple[ValidationResult, ...]) -> ValidationState | None:
    states = {result.state for result in results}
    for state in (ValidationState.STALE, ValidationState.REJECTED, ValidationState.REVIEW_REQUIRED):
        if state in states:
            return state
    if ValidationState.CONFIRMED_WITH_WARNINGS in states:
        return ValidationState.CONFIRMED_WITH_WARNINGS
    if ValidationState.CONFIRMED in states:
        return ValidationState.CONFIRMED
    return None


def _metadata_string(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None
