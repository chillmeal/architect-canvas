import pytest

from app.domain.enums import NodeType
from app.domain.value_objects import (
    StableLogicalKey,
    StableLogicalKeyError,
    StableLogicalKeySource,
    normalize_key_part,
)


def test_normalize_key_part_is_deterministic() -> None:
    assert normalize_key_part("  Billing Service/API  ") == "billing-service-api"
    assert normalize_key_part("Cafe\u0301 Service") == "café-service"


def test_stable_logical_key_uses_owner_type_name_and_identity_signal() -> None:
    key = StableLogicalKey.from_source(
        StableLogicalKeySource(
            project_id="Project A",
            node_type=NodeType.MICROSERVICE,
            owner_path=("Subsystem", "Payments"),
            name="Billing Service",
            artifact_id="billing-service",
            package_name="com.company.billing",
            deployment_name="billing-prod",
            repository_path="services/billing",
        )
    )

    assert key.value == (
        "project-a/MICROSERVICE/subsystem/payments/"
        "billing-service__artifact-billing-service__deployment-billing-prod__"
        "package-com.company.billing__path-services-billing"
    )


def test_stable_logical_key_supports_root_owner_path() -> None:
    key = StableLogicalKey.from_source(
        StableLogicalKeySource(
            project_id="Project A",
            node_type=NodeType.AUTOMATED_SYSTEM,
            owner_path=(),
            name="Target System",
            repository_path=".",
        )
    )

    assert key.value == "project-a/AUTOMATED_SYSTEM/_root/target-system__path-root"


def test_stable_logical_key_cannot_be_built_only_from_display_name() -> None:
    with pytest.raises(StableLogicalKeyError) as exc_info:
        StableLogicalKey.from_source(
            StableLogicalKeySource(
                project_id="Project A",
                node_type=NodeType.MICROSERVICE,
                owner_path=("Subsystem",),
                name="Billing Service",
            )
        )

    assert "requires at least one identity signal" in str(exc_info.value)


def test_stable_logical_key_rejects_empty_project_or_name() -> None:
    with pytest.raises(StableLogicalKeyError, match="project_id is required"):
        StableLogicalKey.from_source(
            StableLogicalKeySource(
                project_id=" ",
                node_type=NodeType.MICROSERVICE,
                owner_path=("Subsystem",),
                name="Billing Service",
                artifact_id="billing",
            )
        )

    with pytest.raises(StableLogicalKeyError, match="name is required"):
        StableLogicalKey.from_source(
            StableLogicalKeySource(
                project_id="Project A",
                node_type=NodeType.MICROSERVICE,
                owner_path=("Subsystem",),
                name=" ",
                artifact_id="billing",
            )
        )
