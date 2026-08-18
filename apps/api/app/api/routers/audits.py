from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    get_app_config,
    get_audit_queue,
    get_llm_provider,
    get_session,
    get_session_factory,
)
from app.core.config import AppConfig
from app.infrastructure.db.models import AuditEventRecord, AuditRecord
from app.infrastructure.queue.in_memory import InMemoryAuditQueue
from app.infrastructure.llm import LlmProvider
from app.services.audit_service import AuditService

router = APIRouter(tags=["audits"])


class AuditRepositoryStateResponse(BaseModel):
    commit_sha: str | None
    branch: str | None
    dirty: bool
    tree_hash: str
    non_git: bool


class AuditResponse(BaseModel):
    audit_id: str
    project_id: str
    status: str
    summary: dict[str, Any]
    repository_state: AuditRepositoryStateResponse
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AuditEventResponse(BaseModel):
    sequence_number: int
    event_type: str
    message: str
    stage_name: str | None
    payload: dict[str, Any]
    created_at: datetime


class AuditEventPageResponse(BaseModel):
    events: list[AuditEventResponse]
    next_offset: int | None


class AuditRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str | None = Field(default=None, max_length=128)


class AuditIssuePageResponse(BaseModel):
    issues: list[dict[str, Any]]
    next_offset: int | None


def get_audit_service(
    config: Annotated[AppConfig, Depends(get_app_config)],
    session: Annotated[Session, Depends(get_session)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    audit_queue: Annotated[InMemoryAuditQueue, Depends(get_audit_queue)],
    llm_provider: Annotated[LlmProvider, Depends(get_llm_provider)],
) -> AuditService:
    return AuditService(
        session=session,
        session_factory=session_factory,
        config=config,
        audit_queue=audit_queue,
        llm_provider=llm_provider,
    )


@router.post(
    "/projects/{project_id}/audits",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_audit(
    project_id: str,
    response: Response,
    service: Annotated[AuditService, Depends(get_audit_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuditResponse:
    started = await service.start_audit(
        project_id=project_id,
        idempotency_key=idempotency_key,
    )
    if started.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return _audit_response(started.audit)


@router.get("/projects/{project_id}/audits", response_model=list[AuditResponse])
def list_project_audits(
    project_id: str,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> list[AuditResponse]:
    return [_audit_response(audit) for audit in service.list_project_audits(project_id=project_id)]


@router.get("/audits/{audit_id}", response_model=AuditResponse)
def get_audit(
    audit_id: str,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuditResponse:
    return _audit_response(service.get_audit(audit_id))


@router.get("/audits/{audit_id}/events")
def stream_audit_events(
    audit_id: str,
    service: Annotated[AuditService, Depends(get_audit_service)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> StreamingResponse:
    page = service.list_events(audit_id=audit_id, offset=offset, limit=limit)

    def event_stream():
        for event in page.events:
            yield _sse_event(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/audits/{audit_id}/events/page", response_model=AuditEventPageResponse)
def list_audit_events_page(
    audit_id: str,
    service: Annotated[AuditService, Depends(get_audit_service)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> AuditEventPageResponse:
    page = service.list_events(audit_id=audit_id, offset=offset, limit=limit)
    return AuditEventPageResponse(
        events=[_event_response(event) for event in page.events],
        next_offset=page.next_offset,
    )


@router.post("/audits/{audit_id}/cancel", response_model=AuditResponse)
async def cancel_audit(
    audit_id: str,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuditResponse:
    return _audit_response(await service.cancel_audit(audit_id))


@router.post("/audits/{audit_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_audit(
    audit_id: str,
    request: AuditRetryRequest,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    service.retry_audit(audit_id, scope=request.scope)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.get("/audits/{audit_id}/issues", response_model=AuditIssuePageResponse)
def list_audit_issues(
    audit_id: str,
    service: Annotated[AuditService, Depends(get_audit_service)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> AuditIssuePageResponse:
    page = service.list_issues(audit_id=audit_id, offset=offset, limit=limit)
    return AuditIssuePageResponse(issues=list(page.issues), next_offset=page.next_offset)


def _audit_response(audit: AuditRecord) -> AuditResponse:
    return AuditResponse(
        audit_id=audit.audit_id,
        project_id=audit.project_id,
        status=audit.status,
        summary=audit.summary,
        repository_state=AuditRepositoryStateResponse(
            commit_sha=audit.repository_state.commit_sha,
            branch=audit.repository_state.branch,
            dirty=audit.repository_state.dirty,
            tree_hash=audit.repository_state.tree_hash,
            non_git=bool(audit.repository_state.metadata_json.get("non_git")),
        ),
        created_at=audit.created_at,
        updated_at=audit.updated_at,
        completed_at=audit.completed_at,
    )


def _event_response(event: AuditEventRecord) -> AuditEventResponse:
    return AuditEventResponse(
        sequence_number=event.sequence_number,
        event_type=event.event_type,
        message=event.message,
        stage_name=event.stage_name,
        payload=event.payload,
        created_at=event.created_at,
    )


def _sse_event(event: AuditEventRecord) -> str:
    payload = _event_response(event).model_dump(mode="json")
    return f"event: {event.event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
