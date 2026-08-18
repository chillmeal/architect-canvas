from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_app_config, get_llm_provider, get_session
from app.core.config import AppConfig
from app.infrastructure.db.models import ProjectRecord, RepositoryStateRecord
from app.infrastructure.llm import LlmProvider
from app.services.project_service import CreatedProject, ProjectPreflightResult, ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    repository_path: str = Field(min_length=1)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    settings: dict[str, Any] | None = None


class ProjectValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_path: str = Field(min_length=1)


class RepositoryStateResponse(BaseModel):
    commit_sha: str | None
    branch: str | None
    dirty: bool
    tree_hash: str
    non_git: bool


class ProjectResponse(BaseModel):
    project_id: str
    name: str
    repository_name: str
    is_archived: bool
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    repository_state: RepositoryStateResponse | None = None


class ProjectValidationResponse(BaseModel):
    ok: bool
    repository_name: str
    repository_state: RepositoryStateResponse
    provider_name: str | None
    models_available: int | None


def get_project_service(
    config: Annotated[AppConfig, Depends(get_app_config)],
    session: Annotated[Session, Depends(get_session)],
) -> ProjectService:
    return ProjectService(session=session, config=config)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: ProjectCreateRequest,
    config: Annotated[AppConfig, Depends(get_app_config)],
    session: Annotated[Session, Depends(get_session)],
    llm_provider: Annotated[LlmProvider, Depends(get_llm_provider)],
) -> ProjectResponse:
    service = ProjectService(session=session, config=config, llm_provider=llm_provider)
    created = await service.create_project(
        name=request.name,
        repository_path=request.repository_path,
        settings=request.settings,
    )
    return _created_project_response(created)


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    service: Annotated[ProjectService, Depends(get_project_service)],
    include_archived: bool = Query(default=False),
) -> list[ProjectResponse]:
    return [_project_response(project) for project in service.list_projects(include_archived=include_archived)]


@router.post("/{project_id}/validate", response_model=ProjectValidationResponse)
async def validate_project(
    project_id: str,
    request: ProjectValidateRequest,
    config: Annotated[AppConfig, Depends(get_app_config)],
    session: Annotated[Session, Depends(get_session)],
    llm_provider: Annotated[LlmProvider, Depends(get_llm_provider)],
) -> ProjectValidationResponse:
    ProjectService(session=session, config=config).get_project(project_id)
    service = ProjectService(session=session, config=config, llm_provider=llm_provider)
    preflight = await service.validate_project_repository(repository_path=request.repository_path)
    return _validation_response(preflight)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    return _project_response(service.get_project(project_id))


@router.patch("/{project_id}", response_model=ProjectResponse)
def patch_project(
    project_id: str,
    request: ProjectPatchRequest,
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    project = service.update_project(
        project_id=project_id,
        name=request.name,
        settings=request.settings,
    )
    return _project_response(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_project(
    project_id: str,
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> Response:
    service.archive_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _created_project_response(created: CreatedProject) -> ProjectResponse:
    return _project_response(created.project, repository_state=created.repository_state)


def _project_response(
    project: ProjectRecord,
    *,
    repository_state: RepositoryStateRecord | None = None,
) -> ProjectResponse:
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        repository_name=Path(project.repository_root).name,
        is_archived=project.is_archived,
        settings=project.settings,
        created_at=project.created_at,
        updated_at=project.updated_at,
        repository_state=_repository_state_response(repository_state),
    )


def _validation_response(preflight: ProjectPreflightResult) -> ProjectValidationResponse:
    return ProjectValidationResponse(
        ok=True,
        repository_name=preflight.repository_name,
        repository_state=RepositoryStateResponse(
            commit_sha=preflight.commit_sha,
            branch=preflight.branch,
            dirty=preflight.dirty,
            tree_hash=preflight.tree_hash,
            non_git=preflight.non_git,
        ),
        provider_name=preflight.provider_name,
        models_available=preflight.models_available,
    )


def _repository_state_response(
    repository_state: RepositoryStateRecord | None,
) -> RepositoryStateResponse | None:
    if repository_state is None:
        return None
    return RepositoryStateResponse(
        commit_sha=repository_state.commit_sha,
        branch=repository_state.branch,
        dirty=repository_state.dirty,
        tree_hash=repository_state.tree_hash,
        non_git=bool(repository_state.metadata_json.get("non_git")),
    )
