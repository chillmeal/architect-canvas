import asyncio
from dataclasses import dataclass

import pytest

from app.infrastructure.queue.in_memory import (
    AuditJobCancelledError,
    AuditJobStatus,
    DuplicateActiveAuditError,
    InMemoryAuditQueue,
)


@pytest.mark.anyio
async def test_in_memory_queue_rejects_second_active_audit_for_project() -> None:
    queue = InMemoryAuditQueue(max_concurrency=1, job_timeout_seconds=1)
    release = asyncio.Event()

    async def wait_until_released(_context) -> None:
        await release.wait()

    first = await queue.submit(
        audit_id="audit-1",
        project_id="project-1",
        operation=wait_until_released,
    )

    with pytest.raises(DuplicateActiveAuditError):
        await queue.submit(
            audit_id="audit-2",
            project_id="project-1",
            operation=wait_until_released,
        )

    release.set()
    assert (await first.task).status == AuditJobStatus.SUCCEEDED


@pytest.mark.anyio
async def test_in_memory_queue_bounds_concurrency() -> None:
    queue = InMemoryAuditQueue(max_concurrency=1, job_timeout_seconds=1)
    state = QueueConcurrencyState()

    async def observed_job(_context) -> None:
        state.active += 1
        state.max_active = max(state.max_active, state.active)
        await asyncio.sleep(0.01)
        state.active -= 1

    first = await queue.submit(audit_id="audit-1", project_id="project-1", operation=observed_job)
    second = await queue.submit(audit_id="audit-2", project_id="project-2", operation=observed_job)

    assert (await first.task).status == AuditJobStatus.SUCCEEDED
    assert (await second.task).status == AuditJobStatus.SUCCEEDED
    assert state.max_active == 1


@pytest.mark.anyio
async def test_in_memory_queue_times_out_job_and_sets_cancellation_flag() -> None:
    queue = InMemoryAuditQueue(max_concurrency=1, job_timeout_seconds=0.01)

    async def slow_job(_context) -> None:
        await asyncio.sleep(1)

    handle = await queue.submit(
        audit_id="audit-1",
        project_id="project-1",
        operation=slow_job,
    )

    result = await handle.task

    assert result.status == AuditJobStatus.TIMED_OUT
    assert handle.cancellation_token.cancelled is True


@pytest.mark.anyio
async def test_in_memory_queue_exposes_cancellation_to_running_job() -> None:
    queue = InMemoryAuditQueue(max_concurrency=1, job_timeout_seconds=1)
    started = asyncio.Event()

    async def cancellable_job(context) -> None:
        started.set()
        while not context.cancellation_token.cancelled:
            await asyncio.sleep(0)
        context.cancellation_token.throw_if_cancelled()

    handle = await queue.submit(
        audit_id="audit-1",
        project_id="project-1",
        operation=cancellable_job,
    )
    await started.wait()

    assert await queue.cancel("audit-1") is True
    result = await handle.task

    assert result.status == AuditJobStatus.CANCELLED
    assert isinstance(result.error, AuditJobCancelledError)


@dataclass
class QueueConcurrencyState:
    active: int = 0
    max_active: int = 0
