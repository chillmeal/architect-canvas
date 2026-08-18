from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import TERMINAL_AUDIT_STATUSES, AuditStatus, ReasonCode


class AuditStatusTransitionError(ValueError):
    def __init__(self, current_status: AuditStatus, next_status: AuditStatus) -> None:
        self.current_status = current_status
        self.next_status = next_status
        self.reason_code = ReasonCode.INVALID_AUDIT_STATUS_TRANSITION
        super().__init__(f"Invalid audit status transition: {current_status} -> {next_status}")


@dataclass(frozen=True)
class AuditStatusTransition:
    current_status: AuditStatus
    next_status: AuditStatus


ALLOWED_AUDIT_TRANSITIONS = {
    AuditStatus.QUEUED: frozenset({AuditStatus.SCANNING, AuditStatus.CANCELLED}),
    AuditStatus.SCANNING: frozenset({AuditStatus.DISCOVERING, AuditStatus.FAILED, AuditStatus.INTERRUPTED}),
    AuditStatus.DISCOVERING: frozenset(
        {AuditStatus.ANALYZING, AuditStatus.FAILED, AuditStatus.INTERRUPTED}
    ),
    AuditStatus.ANALYZING: frozenset(
        {AuditStatus.VALIDATING, AuditStatus.PARTIAL, AuditStatus.CANCELLED, AuditStatus.INTERRUPTED}
    ),
    AuditStatus.VALIDATING: frozenset(
        {AuditStatus.ASSEMBLING, AuditStatus.PARTIAL, AuditStatus.INTERRUPTED}
    ),
    AuditStatus.PARTIAL: frozenset({AuditStatus.ASSEMBLING}),
    AuditStatus.ASSEMBLING: frozenset(
        {AuditStatus.COMPLETED, AuditStatus.COMPLETED_WITH_WARNINGS}
    ),
    AuditStatus.COMPLETED: frozenset(),
    AuditStatus.COMPLETED_WITH_WARNINGS: frozenset(),
    AuditStatus.FAILED: frozenset(),
    AuditStatus.CANCELLED: frozenset(),
    AuditStatus.INTERRUPTED: frozenset(),
}


class AuditStateMachine:
    def can_transition(self, current_status: AuditStatus, next_status: AuditStatus) -> bool:
        return next_status in ALLOWED_AUDIT_TRANSITIONS[current_status]

    def validate_transition(
        self,
        current_status: AuditStatus,
        next_status: AuditStatus,
    ) -> AuditStatusTransition:
        if current_status in TERMINAL_AUDIT_STATUSES or current_status == AuditStatus.INTERRUPTED:
            raise AuditStatusTransitionError(current_status, next_status)
        if not self.can_transition(current_status, next_status):
            raise AuditStatusTransitionError(current_status, next_status)
        return AuditStatusTransition(current_status=current_status, next_status=next_status)
