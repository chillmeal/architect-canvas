from pathlib import Path

from app.infrastructure.repository.scanner import RepositoryFileIndexer
from app.infrastructure.repository.unit_detector import AnalysisUnitDetector

FIXTURE_ROOT = Path(__file__).resolve().parents[4] / "tests" / "fixture-repositories"


def test_analysis_unit_detector_reads_simple_rest_service_units() -> None:
    repository = FIXTURE_ROOT / "simple-rest"
    file_index = RepositoryFileIndexer(
        allowed_roots=(FIXTURE_ROOT,),
        max_file_bytes=100_000,
    ).index_files(repository)

    units = AnalysisUnitDetector(repository).detect(file_index)
    units_by_root = {unit.root_paths[0]: unit for unit in units}

    assert sorted(units_by_root) == ["billing-api", "orders-api"]
    orders_api = units_by_root["orders-api"]
    assert orders_api.candidate_name == "orders-api"
    assert orders_api.manifest_files == (
        "orders-api/Dockerfile",
        "orders-api/openapi.yaml",
        "orders-api/package.json",
    )
    assert orders_api.entry_points == ("orders-api/src/index.ts",)
    assert "node-fetch" in orders_api.dependency_hints
    assert orders_api.signals == ("DOCKERFILE", "OPENAPI", "PACKAGE_JSON")

    billing_api = units_by_root["billing-api"]
    assert billing_api.candidate_name == "billing-api"
    assert billing_api.manifest_files == (
        "billing-api/Dockerfile",
        "billing-api/openapi.yaml",
        "billing-api/package.json",
    )
    assert billing_api.entry_points == ("billing-api/src/index.ts",)
    assert "express" in billing_api.dependency_hints


def test_analysis_unit_detector_detects_multiple_fixture_units() -> None:
    repository = FIXTURE_ROOT / "kafka-services"
    file_index = RepositoryFileIndexer(
        allowed_roots=(FIXTURE_ROOT,),
        max_file_bytes=100_000,
    ).index_files(repository)

    units = AnalysisUnitDetector(repository).detect(file_index)
    units_by_root = {unit.root_paths[0]: unit for unit in units}

    order_service = units_by_root["order-service"]
    assert order_service.candidate_name == "order-service"
    assert order_service.manifest_files == (
        "order-service/deployment.yaml",
        "order-service/pom.xml",
    )
    assert order_service.config_files == (
        "order-service/src/main/resources/application.yml",
    )
    assert order_service.entry_points == (
        "order-service/src/main/java/example/Application.java",
    )
    assert "spring-kafka" in order_service.dependency_hints
    assert order_service.signals == ("APPLICATION_CONFIG", "DEPLOYMENT_MANIFEST", "POM")

    inventory_service = units_by_root["inventory-service"]
    assert inventory_service.candidate_name == "inventory-service"
    assert inventory_service.manifest_files == ("inventory-service/build.gradle",)
    assert inventory_service.entry_points == (
        "inventory-service/src/main/java/example/Application.java",
    )
    assert "org.springframework.boot:spring-boot-starter-web:3.2.0" in (
        inventory_service.dependency_hints
    )
    assert inventory_service.signals == ("GRADLE",)


def test_analysis_unit_detector_falls_back_to_directories(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    (repository / "services" / "billing").mkdir(parents=True)
    (repository / "libs" / "common").mkdir(parents=True)
    (repository / "services" / "billing" / "billing.py").write_text(
        "print('billing')",
        encoding="utf-8",
    )
    (repository / "libs" / "common" / "common.py").write_text(
        "print('common')",
        encoding="utf-8",
    )
    file_index = RepositoryFileIndexer(
        allowed_roots=(tmp_path,),
        max_file_bytes=100_000,
    ).index_files(repository)

    units = AnalysisUnitDetector(repository).detect(file_index)

    assert [unit.root_paths[0] for unit in units] == ["libs/common", "services/billing"]
    assert [unit.candidate_name for unit in units] == ["common", "billing"]
