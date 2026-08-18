from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.audit_state_machine import AuditStateMachine, AuditStatusTransitionError
from app.domain.enums import TERMINAL_AUDIT_STATUSES, AuditStageName, AuditStatus
from app.infrastructure.db.models import (
    AuditEventRecord,
    AuditRecord,
    AuditStageRecord,
    ProjectRecord,
    RepositoryStateRecord,
)

ACTIVE_AUDIT_STATUSES = frozenset(
    status
    for status in AuditStatus
    if status not in TERMINAL_AUDIT_STATUSES and status != AuditStatus.INTERRUPTED
)


class AuditTerminalStateError(AuditStatusTransitionError):
    pass


@dataclass(frozen=True)
class AuditEventPage:
    events: tuple[AuditEventRecord, ...]
    next_offset: int | None


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_project(
        self,
        *,
        name: str,
        repository_root: str,
        settings: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> ProjectRecord:
        project = ProjectRecord(
            project_id=project_id or str(uuid4()),
            name=name,
            repository_root=repository_root,
            settings=settings or {},
        )
        self.session.add(project)
        self.session.flush()
        return project

    def get_project(self, project_id: str) -> ProjectRecord | None:
        return self.session.get(ProjectRecord, project_id)

    def list_projects(self, *, include_archived: bool = False) -> tuple[ProjectRecord, ...]:
        query = select(ProjectRecord)
        if not include_archived:
            query = query.where(ProjectRecord.is_archived.is_(False))
        return tuple(self.session.scalars(query.order_by(ProjectRecord.created_at)).all())

    def update_project(
        self,
        *,
        project_id: str,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ProjectRecord:
        project = self.get_project(project_id)
        if project is None:
            raise LookupError(f"Project not found: {project_id}")
        if name is not None:
            project.name = name
        if settings is not None:
            project.settings = settings
        project.updated_at = datetime.now(UTC)
        self.session.flush()
        return project

    def archive_project(self, *, project_id: str) -> ProjectRecord:
        project = self.get_project(project_id)
        if project is None:
            raise LookupError(f"Project not found: {project_id}")
        project.is_archived = True
        project.updated_at = datetime.now(UTC)
        self.session.flush()
        return project


class RepositoryStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_repository_state(
        self,
        *,
        project_id: str,
        tree_hash: str,
        commit_sha: str | None = None,
        branch: str | None = None,
        dirty: bool = False,
        metadata: dict[str, Any] | None = None,
        repository_state_id: str | None = None,
    ) -> RepositoryStateRecord:
        repository_state = RepositoryStateRecord(
            repository_state_id=repository_state_id or str(uuid4()),
            project_id=project_id,
            commit_sha=commit_sha,
            branch=branch,
            dirty=dirty,
            tree_hash=tree_hash,
            metadata_json=metadata or {},
        )
        self.session.add(repository_state)
        self.session.flush()
        return repository_state


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_audit(
        self,
        *,
        project_id: str,
        repository_state_id: str,
        status: AuditStatus = AuditStatus.QUEUED,
        summary: dict[str, Any] | None = None,
        audit_id: str | None = None,
    ) -> AuditRecord:
        audit = AuditRecord(
            audit_id=audit_id or str(uuid4()),
            project_id=project_id,
            repository_state_id=repository_state_id,
            status=status.value,
            summary=summary or {},
        )
        self.session.add(audit)
        self.session.flush()
        return audit

    def get_audit(self, audit_id: str) -> AuditRecord | None:
        return self.session.get(AuditRecord, audit_id)

    def list_project_audits(self, *, project_id: str) -> tuple[AuditRecord, ...]:
        return tuple(
            self.session.scalars(
                select(AuditRecord)
                .where(AuditRecord.project_id == project_id)
                .order_by(AuditRecord.created_at.desc())
            ).all()
        )

    def find_by_idempotency_key(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> AuditRecord | None:
        return self.session.scalar(
            select(AuditRecord)
            .where(AuditRecord.project_id == project_id)
            .where(AuditRecord.summary["idempotency_key"].as_string() == idempotency_key)
            .order_by(AuditRecord.created_at.desc())
            .limit(1)
        )

    def list_active_audits(self, *, project_id: str | None = None) -> tuple[AuditRecord, ...]:
        query = select(AuditRecord).where(
            AuditRecord.status.in_([status.value for status in ACTIVE_AUDIT_STATUSES])
        )
        if project_id is not None:
            query = query.where(AuditRecord.project_id == project_id)
        return tuple(self.session.scalars(query.order_by(AuditRecord.created_at)).all())

    def interrupt_active_audits_on_startup(self) -> int:
        interrupted_count = 0
        now = datetime.now(UTC)
        for audit in self.list_active_audits():
            audit.status = AuditStatus.INTERRUPTED.value
            audit.updated_at = now
            audit.summary = {
                **audit.summary,
                "interrupted_reason": "BACKEND_RESTART",
            }
            interrupted_count += 1
        self.session.flush()
        return interrupted_count

    def update_status(
        self,
        *,
        audit_id: str,
        status: AuditStatus,
        summary: dict[str, Any] | None = None,
    ) -> AuditRecord:
        audit = self.session.get(AuditRecord, audit_id)
        if audit is None:
            raise LookupError(f"Audit not found: {audit_id}")
        current_status = AuditStatus(audit.status)
        try:
            AuditStateMachine().validate_transition(current_status, status)
        except AuditStatusTransitionError as exc:
            if current_status in TERMINAL_AUDIT_STATUSES:
                raise AuditTerminalStateError(current_status, status) from exc
            raise
        audit.status = status.value
        audit.updated_at = datetime.now(UTC)
        if summary is not None:
            audit.summary = summary
        if status in TERMINAL_AUDIT_STATUSES:
            audit.completed_at = datetime.now(UTC)
        self.session.flush()
        return audit


class AuditStageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_stage(
        self,
        *,
        audit_id: str,
        stage_name: AuditStageName,
        status: AuditStatus,
        details: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> AuditStageRecord:
        stage = self.session.scalar(
            select(AuditStageRecord).where(
                AuditStageRecord.audit_id == audit_id,
                AuditStageRecord.stage_name == stage_name.value,
            )
        )
        now = datetime.now(UTC)
        if stage is None:
            stage = AuditStageRecord(
                audit_stage_id=str(uuid4()),
                audit_id=audit_id,
                stage_name=stage_name.value,
                status=status.value,
                started_at=now,
                details=details or {},
                error_code=error_code,
            )
            self.session.add(stage)
        else:
            stage.status = status.value
            stage.details = details or stage.details
            stage.error_code = error_code
        if status in TERMINAL_AUDIT_STATUSES:
            stage.completed_at = now
        self.session.flush()
        return stage


class AuditEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append_event(
        self,
        *,
        audit_id: str,
        event_type: str,
        message: str,
        stage_name: AuditStageName | None = None,
        payload: dict[str, Any] | None = None,
        audit_event_id: str | None = None,
    ) -> AuditEventRecord:
        next_sequence = self._next_sequence_number(audit_id)
        event = AuditEventRecord(
            audit_event_id=audit_event_id or str(uuid4()),
            audit_id=audit_id,
            sequence_number=next_sequence,
            event_type=event_type,
            message=message,
            stage_name=stage_name.value if stage_name else None,
            payload=payload or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_events(
        self,
        *,
        audit_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> AuditEventPage:
        events = tuple(
            self.session.scalars(
                select(AuditEventRecord)
                .where(AuditEventRecord.audit_id == audit_id)
                .order_by(AuditEventRecord.sequence_number)
                .offset(offset)
                .limit(limit)
            ).all()
        )
        next_offset = offset + len(events) if len(events) == limit else None
        return AuditEventPage(events=events, next_offset=next_offset)

    def _next_sequence_number(self, audit_id: str) -> int:
        current_max = self.session.scalar(
            select(func.max(AuditEventRecord.sequence_number)).where(
                AuditEventRecord.audit_id == audit_id
            )
        )
        return int(current_max or 0) + 1
