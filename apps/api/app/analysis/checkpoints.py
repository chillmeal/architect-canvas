from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.enums import AuditStageName, AuditStatus
from app.infrastructure.db.repositories import AuditEventRepository, AuditStageRepository


class AuditCheckpointName(StrEnum):
    REPOSITORY_STATE_RECORDED = "REPOSITORY_STATE_RECORDED"
    SCANNER_COMPLETED = "SCANNER_COMPLETED"
    ANALYSIS_UNITS_DETECTED = "ANALYSIS_UNITS_DETECTED"
    DISCOVERY_COMPLETED = "DISCOVERY_COMPLETED"
    ANALYSIS_UNIT_COMPLETED = "ANALYSIS_UNIT_COMPLETED"
    DETERMINISTIC_VALIDATION_COMPLETED = "DETERMINISTIC_VALIDATION_COMPLETED"
    LLM_VALIDATION_COMPLETED = "LLM_VALIDATION_COMPLETED"
    GRAPH_SNAPSHOT_SAVED = "GRAPH_SNAPSHOT_SAVED"


@dataclass(frozen=True)
class AuditCheckpoint:
    name: AuditCheckpointName
    stage_name: AuditStageName


CHECKPOINTS: dict[AuditCheckpointName, AuditCheckpoint] = {
    AuditCheckpointName.REPOSITORY_STATE_RECORDED: AuditCheckpoint(
        name=AuditCheckpointName.REPOSITORY_STATE_RECORDED,
        stage_name=AuditStageName.PREFLIGHT,
    ),
    AuditCheckpointName.SCANNER_COMPLETED: AuditCheckpoint(
        name=AuditCheckpointName.SCANNER_COMPLETED,
        stage_name=AuditStageName.SCANNING,
    ),
    AuditCheckpointName.ANALYSIS_UNITS_DETECTED: AuditCheckpoint(
        name=AuditCheckpointName.ANALYSIS_UNITS_DETECTED,
        stage_name=AuditStageName.UNIT_DETECTION,
    ),
    AuditCheckpointName.DISCOVERY_COMPLETED: AuditCheckpoint(
        name=AuditCheckpointName.DISCOVERY_COMPLETED,
        stage_name=AuditStageName.DISCOVERING,
    ),
    AuditCheckpointName.ANALYSIS_UNIT_COMPLETED: AuditCheckpoint(
        name=AuditCheckpointName.ANALYSIS_UNIT_COMPLETED,
        stage_name=AuditStageName.ANALYZING,
    ),
    AuditCheckpointName.DETERMINISTIC_VALIDATION_COMPLETED: AuditCheckpoint(
        name=AuditCheckpointName.DETERMINISTIC_VALIDATION_COMPLETED,
        stage_name=AuditStageName.DETERMINISTIC_VALIDATION,
    ),
    AuditCheckpointName.LLM_VALIDATION_COMPLETED: AuditCheckpoint(
        name=AuditCheckpointName.LLM_VALIDATION_COMPLETED,
        stage_name=AuditStageName.LLM_VALIDATION,
    ),
    AuditCheckpointName.GRAPH_SNAPSHOT_SAVED: AuditCheckpoint(
        name=AuditCheckpointName.GRAPH_SNAPSHOT_SAVED,
        stage_name=AuditStageName.SNAPSHOT_PERSISTENCE,
    ),
}


class AuditCheckpointRecorder:
    def __init__(
        self,
        *,
        stages: AuditStageRepository,
        events: AuditEventRepository,
    ) -> None:
        self._stages = stages
        self._events = events

    def record(
        self,
        *,
        audit_id: str,
        checkpoint_name: AuditCheckpointName,
        details: dict[str, Any] | None = None,
    ) -> None:
        checkpoint = CHECKPOINTS[checkpoint_name]
        checkpoint_details = {"checkpoint": checkpoint_name.value, **(details or {})}
        self._stages.upsert_stage(
            audit_id=audit_id,
            stage_name=checkpoint.stage_name,
            status=AuditStatus.COMPLETED,
            details=checkpoint_details,
        )
        self._events.append_event(
            audit_id=audit_id,
            event_type="CHECKPOINT_RECORDED",
            message=checkpoint_name.value,
            stage_name=checkpoint.stage_name,
            payload=checkpoint_details,
        )
