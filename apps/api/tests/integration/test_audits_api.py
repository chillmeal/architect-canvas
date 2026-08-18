import subprocess
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import AppConfig
from app.infrastructure.llm import FakeLlmProvider
from app.main import create_app


def test_audits_api_start_is_idempotent_and_history_is_project_scoped(tmp_path: Path) -> None:
    repository = create_committed_repository(tmp_path / "repo")
    with make_client(tmp_path) as client:
        project_id = create_project(client, repository)

        first = client.post(
            f"/api/v1/projects/{project_id}/audits",
            headers={"Idempotency-Key": "audit-key-1"},
        )
        second = client.post(
            f"/api/v1/projects/{project_id}/audits",
            headers={"Idempotency-Key": "audit-key-1"},
        )
        history = client.get(f"/api/v1/projects/{project_id}/audits")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["audit_id"] == second.json()["audit_id"]
    assert history.status_code == 200
    assert [audit["audit_id"] for audit in history.json()] == [first.json()["audit_id"]]


def test_audits_api_streams_events_as_sse_in_sequence_order(tmp_path: Path) -> None:
    repository = create_committed_repository(tmp_path / "repo")
    with make_client(tmp_path) as client:
        project_id = create_project(client, repository)
        audit = client.post(f"/api/v1/projects/{project_id}/audits").json()

        events_page = client.get(f"/api/v1/audits/{audit['audit_id']}/events/page")
        sse_response = client.get(f"/api/v1/audits/{audit['audit_id']}/events")

    assert events_page.status_code == 200
    sequences = [event["sequence_number"] for event in events_page.json()["events"]]
    assert sequences == list(range(1, len(sequences) + 1))
    assert events_page.json()["events"][0]["event_type"] == "AUDIT_QUEUED"
    assert sse_response.status_code == 200
    assert sse_response.headers["content-type"].startswith("text/event-stream")
    assert "event: AUDIT_QUEUED" in sse_response.text
    assert '"sequence_number": 1' in sse_response.text


def test_audits_api_cancel_marks_queued_audit_cancelled(tmp_path: Path) -> None:
    repository = create_committed_repository(tmp_path / "repo")
    with make_client(tmp_path) as client:
        project_id = create_project(client, repository)
        audit = client.post(f"/api/v1/projects/{project_id}/audits").json()

        cancel_response = client.post(f"/api/v1/audits/{audit['audit_id']}/cancel")
        status_response = client.get(f"/api/v1/audits/{audit['audit_id']}")

    if cancel_response.status_code == 200:
        assert cancel_response.json()["status"] == "CANCELLED"
        assert status_response.json()["status"] == "CANCELLED"
    else:
        # The real pipeline may finish before an immediate cancellation request reaches it.
        assert cancel_response.status_code == 409
        assert status_response.json()["status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}


def test_audits_api_retry_rejects_non_retryable_status(tmp_path: Path) -> None:
    repository = create_committed_repository(tmp_path / "repo")
    with make_client(tmp_path) as client:
        project_id = create_project(client, repository)
        audit = client.post(f"/api/v1/projects/{project_id}/audits").json()

        retry_response = client.post(
            f"/api/v1/audits/{audit['audit_id']}/retry",
            json={"scope": "failed-unit"},
        )

    assert retry_response.status_code == 409
    assert retry_response.json()["error_code"] == "AUDIT_RETRY_NOT_ALLOWED"


def test_audits_api_issues_are_paginated_empty_until_issue_store_exists(tmp_path: Path) -> None:
    repository = create_committed_repository(tmp_path / "repo")
    with make_client(tmp_path) as client:
        project_id = create_project(client, repository)
        audit = client.post(f"/api/v1/projects/{project_id}/audits").json()

        response = client.get(f"/api/v1/audits/{audit['audit_id']}/issues?offset=0&limit=10")

    assert response.status_code == 200
    assert response.json() == {"issues": [], "next_offset": None}


def make_client(tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'api.db'}"
    run_migrations(database_url)
    config = AppConfig(
        app_env="test",
        database_url=database_url,
        repository_allowed_roots=(tmp_path,),
    )
    return TestClient(create_app(config=config, llm_provider=FakeLlmProvider()))


def create_project(client: TestClient, repository: Path) -> str:
    response = client.post(
        "/api/v1/projects",
        json={"name": "Payments", "repository_path": str(repository)},
    )
    assert response.status_code == 201
    return str(response.json()["project_id"])


def create_committed_repository(repository: Path) -> Path:
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.invalid")
    git(repository, "config", "user.name", "Test User")
    (repository / "README.md").write_text("hello\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "initial")
    return repository


def run_migrations(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


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
