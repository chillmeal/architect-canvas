import json
from pathlib import Path
from typing import Any

import pytest

from app.infrastructure.repository.scanner import FileIndexStatus, RepositoryFileIndexer

FIXTURE_ROOT = Path(__file__).resolve().parents[4] / "tests" / "fixture-repositories"
FIXTURE_NAMES = ("simple-rest", "kafka-services", "ambiguous-architecture")
SECRET_MARKERS = (
    "BEGIN PRIVATE KEY",
    "Authorization: Bearer",
    "password=",
    "client_secret",
    "GIGACHAT_CREDENTIALS",
)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_fixture_repository_has_expected_golden_graph_and_safe_content(fixture_name: str) -> None:
    repository = FIXTURE_ROOT / fixture_name
    expected_graph = read_expected_graph(repository)
    file_index = RepositoryFileIndexer(
        allowed_roots=(FIXTURE_ROOT,),
        max_file_bytes=100_000,
    ).index_files(repository)

    assert expected_graph["fixture"] == fixture_name
    assert file_index.warnings == ()
    assert all(record.status == FileIndexStatus.INDEXED for record in file_index.files)
    assert all(record.sha256 for record in file_index.files)
    assert_fixture_has_no_secret_markers(repository)


def test_simple_rest_fixture_contains_two_services_and_confirmed_http_call() -> None:
    graph = read_expected_graph(FIXTURE_ROOT / "simple-rest")

    assert {node["name"] for node in graph["expectedNodes"]} == {"orders-api", "billing-api"}
    assert graph["expectedEdges"] == [
        {
            "sourceStableKey": "fixture/simple-rest/MICROSERVICE/orders-api",
            "targetStableKey": "fixture/simple-rest/MICROSERVICE/billing-api",
            "type": "SYNC_CALL",
            "evidencePaths": [
                "orders-api/src/index.ts",
                "billing-api/openapi.yaml",
            ],
        }
    ]
    orders_source = (FIXTURE_ROOT / "simple-rest" / "orders-api" / "src" / "index.ts").read_text(
        encoding="utf-8"
    )
    assert "fetch(`${billingBaseUrl}/invoices/" in orders_source


def test_kafka_fixture_contains_producer_consumer_and_topic() -> None:
    graph = read_expected_graph(FIXTURE_ROOT / "kafka-services")

    assert any(node["type"] == "TOPIC" and node["name"] == "orders.created" for node in graph["expectedNodes"])
    edge_types = {edge["type"] for edge in graph["expectedEdges"]}
    assert edge_types == {"ASYNC_PUBLISH", "ASYNC_SUBSCRIBE"}
    order_source = (
        FIXTURE_ROOT
        / "kafka-services"
        / "order-service"
        / "src"
        / "main"
        / "java"
        / "example"
        / "Application.java"
    ).read_text(encoding="utf-8")
    inventory_source = (
        FIXTURE_ROOT
        / "kafka-services"
        / "inventory-service"
        / "src"
        / "main"
        / "java"
        / "example"
        / "Application.java"
    ).read_text(encoding="utf-8")
    assert 'kafkaTemplate.send("orders.created", orderId)' in order_source
    assert '@KafkaListener(topics = "orders.created", groupId = "inventory-service")' in inventory_source


def test_ambiguous_fixture_documents_false_import_and_insufficient_evidence() -> None:
    graph = read_expected_graph(FIXTURE_ROOT / "ambiguous-architecture")

    assert {node["name"] for node in graph["expectedNodes"]} == {"payment-api", "payments-api"}
    assert graph["expectedEdges"] == []
    assert {issue["reasonCode"] for issue in graph["expectedIssues"]} == {
        "INSUFFICIENT_SOURCE_SIGNALS",
        "NAMING_SIMILARITY_ONLY",
    }
    source = (
        FIXTURE_ROOT / "ambiguous-architecture" / "payment-api" / "src" / "index.ts"
    ).read_text(encoding="utf-8")
    assert "import type { PaymentsApiClient }" in source
    assert "fetch(" not in source


def read_expected_graph(repository: Path) -> dict[str, Any]:
    graph_path = repository / "expected-graph.json"
    assert graph_path.is_file()
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert set(graph) == {"fixture", "expectedNodes", "expectedEdges", "expectedIssues"}
    assert graph["expectedNodes"]
    return graph


def assert_fixture_has_no_secret_markers(repository: Path) -> None:
    for path in repository.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        assert not any(marker in content for marker in SECRET_MARKERS), path
