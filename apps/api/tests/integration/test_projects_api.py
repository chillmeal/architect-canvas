import subprocess
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import AppConfig
from app.domain.enums import AuditStatus
from app.infrastructure.db.repositories import (
    AuditRepository,
    ProjectRepository,
    RepositoryStateRepository,
)
from app.infrastructure.db.session import session_scope
from app.infrastructure.llm import FakeLlmProvider
from app.main import create_app
from app.services.project_service import ProjectService


def test_projects_api_create_list_get_patch_and_archive(tmp_path: Path) -> None:
    repository = init_git_repository(tmp_path / "repo")
    (repository / "README.md").write_text("hello\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "initial")
    client = make_client(tmp_path)

    create_response = client.post(
        "/api/v1/projects",
        json={
            "name": "Payments",
            "repository_path": str(repository),
            "settings": {"domain": "payments"},
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == "Payments"
    assert created["repository_name"] == "repo"
    assert created["settings"] == {"domain": "payments"}
    assert created["repository_state"]["commit_sha"] == git(repository, "rev-parse", "HEAD")
    assert created["repository_state"]["dirty"] is False
    assert str(repository) not in create_response.text

    project_id = created["project_id"]
    list_response = client.get("/api/v1/projects")
    get_response = client.get(f"/api/v1/projects/{project_id}")
    patch_response = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Payments Core", "settings": {"domain": "core"}},
    )
    archive_response = client.delete(f"/api/v1/projects/{project_id}")
    list_after_archive_response = client.get("/api/v1/projects")

    assert list_response.status_code == 200
    assert [project["project_id"] for project in list_response.json()] == [project_id]
    assert get_response.status_code == 200
    assert get_response.json()["project_id"] == project_id
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] == "Payments Core"
    assert archive_response.status_code == 204
    assert list_after_archive_response.status_code == 200
    assert list_after_archive_response.json() == []


def test_projects_api_preflight_rejects_path_outside_allowlist(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    client = make_client(tmp_path, allowed_roots=(allowed,))

    response = client.post(
        "/api/v1/projects",
        json={"name": "Outside", "repository_path": str(outside)},
    )

    assert_preflight_failure(response, "REPOSITORY_PATH")


def test_projects_api_validate_preflights_existing_project_repository(tmp_path: Path) -> None:
    repository = init_git_repository(tmp_path / "repo")
    (repository / "README.md").write_text("hello\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "initial")
    client = make_client(tmp_path)
    project_id = client.post(
        "/api/v1/projects",
        json={"name": "Payments", "repository_path": str(repository)},
    ).json()["project_id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/validate",
        json={"repository_path": str(repository)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["repository_name"] == "repo"
    assert body["repository_state"]["commit_sha"] == git(repository, "rev-parse", "HEAD")
    assert body["provider_name"] == "fake"


def test_projects_api_preflight_rejects_non_git_without_flag(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/projects",
        json={"name": "Non Git", "repository_path": str(repository)},
    )

    assert_preflight_failure(response, "GIT_METADATA")


def test_projects_api_preflight_rejects_unhealthy_llm_provider(tmp_path: Path) -> None:
    repository = init_git_repository(tmp_path / "repo")
    (repository / "README.md").write_text("hello\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "initial")
    client = make_client(tmp_path, llm_provider=FakeLlmProvider(healthy=False))

    response = client.post(
        "/api/v1/projects",
        json={"name": "LLM Down", "repository_path": str(repository)},
    )

    assert_preflight_failure(response, "GIGACHAT_CONFIG")


def test_projects_api_preflight_rejects_dirty_repo_when_clean_git_required(
    tmp_path: Path,
) -> None:
    repository = init_git_repository(tmp_path / "repo")
    (repository / "README.md").write_text("hello\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "initial")
    (repository / "README.md").write_text("changed\n", encoding="utf-8")
    client = make_client(tmp_path, audit_require_clean_git=True)

    response = client.post(
        "/api/v1/projects",
        json={"name": "Dirty", "repository_path": str(repository)},
    )

    assert_preflight_failure(response, "GIT_METADATA")


def test_projects_api_preflight_reports_database_writable_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = init_git_repository(tmp_path / "repo")
    (repository / "README.md").write_text("hello\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "initial")

    def fail_database_check(_service: ProjectService) -> None:
        raise RuntimeError("database is read-only")

    monkeypatch.setattr(ProjectService, "_check_database_writable", fail_database_check)
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/projects",
        json={"name": "DB Failure", "repository_path": str(repository)},
    )

    assert_preflight_failure(response, "DATABASE_WRITABLE")


def test_projects_api_rejects_patch_during_active_audit(tmp_path: Path) -> None:
    session_factory = create_migrated_session_factory(tmp_path)
    config = AppConfig(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        repository_allowed_roots=(tmp_path,),
        audit_allow_non_git=True,
    )
    with session_scope(session_factory) as session:
        project = ProjectRepository(session).create_project(
            name="Payments",
            repository_root=str(tmp_path / "repo"),
        )
        repository_state = RepositoryStateRepository(session).create_repository_state(
            project_id=project.project_id,
            tree_hash="tree-hash",
        )
        AuditRepository(session).create_audit(
            project_id=project.project_id,
            repository_state_id=repository_state.repository_state_id,
            status=AuditStatus.SCANNING,
        )
        project_id = project.project_id
    client = TestClient(create_app(config=config, llm_provider=FakeLlmProvider()))

    response = client.patch(f"/api/v1/projects/{project_id}", json={"name": "Blocked"})

    assert response.status_code == 409
    assert response.json()["error_code"] == "ACTIVE_AUDIT_CONFLICT"


def make_client(
    tmp_path: Path,
    *,
    allowed_roots: tuple[Path, ...] | None = None,
    llm_provider: FakeLlmProvider | None = None,
    audit_require_clean_git: bool = False,
) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'api.db'}"
    run_migrations(database_url)
    config = AppConfig(
        app_env="test",
        database_url=database_url,
        repository_allowed_roots=allowed_roots or (tmp_path,),
        audit_require_clean_git=audit_require_clean_git,
    )
    return TestClient(create_app(config=config, llm_provider=llm_provider or FakeLlmProvider()))


def create_migrated_session_factory(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'api.db'}"
    run_migrations(database_url)
    app = create_app(
        config=AppConfig(
            app_env="test",
            database_url=database_url,
            repository_allowed_roots=(tmp_path,),
        ),
        llm_provider=FakeLlmProvider(),
    )
    return app.state.session_factory


def run_migrations(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def assert_preflight_failure(response, category: str) -> None:
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "PROJECT_PREFLIGHT_FAILED"
    assert category in {failure["category"] for failure in body["details"]["failures"]}


def init_git_repository(repository: Path) -> Path:
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.invalid")
    git(repository, "config", "user.name", "Test User")
    return repository


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    return result.stdout.strip()
