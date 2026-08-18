from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppConfig
from app.core.errors import AppError
from app.analysis.orchestrator import AuditOrchestrator
from app.domain.enums import AuditStageName, AuditStatus
from app.infrastructure.db.models import AuditRecord
from app.infrastructure.db.repositories import (
    AuditEventPage,
    AuditEventRepository,
    AuditRepository,
    ProjectRepository,
    RepositoryStateRepository,
    GraphSnapshotRepository,
)
from app.infrastructure.db.session import session_scope
from app.infrastructure.llm import LlmProvider
from app.infrastructure.queue.in_memory import (
    AuditJobContext,
    DuplicateActiveAuditError,
    InMemoryAuditQueue,
)
from app.infrastructure.repository.git_metadata import GitMetadataError, GitMetadataReader


@dataclass(frozen=True)
class StartedAudit:
    audit: AuditRecord
    idempotent_replay: bool = False


@dataclass(frozen=True)
class AuditIssuePage:
    issues: tuple[dict[str, Any], ...]
    next_offset: int | None


class AuditService:
    def __init__(
        self,
        *,
        session: Session,
        session_factory: sessionmaker[Session],
        config: AppConfig,
        audit_queue: InMemoryAuditQueue,
        llm_provider: LlmProvider,
    ) -> None:
        self._session = session
        self._session_factory = session_factory
        self._config = config
        self._audit_queue = audit_queue
        self._llm_provider = llm_provider
        self._projects = ProjectRepository(session)
        self._repository_states = RepositoryStateRepository(session)
        self._audits = AuditRepository(session)
        self._events = AuditEventRepository(session)

    async def start_audit(
        self,
        *,
        project_id: str,
        idempotency_key: str | None,
    ) -> StartedAudit:
        project = self._projects.get_project(project_id)
        if project is None or project.is_archived:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", status_code=HTTPStatus.NOT_FOUND)

        if idempotency_key:
            existing = self._audits.find_by_idempotency_key(
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return StartedAudit(audit=existing, idempotent_replay=True)

        active_audits = self._audits.list_active_audits(project_id=project_id)
        if active_audits:
            raise AppError(
                "ACTIVE_AUDIT_CONFLICT",
                "Project has an active audit",
                status_code=HTTPStatus.CONFLICT,
                details={"audit_id": active_audits[0].audit_id},
            )

        try:
            git_metadata = GitMetadataReader(
                self._config.repository_allowed_roots,
                allow_non_git=self._config.audit_allow_non_git,
            ).read(project.repository_root)
        except GitMetadataError as exc:
            raise AppError(
                "AUDIT_PREFLIGHT_FAILED",
                "Audit preflight validation failed",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                details={"category": "GIT_METADATA", "message": str(exc)},
            ) from exc

        repository_state = self._repository_states.create_repository_state(
            project_id=project.project_id,
            commit_sha=git_metadata.commit_sha,
            branch=git_metadata.branch,
            dirty=git_metadata.dirty,
            tree_hash=git_metadata.tree_hash,
            metadata={"non_git": git_metadata.non_git},
        )
        audit = self._audits.create_audit(
            project_id=project.project_id,
            repository_state_id=repository_state.repository_state_id,
            summary={"idempotency_key": idempotency_key} if idempotency_key else {},
        )
        self._events.append_event(
            audit_id=audit.audit_id,
            event_type="AUDIT_QUEUED",
            message="Audit queued",
            payload={"project_id": project.project_id},
        )

        # The queue runs in a separate DB session. Commit the durable audit handoff before
        # scheduling the worker so it cannot race the request-scoped transaction.
        self._session.commit()

        try:
            await self._audit_queue.submit(
                audit_id=audit.audit_id,
                project_id=project.project_id,
                operation=self._run_audit,
            )
        except DuplicateActiveAuditError as exc:
            # The audit row is already durable by design. Close it explicitly instead of
            # leaving a QUEUED orphan when a concurrent queue handoff wins the race.
            self._audits.update_status(audit_id=audit.audit_id, status=AuditStatus.CANCELLED)
            self._events.append_event(
                audit_id=audit.audit_id,
                event_type="AUDIT_QUEUE_REJECTED",
                message="Audit queue rejected a duplicate active project job",
            )
            self._session.commit()
            raise AppError(
                "ACTIVE_AUDIT_CONFLICT",
                "Project has an active audit",
                status_code=HTTPStatus.CONFLICT,
                details={"project_id": exc.project_id},
            ) from exc
        return StartedAudit(audit=audit)

    def list_project_audits(self, *, project_id: str) -> tuple[AuditRecord, ...]:
        project = self._projects.get_project(project_id)
        if project is None:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", status_code=HTTPStatus.NOT_FOUND)
        return self._audits.list_project_audits(project_id=project_id)

    def get_audit(self, audit_id: str) -> AuditRecord:
        audit = self._audits.get_audit(audit_id)
        if audit is None:
            raise AppError("AUDIT_NOT_FOUND", "Audit not found", status_code=HTTPStatus.NOT_FOUND)
        return audit

    def list_events(self, *, audit_id: str, offset: int, limit: int) -> AuditEventPage:
        self.get_audit(audit_id)
        return self._events.list_events(audit_id=audit_id, offset=offset, limit=limit)

    async def cancel_audit(self, audit_id: str) -> AuditRecord:
        audit = self.get_audit(audit_id)
        status = AuditStatus(audit.status)
        if status in {
            AuditStatus.COMPLETED,
            AuditStatus.COMPLETED_WITH_WARNINGS,
            AuditStatus.FAILED,
            AuditStatus.CANCELLED,
            AuditStatus.INTERRUPTED,
        }:
            raise AppError(
                "AUDIT_NOT_CANCELLABLE",
                "Audit is already terminal",
                status_code=HTTPStatus.CONFLICT,
                details={"status": status.value},
            )
        await self._audit_queue.cancel(audit_id)
        if status in {AuditStatus.QUEUED, AuditStatus.ANALYZING}:
            audit = self._audits.update_status(audit_id=audit_id, status=AuditStatus.CANCELLED)
            self._events.append_event(
                audit_id=audit_id,
                event_type="AUDIT_CANCELLED",
                message="Audit cancelled",
            )
        else:
            self._events.append_event(
                audit_id=audit_id,
                event_type="AUDIT_CANCELLATION_REQUESTED",
                message="Audit cancellation requested",
            )
        return audit

    def retry_audit(self, audit_id: str, *, scope: str | None = None) -> None:
        audit = self.get_audit(audit_id)
        status = AuditStatus(audit.status)
        if status not in {AuditStatus.FAILED, AuditStatus.PARTIAL}:
            raise AppError(
                "AUDIT_RETRY_NOT_ALLOWED",
                "Retry is allowed only for failed or partial audits",
                status_code=HTTPStatus.CONFLICT,
                details={"status": status.value, "scope": scope},
            )
        raise AppError(
            "AUDIT_RETRY_SCOPE_UNSUPPORTED",
            "Retry scopes are not implemented for the current audit pipeline",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            details={"scope": scope},
        )

    def list_issues(self, *, audit_id: str, offset: int, limit: int) -> AuditIssuePage:
        self.get_audit(audit_id)
        return AuditIssuePage(issues=(), next_offset=None)

    async def _run_audit(self, context: AuditJobContext) -> None:
        orchestrator = AuditOrchestrator(config=self._config, provider=self._llm_provider)

        def on_stage(
            status: AuditStatus,
            stage_name: AuditStageName,
            details: dict[str, object],
        ) -> None:
            context.cancellation_token.throw_if_cancelled()
            with session_scope(self._session_factory) as stage_session:
                audits = AuditRepository(stage_session)
                events = AuditEventRepository(stage_session)
                audit = audits.update_status(audit_id=context.audit_id, status=status)
                events.append_event(
                    audit_id=context.audit_id,
                    event_type="AUDIT_STAGE_CHANGED",
                    message=f"Audit status changed to {status.value}",
                    stage_name=stage_name,
                    payload={"status": status.value, **details},
                )

        try:
            with session_scope(self._session_factory) as read_session:
                projects = ProjectRepository(read_session)
                audits = AuditRepository(read_session)
                project = projects.get_project(context.project_id)
                audit = audits.get_audit(context.audit_id)
                if project is None or audit is None:
                    raise RuntimeError("Audit project or audit record is missing")
                repository_root = project.repository_root
                repository_state_id = audit.repository_state_id

            result = await orchestrator.run(
                project_id=context.project_id,
                audit_id=context.audit_id,
                repository_state_id=repository_state_id,
                repository_root=repository_root,
                cancellation_token=context.cancellation_token,
                on_stage=on_stage,
            )
            context.cancellation_token.throw_if_cancelled()

            with session_scope(self._session_factory) as session:
                audits = AuditRepository(session)
                events = AuditEventRepository(session)
                current_audit = audits.get_audit(context.audit_id)
                base_summary = dict(current_audit.summary) if current_audit is not None else {}
                if not result.assembly.validation.auto_publish_allowed:
                    summary = {**base_summary, **self._pipeline_summary(result, snapshot_id=None)}
                    summary["warnings"] = [
                        *summary.get("warnings", []),
                        "GRAPH_VALIDATION_BLOCKED_PUBLICATION",
                    ]
                    audits.update_status(
                        audit_id=context.audit_id,
                        status=AuditStatus.COMPLETED_WITH_WARNINGS,
                        summary=summary,
                    )
                    events.append_event(
                        audit_id=context.audit_id,
                        event_type="AUDIT_COMPLETED",
                        message="Audit completed, but graph publication was blocked by validation",
                        payload={"published": False},
                    )
                    return

                published = GraphSnapshotRepository(session).publish_snapshot(result.assembly.snapshot)
                summary = {
                    **base_summary,
                    **self._pipeline_summary(result, snapshot_id=published.snapshot.snapshot_id),
                }
                terminal_status = (
                    AuditStatus.COMPLETED_WITH_WARNINGS
                    if result.warnings or result.issues or result.assembly.debug_candidates
                    else AuditStatus.COMPLETED
                )
                audits.update_status(
                    audit_id=context.audit_id,
                    status=terminal_status,
                    summary=summary,
                )
                events.append_event(
                    audit_id=context.audit_id,
                    event_type="AUDIT_COMPLETED",
                    message=f"Audit completed with status {terminal_status.value}",
                    payload={
                        "published": True,
                        "snapshot_id": published.snapshot.snapshot_id,
                        "node_count": len(result.assembly.snapshot.nodes),
                        "edge_count": len(result.assembly.snapshot.edges),
                    },
                )
        except Exception as exc:  # noqa: BLE001
            if context.cancellation_token.cancelled:
                self._mark_cancelled_after_start(context.audit_id)
                return
            self._mark_pipeline_failure(context.audit_id, exc)
            raise

    @staticmethod
    def _pipeline_summary(result, *, snapshot_id: str | None) -> dict[str, Any]:
        return {
            "pipeline": "real",
            "snapshot_id": snapshot_id,
            "unit_count": result.unit_count,
            "indexed_file_count": sum(1 for item in result.file_index.files if item.readable),
            "raw_candidate_count": result.raw_candidate_count,
            "normalized_candidate_count": result.normalized_candidate_count,
            "validated_candidate_count": result.validated_candidate_count,
            "published_node_count": len(result.assembly.snapshot.nodes),
            "published_edge_count": len(result.assembly.snapshot.edges),
            "review_candidate_count": len(result.assembly.debug_candidates),
            "issue_count": len(result.issues),
            "warnings": list(result.warnings),
        }

    def _mark_pipeline_failure(self, audit_id: str, exc: Exception) -> None:
        with session_scope(self._session_factory) as session:
            audits = AuditRepository(session)
            events = AuditEventRepository(session)
            audit = audits.get_audit(audit_id)
            if audit is None:
                return
            current = AuditStatus(audit.status)
            summary = dict(audit.summary)
            summary.update(
                {
                    "pipeline": "real",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
            if current in {AuditStatus.SCANNING, AuditStatus.DISCOVERING}:
                audits.update_status(audit_id=audit_id, status=AuditStatus.FAILED, summary=summary)
            else:
                # The current state machine models late-stage failures as partial results.
                if current in {AuditStatus.ANALYZING, AuditStatus.VALIDATING}:
                    audits.update_status(audit_id=audit_id, status=AuditStatus.PARTIAL, summary=summary)
                    audits.update_status(audit_id=audit_id, status=AuditStatus.ASSEMBLING, summary=summary)
                    audits.update_status(
                        audit_id=audit_id,
                        status=AuditStatus.COMPLETED_WITH_WARNINGS,
                        summary=summary,
                    )
                elif current == AuditStatus.ASSEMBLING:
                    audits.update_status(
                        audit_id=audit_id,
                        status=AuditStatus.COMPLETED_WITH_WARNINGS,
                        summary=summary,
                    )
            events.append_event(
                audit_id=audit_id,
                event_type="AUDIT_PIPELINE_FAILED",
                message="Audit pipeline failed",
                payload={"error_type": type(exc).__name__, "message": str(exc)},
            )

    def _mark_cancelled_after_start(self, audit_id: str) -> None:
        with session_scope(self._session_factory) as session:
            audits = AuditRepository(session)
            events = AuditEventRepository(session)
            audit = audits.get_audit(audit_id)
            if audit is None:
                return
            current = AuditStatus(audit.status)
            if current == AuditStatus.ANALYZING:
                audits.update_status(audit_id=audit_id, status=AuditStatus.CANCELLED)
                events.append_event(
                    audit_id=audit_id,
                    event_type="AUDIT_CANCELLED",
                    message="Audit cancelled",
                )

    def _mark_cancelled_if_possible(self, audit_id: str) -> None:
        with session_scope(self._session_factory) as session:
            audits = AuditRepository(session)
            events = AuditEventRepository(session)
            audit = audits.get_audit(audit_id)
            if audit is None or AuditStatus(audit.status) != AuditStatus.QUEUED:
                return
            audits.update_status(audit_id=audit_id, status=AuditStatus.CANCELLED)
            events.append_event(
                audit_id=audit_id,
                event_type="AUDIT_CANCELLED",
                message="Audit cancelled",
            )
