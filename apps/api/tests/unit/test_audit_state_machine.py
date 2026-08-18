import pytest

from app.domain.audit_state_machine import (
    ALLOWED_AUDIT_TRANSITIONS,
    AuditStateMachine,
    AuditStatusTransitionError,
)
from app.domain.enums import AuditStatus, ReasonCode


def test_audit_state_machine_allows_architecture_transitions() -> None:
    state_machine = AuditStateMachine()

    for current_status, allowed_next_statuses in ALLOWED_AUDIT_TRANSITIONS.items():
        for next_status in allowed_next_statuses:
            transition = state_machine.validate_transition(current_status, next_status)

            assert transition.current_status == current_status
            assert transition.next_status == next_status


def test_audit_state_machine_matches_architecture_status_diagram() -> None:
    assert ALLOWED_AUDIT_TRANSITIONS == {
        AuditStatus.QUEUED: frozenset({AuditStatus.SCANNING, AuditStatus.CANCELLED}),
        AuditStatus.SCANNING: frozenset(
            {AuditStatus.DISCOVERING, AuditStatus.FAILED, AuditStatus.INTERRUPTED}
        ),
        AuditStatus.DISCOVERING: frozenset(
            {AuditStatus.ANALYZING, AuditStatus.FAILED, AuditStatus.INTERRUPTED}
        ),
        AuditStatus.ANALYZING: frozenset(
            {
                AuditStatus.VALIDATING,
                AuditStatus.PARTIAL,
                AuditStatus.CANCELLED,
                AuditStatus.INTERRUPTED,
            }
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


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    [
        (AuditStatus.QUEUED, AuditStatus.ANALYZING),
        (AuditStatus.SCANNING, AuditStatus.ASSEMBLING),
        (AuditStatus.DISCOVERING, AuditStatus.COMPLETED),
        (AuditStatus.ANALYZING, AuditStatus.COMPLETED),
        (AuditStatus.ANALYZING, AuditStatus.FAILED),
        (AuditStatus.VALIDATING, AuditStatus.COMPLETED_WITH_WARNINGS),
        (AuditStatus.PARTIAL, AuditStatus.VALIDATING),
        (AuditStatus.ASSEMBLING, AuditStatus.VALIDATING),
    ],
)
def test_audit_state_machine_rejects_invalid_transitions(
    current_status: AuditStatus,
    next_status: AuditStatus,
) -> None:
    with pytest.raises(AuditStatusTransitionError) as exc_info:
        AuditStateMachine().validate_transition(current_status, next_status)

    assert exc_info.value.reason_code == ReasonCode.INVALID_AUDIT_STATUS_TRANSITION
    assert exc_info.value.current_status == current_status
    assert exc_info.value.next_status == next_status


@pytest.mark.parametrize(
    "terminal_status",
    [
        AuditStatus.COMPLETED,
        AuditStatus.COMPLETED_WITH_WARNINGS,
        AuditStatus.FAILED,
        AuditStatus.CANCELLED,
        AuditStatus.INTERRUPTED,
    ],
)
def test_audit_state_machine_terminal_states_are_immutable(
    terminal_status: AuditStatus,
) -> None:
    with pytest.raises(AuditStatusTransitionError) as exc_info:
        AuditStateMachine().validate_transition(terminal_status, AuditStatus.SCANNING)

    assert exc_info.value.reason_code == ReasonCode.INVALID_AUDIT_STATUS_TRANSITION
