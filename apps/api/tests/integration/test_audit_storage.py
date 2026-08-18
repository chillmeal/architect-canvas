from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.analysis.checkpoints import AuditCheckpointName, AuditCheckpointRecorder
from app.domain.enums import AuditStageName, AuditStatus
from app.infrastructure.db.repositories import (
    AuditEventRepository,
    AuditRepository,
    AuditStageRepository,
    AuditTerminalStateError,
    ProjectRepository,
    RepositoryStateRepository,
)
from app.infrastructure.db.session import (
    create_session_factory,
    create_sqlite_engine,
    session_scope,
)


def test_project_repository_state_and_audit_are_persisted(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)

    with session_scope(session_factory) as session:
        project = ProjectRepository(session).create_project(
            name="Payments",
            repository_root="/allowed/repos/payments",
            settings={"language": "python"},
        )
        repository_state = RepositoryStateRepository(session).create_repository_state(
            project_id=project.project_id,
            commit_sha="abc123",
            branch="main",
            dirty=True,
            tree_hash="tree-hash",
            metadata={"dirty_files": ["README.md"]},
        )
        audit = AuditRepository(session).create_audit(
            project_id=project.project_id,
            repository_state_id=repository_state.repository_state_id,
        )

    with session_scope(session_factory) as session:
        persisted_project = ProjectRepository(session).get_project(project.project_id)
        persisted_audit = AuditRepository(session).get_audit(audit.audit_id)

        assert persisted_project is not None
        assert persisted_project.settings == {"language": "python"}
        assert persisted_audit is not None
        assert persisted_audit.status == AuditStatus.QUEUED.value
        assert persisted_audit.repository_state.dirty is True
        assert persisted_audit.repository_state.metadata_json == {"dirty_files": ["README.md"]}


def test_audit_events_are_ordered_and_paginated(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    audit_id = create_audit_fixture(session_factory)

    with session_scope(session_factory) as session:
        events = AuditEventRepository(session)
        events.append_event(audit_id=audit_id, event_type="AUDIT_QUEUED", message="queued")
        events.append_event(
            audit_id=audit_id,
            event_type="STAGE_STARTED",
            message="scan started",
            stage_name=AuditStageName.SCANNING,
            payload={"files": 10},
        )
        events.append_event(audit_id=audit_id, event_type="STAGE_DONE", message="scan done")

    with session_scope(session_factory) as session:
        first_page = AuditEventRepository(session).list_events(audit_id=audit_id, limit=2)
        second_page = AuditEventRepository(session).list_events(
            audit_id=audit_id,
            offset=first_page.next_offset or 0,
            limit=2,
        )

        assert [event.sequence_number for event in first_page.events] == [1, 2]
        assert [event.message for event in first_page.events] == ["queued", "scan started"]
        assert first_page.next_offset == 2
        assert [event.sequence_number for event in second_page.events] == [3]
        assert second_page.next_offset is None


def test_audit_terminal_status_is_not_mutable(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    audit_id = create_audit_fixture(session_factory)

    with session_scope(session_factory) as session:
        audits = AuditRepository(session)
        audits.update_status(audit_id=audit_id, status=AuditStatus.SCANNING)
        audits.update_status(audit_id=audit_id, status=AuditStatus.DISCOVERING)
        audits.update_status(audit_id=audit_id, status=AuditStatus.ANALYZING)
        audits.update_status(audit_id=audit_id, status=AuditStatus.VALIDATING)
        audits.update_status(audit_id=audit_id, status=AuditStatus.ASSEMBLING)
        audit = audits.update_status(
            audit_id=audit_id,
            status=AuditStatus.COMPLETED,
            summary={"confirmed_edges": 1},
        )
        assert audit.completed_at is not None

    with pytest.raises(AuditTerminalStateError), session_scope(session_factory) as session:
        AuditRepository(session).update_status(
            audit_id=audit_id,
            status=AuditStatus.FAILED,
        )

    with session_scope(session_factory) as session:
        audit = AuditRepository(session).get_audit(audit_id)
        assert audit is not None
        assert audit.status == AuditStatus.COMPLETED.value
        assert audit.summary == {"confirmed_edges": 1}


def test_startup_recovery_marks_active_audits_interrupted(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    audit_id = create_audit_fixture(session_factory)

    with session_scope(session_factory) as session:
        audits = AuditRepository(session)
        audits.update_status(audit_id=audit_id, status=AuditStatus.SCANNING)

    with session_scope(session_factory) as session:
        interrupted_count = AuditRepository(session).interrupt_active_audits_on_startup()

        assert interrupted_count == 1

    with session_scope(session_factory) as session:
        audits = AuditRepository(session)
        audit = audits.get_audit(audit_id)

        assert audit is not None
        assert audit.status == AuditStatus.INTERRUPTED.value
        assert audit.summary == {"interrupted_reason": "BACKEND_RESTART"}
        assert audits.list_active_audits(project_id=audit.project_id) == ()


def test_checkpoint_recorder_persists_stage_and_event(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    audit_id = create_audit_fixture(session_factory)

    with session_scope(session_factory) as session:
        recorder = AuditCheckpointRecorder(
            stages=AuditStageRepository(session),
            events=AuditEventRepository(session),
        )
        recorder.record(
            audit_id=audit_id,
            checkpoint_name=AuditCheckpointName.ANALYSIS_UNITS_DETECTED,
            details={"units": 3},
        )

    with session_scope(session_factory) as session:
        events = AuditEventRepository(session).list_events(audit_id=audit_id).events

        assert len(events) == 1
        assert events[0].event_type == "CHECKPOINT_RECORDED"
        assert events[0].stage_name == AuditStageName.UNIT_DETECTION.value
        assert events[0].payload == {
            "checkpoint": AuditCheckpointName.ANALYSIS_UNITS_DETECTED.value,
            "units": 3,
        }


def test_audit_stage_upsert_preserves_single_stage_record(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    audit_id = create_audit_fixture(session_factory)

    with session_scope(session_factory) as session:
        stages = AuditStageRepository(session)
        started = stages.upsert_stage(
            audit_id=audit_id,
            stage_name=AuditStageName.SCANNING,
            status=AuditStatus.SCANNING,
            details={"files_seen": 1},
        )
        completed = stages.upsert_stage(
            audit_id=audit_id,
            stage_name=AuditStageName.SCANNING,
            status=AuditStatus.COMPLETED,
            details={"files_seen": 10},
        )

        assert completed.audit_stage_id == started.audit_stage_id
        assert completed.status == AuditStatus.COMPLETED.value
        assert completed.completed_at is not None
        assert completed.details == {"files_seen": 10}


def create_migrated_session_factory(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'storage.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_sqlite_engine(database_url)
    return create_session_factory(engine)


def create_audit_fixture(session_factory) -> str:
    with session_scope(session_factory) as session:
        project = ProjectRepository(session).create_project(
            name="Payments",
            repository_root="/allowed/repos/payments",
        )
        repository_state = RepositoryStateRepository(session).create_repository_state(
            project_id=project.project_id,
            tree_hash="tree-hash",
        )
        audit = AuditRepository(session).create_audit(
            project_id=project.project_id,
            repository_state_id=repository_state.repository_state_id,
        )
        return audit.audit_id
