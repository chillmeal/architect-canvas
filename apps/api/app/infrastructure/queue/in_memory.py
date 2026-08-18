from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum


class AuditQueueError(RuntimeError):
    pass


class DuplicateActiveAuditError(AuditQueueError):
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"Project already has an active audit: {project_id}")


class AuditJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class AuditCancellationToken:
    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def throw_if_cancelled(self) -> None:
        if self._cancelled:
            raise AuditJobCancelledError("Audit job was cancelled")


class AuditJobCancelledError(AuditQueueError):
    pass


@dataclass(frozen=True)
class AuditJobContext:
    audit_id: str
    project_id: str
    cancellation_token: AuditCancellationToken


@dataclass(frozen=True)
class AuditJobResult:
    audit_id: str
    project_id: str
    status: AuditJobStatus
    error: BaseException | None = None


@dataclass(frozen=True)
class AuditJobHandle:
    audit_id: str
    project_id: str
    cancellation_token: AuditCancellationToken
    task: asyncio.Task[AuditJobResult]


AuditJobOperation = Callable[[AuditJobContext], Awaitable[None]]


class InMemoryAuditQueue:
    def __init__(self, *, max_concurrency: int, job_timeout_seconds: float) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if job_timeout_seconds <= 0:
            raise ValueError("job_timeout_seconds must be positive")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._job_timeout_seconds = job_timeout_seconds
        self._lock = asyncio.Lock()
        self._jobs_by_audit_id: dict[str, AuditJobHandle] = {}
        self._audit_id_by_project_id: dict[str, str] = {}

    async def submit(
        self,
        *,
        audit_id: str,
        project_id: str,
        operation: AuditJobOperation,
    ) -> AuditJobHandle:
        async with self._lock:
            if project_id in self._audit_id_by_project_id:
                raise DuplicateActiveAuditError(project_id)
            cancellation_token = AuditCancellationToken()
            context = AuditJobContext(
                audit_id=audit_id,
                project_id=project_id,
                cancellation_token=cancellation_token,
            )
            task = asyncio.create_task(self._run(context, operation))
            handle = AuditJobHandle(
                audit_id=audit_id,
                project_id=project_id,
                cancellation_token=cancellation_token,
                task=task,
            )
            self._jobs_by_audit_id[audit_id] = handle
            self._audit_id_by_project_id[project_id] = audit_id
            task.add_done_callback(lambda _task: asyncio.create_task(self._forget(audit_id, project_id)))
            return handle

    async def cancel(self, audit_id: str) -> bool:
        async with self._lock:
            handle = self._jobs_by_audit_id.get(audit_id)
            if handle is None:
                return False
            handle.cancellation_token.cancel()
            return True

    async def active_audit_id_for_project(self, project_id: str) -> str | None:
        async with self._lock:
            return self._audit_id_by_project_id.get(project_id)

    async def _run(
        self,
        context: AuditJobContext,
        operation: AuditJobOperation,
    ) -> AuditJobResult:
        async with self._semaphore:
            if context.cancellation_token.cancelled:
                return AuditJobResult(
                    audit_id=context.audit_id,
                    project_id=context.project_id,
                    status=AuditJobStatus.CANCELLED,
                )
            try:
                await asyncio.wait_for(operation(context), timeout=self._job_timeout_seconds)
            except TimeoutError as exc:
                context.cancellation_token.cancel()
                return AuditJobResult(
                    audit_id=context.audit_id,
                    project_id=context.project_id,
                    status=AuditJobStatus.TIMED_OUT,
                    error=exc,
                )
            except AuditJobCancelledError as exc:
                context.cancellation_token.cancel()
                return AuditJobResult(
                    audit_id=context.audit_id,
                    project_id=context.project_id,
                    status=AuditJobStatus.CANCELLED,
                    error=exc,
                )
            except Exception as exc:  # noqa: BLE001
                return AuditJobResult(
                    audit_id=context.audit_id,
                    project_id=context.project_id,
                    status=AuditJobStatus.FAILED,
                    error=exc,
                )
            if context.cancellation_token.cancelled:
                return AuditJobResult(
                    audit_id=context.audit_id,
                    project_id=context.project_id,
                    status=AuditJobStatus.CANCELLED,
                )
            return AuditJobResult(
                audit_id=context.audit_id,
                project_id=context.project_id,
                status=AuditJobStatus.SUCCEEDED,
            )

    async def _forget(self, audit_id: str, project_id: str) -> None:
        async with self._lock:
            self._jobs_by_audit_id.pop(audit_id, None)
            if self._audit_id_by_project_id.get(project_id) == audit_id:
                self._audit_id_by_project_id.pop(project_id, None)
