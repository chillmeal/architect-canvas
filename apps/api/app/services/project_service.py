from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import AppConfig, ConfigError
from app.core.errors import AppError
from app.core.security import PathSafetyError, validate_repository_root
from app.domain.enums import AuditStatus
from app.infrastructure.db.models import ProjectRecord, RepositoryStateRecord
from app.infrastructure.db.repositories import (
    AuditRepository,
    ProjectRepository,
    RepositoryStateRepository,
)
from app.infrastructure.llm import LlmProvider
from app.infrastructure.repository.git_metadata import (
    GitMetadataError,
    GitMetadataReader,
    RepositoryGitMetadata,
)


class ProjectPreflightError(AppError):
    def __init__(self, failures: tuple[ProjectPreflightFailure, ...]) -> None:
        super().__init__(
            "PROJECT_PREFLIGHT_FAILED",
            "Project preflight validation failed",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            details={"failures": [failure.to_public_dict() for failure in failures]},
        )


@dataclass(frozen=True)
class ProjectPreflightFailure:
    category: str
    message: str

    def to_public_dict(self) -> dict[str, str]:
        return {"category": self.category, "message": self.message}


@dataclass(frozen=True)
class CreatedProject:
    project: ProjectRecord
    repository_state: RepositoryStateRecord


@dataclass(frozen=True)
class ProjectPreflightResult:
    repository_name: str
    commit_sha: str | None
    branch: str | None
    dirty: bool
    tree_hash: str
    non_git: bool
    provider_name: str | None
    models_available: int | None


class ProjectService:
    def __init__(
        self,
        *,
        session: Session,
        config: AppConfig,
        llm_provider: LlmProvider | None = None,
    ) -> None:
        self._session = session
        self._config = config
        self._llm_provider = llm_provider
        self._projects = ProjectRepository(session)
        self._repository_states = RepositoryStateRepository(session)
        self._audits = AuditRepository(session)

    async def create_project(
        self,
        *,
        name: str,
        repository_path: str,
        settings: dict[str, Any] | None = None,
    ) -> CreatedProject:
        root, git_metadata = await self._run_preflight(repository_path=repository_path)
        project = self._projects.create_project(
            name=name,
            repository_root=str(root),
            settings=settings,
        )
        repository_state = self._repository_states.create_repository_state(
            project_id=project.project_id,
            commit_sha=git_metadata.commit_sha,
            branch=git_metadata.branch,
            dirty=git_metadata.dirty,
            tree_hash=git_metadata.tree_hash,
            metadata={"non_git": git_metadata.non_git},
        )
        return CreatedProject(project=project, repository_state=repository_state)

    async def validate_project_repository(self, *, repository_path: str) -> ProjectPreflightResult:
        root, git_metadata = await self._run_preflight(repository_path=repository_path)
        provider_name: str | None = None
        models_available: int | None = None
        if self._llm_provider is not None:
            health = await self._llm_provider.health_check()
            provider_name = health.provider_name
            models_available = health.models_available
        return ProjectPreflightResult(
            repository_name=root.name,
            commit_sha=git_metadata.commit_sha,
            branch=git_metadata.branch,
            dirty=git_metadata.dirty,
            tree_hash=git_metadata.tree_hash,
            non_git=git_metadata.non_git,
            provider_name=provider_name,
            models_available=models_available,
        )

    def list_projects(self, *, include_archived: bool = False) -> tuple[ProjectRecord, ...]:
        return self._projects.list_projects(include_archived=include_archived)

    def get_project(self, project_id: str) -> ProjectRecord:
        project = self._projects.get_project(project_id)
        if project is None:
            raise AppError(
                "PROJECT_NOT_FOUND",
                "Project not found",
                status_code=HTTPStatus.NOT_FOUND,
            )
        return project

    def update_project(
        self,
        *,
        project_id: str,
        name: str | None,
        settings: dict[str, Any] | None,
    ) -> ProjectRecord:
        project = self.get_project(project_id)
        self._ensure_no_active_audit(project.project_id)
        return self._projects.update_project(project_id=project_id, name=name, settings=settings)

    def archive_project(self, project_id: str) -> ProjectRecord:
        project = self.get_project(project_id)
        self._ensure_no_active_audit(project.project_id)
        return self._projects.archive_project(project_id=project_id)

    async def _run_preflight(
        self,
        *,
        repository_path: str,
    ) -> tuple[Path, RepositoryGitMetadata]:
        failures: list[ProjectPreflightFailure] = []
        root: Path | None = None
        git_metadata: RepositoryGitMetadata | None = None

        try:
            root = validate_repository_root(
                repository_path,
                self._config.repository_allowed_roots,
            )
        except PathSafetyError as exc:
            failures.append(ProjectPreflightFailure("REPOSITORY_PATH", str(exc)))

        if root is not None:
            try:
                git_metadata = GitMetadataReader(
                    self._config.repository_allowed_roots,
                    allow_non_git=self._config.audit_allow_non_git,
                ).read(root)
                if self._config.audit_require_clean_git and git_metadata.dirty:
                    failures.append(
                        ProjectPreflightFailure(
                            "GIT_METADATA",
                            "Repository has uncommitted changes",
                        )
                    )
            except GitMetadataError as exc:
                failures.append(ProjectPreflightFailure("GIT_METADATA", str(exc)))

        try:
            self._check_database_writable()
        except Exception as exc:  # noqa: BLE001
            failures.append(ProjectPreflightFailure("DATABASE_WRITABLE", str(exc)))

        try:
            if self._llm_provider is None:
                raise ConfigError(["GIGACHAT_CREDENTIALS is required"])
            health = await self._llm_provider.health_check()
            if not health.ok:
                failures.append(
                    ProjectPreflightFailure(
                        "GIGACHAT_CONFIG",
                        health.message or "LLM provider health check failed",
                    )
                )
        except ConfigError as exc:
            failures.append(ProjectPreflightFailure("GIGACHAT_CONFIG", "; ".join(exc.errors)))
        except Exception as exc:  # noqa: BLE001
            failures.append(ProjectPreflightFailure("GIGACHAT_CONFIG", str(exc)))

        if failures:
            raise ProjectPreflightError(tuple(failures))
        if root is None or git_metadata is None:
            raise ProjectPreflightError(
                (ProjectPreflightFailure("PREFLIGHT", "Preflight did not produce repository state"),)
            )
        return root, git_metadata

    def _check_database_writable(self) -> None:
        self._session.execute(
            text("UPDATE projects SET updated_at = updated_at WHERE project_id = :project_id"),
            {"project_id": "__preflight_write_check__"},
        )

    def _ensure_no_active_audit(self, project_id: str) -> None:
        active_audits = self._audits.list_active_audits(project_id=project_id)
        if active_audits:
            raise AppError(
                "ACTIVE_AUDIT_CONFLICT",
                "Project has an active audit",
                status_code=HTTPStatus.CONFLICT,
                details={
                    "project_id": project_id,
                    "audit_ids": [audit.audit_id for audit in active_audits],
                    "statuses": [AuditStatus(audit.status).value for audit in active_audits],
                },
            )
