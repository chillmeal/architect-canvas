import hashlib
import subprocess
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import AppConfig
from app.infrastructure.llm import FakeLlmProvider, FakeStructuredResponse, LlmModelInfo
from app.main import create_app


def test_real_audit_pipeline_publishes_llm_discovered_graph(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo")
    package_text = '{"name":"payments-subsystem","version":"1.0.0"}\n'
    (repository / "package.json").write_text(package_text, encoding="utf-8")
    git(repository, "add", "package.json")
    git(repository, "commit", "-m", "add package manifest")

    file_hash = hashlib.sha256(package_text.encode("utf-8")).hexdigest()
    fragment = package_text.rstrip("\n")
    fragment_hash = f"sha256:{hashlib.sha256(fragment.encode('utf-8')).hexdigest()}"
    evidence = {
        "evidence_id": "ev-package",
        "relative_path": "package.json",
        "file_hash": file_hash,
        "line_start": 1,
        "line_end": 1,
        "fragment_hash": fragment_hash,
        "source_type": "MANIFEST",
        "strength": "STRONG",
        "analysis_unit_id": "unit-root",
    }
    provider = FakeLlmProvider(
        models=(LlmModelInfo(model_id="fake-chat", owned_by="test", capabilities=("chat",)),)
    )
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "candidates": [],
                "unresolved_questions": [
                    {
                        "question_id": "discovery-complete",
                        "message": "Detailed component extraction delegated to analysis stage",
                        "related_paths": ["package.json"],
                    }
                ],
            }
        )
    )
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "facts": [
                    {
                        "fact_id": "fact-payments-subsystem",
                        "fact_kind": "NODE",
                        "candidate_schema_version": "0.1.0",
                        "node_type": "FUNCTIONAL_SUBSYSTEM",
                        "name": "payments-subsystem",
                        "evidence": [evidence],
                        "metadata": {"repository_path": ".", "package_name": "payments-subsystem"},
                    }
                ],
                "unresolved_questions": [],
            }
        )
    )
    provider.enqueue_structured_response(
        FakeStructuredResponse(
            payload={
                "decision": "SUPPORTED",
                "reason_codes": [],
                "message": "The package manifest directly supports this architecture node",
            }
        )
    )

    database_url = f"sqlite:///{tmp_path / 'pipeline.db'}"
    run_migrations(database_url)
    config = AppConfig(
        app_env="test",
        database_url=database_url,
        repository_allowed_roots=(tmp_path,),
    )

    with TestClient(create_app(config=config, llm_provider=provider)) as client:
        project_response = client.post(
            "/api/v1/projects",
            json={"name": "Payments", "repository_path": str(repository)},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["project_id"]

        audit_response = client.post(f"/api/v1/projects/{project_id}/audits")
        assert audit_response.status_code == 201
        audit_id = audit_response.json()["audit_id"]
        audit = wait_for_terminal_audit(client, audit_id)
        graph_response = client.get(f"/api/v1/audits/{audit_id}/graph")

    assert audit["status"] == "COMPLETED"
    assert audit["summary"]["pipeline"] == "real"
    assert audit["summary"]["published_node_count"] == 1
    assert graph_response.status_code == 200
    graph = graph_response.json()
    assert [(node["name"], node["node_type"]) for node in graph["nodes"]] == [
        ("payments-subsystem", "FUNCTIONAL_SUBSYSTEM")
    ]
    assert [request.model for request in provider.requests] == ["fake-chat", "fake-chat", "fake-chat"]


def wait_for_terminal_audit(client: TestClient, audit_id: str) -> dict[str, object]:
    terminal = {"COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED"}
    for _ in range(200):
        response = client.get(f"/api/v1/audits/{audit_id}")
        assert response.status_code == 200
        audit = response.json()
        if audit["status"] in terminal:
            return audit
        time.sleep(0.01)
    events = client.get(f"/api/v1/audits/{audit_id}/events/page").json()
    raise AssertionError(f"audit did not reach terminal state: {audit}; events={events}")


def create_repository(repository: Path) -> Path:
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.invalid")
    git(repository, "config", "user.name", "Test User")
    (repository / "README.md").write_text("architecture fixture\n", encoding="utf-8")
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
