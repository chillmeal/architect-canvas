import pytest

from app.domain.enums import (
    TERMINAL_AUDIT_STATUSES,
    AuditStatus,
    EdgeType,
    EntityOrigin,
    EvidenceSourceType,
    EvidenceStrength,
    LlmValidatorDecision,
    NodeType,
    OverrideOperation,
    ReasonCode,
    UnknownEnumValueError,
    ValidationState,
    parse_enum_value,
)


def test_node_types_match_architecture_contract() -> None:
    assert {item.value for item in NodeType} == {
        "AUTOMATED_SYSTEM",
        "FUNCTIONAL_SUBSYSTEM",
        "MODULE",
        "SUBMODULE",
        "MICROSERVICE",
        "APPLICATION_COMPONENT",
        "INFRA_COMPONENT",
        "MESSAGE_BROKER",
        "TOPIC",
        "DATABASE",
        "EXTERNAL_SYSTEM",
        "API_ENDPOINT",
        "UNKNOWN",
    }


def test_edge_types_match_architecture_contract() -> None:
    assert {item.value for item in EdgeType} == {
        "CONTAINS",
        "SYNC_CALL",
        "ASYNC_PUBLISH",
        "ASYNC_SUBSCRIBE",
        "DATA_READ",
        "DATA_WRITE",
        "ROUTES_TO",
        "DEPENDS_ON",
        "IMPLEMENTS",
        "UNKNOWN",
    }


def test_status_and_operation_enums_cover_architecture_contracts() -> None:
    assert {item.value for item in ValidationState} == {
        "CONFIRMED",
        "CONFIRMED_WITH_WARNINGS",
        "UNCONFIRMED",
        "REVIEW_REQUIRED",
        "REJECTED",
        "STALE",
    }
    assert {item.value for item in AuditStatus} >= {
        "QUEUED",
        "SCANNING",
        "DISCOVERING",
        "ANALYZING",
        "VALIDATING",
        "ASSEMBLING",
        "COMPLETED",
        "COMPLETED_WITH_WARNINGS",
        "FAILED",
        "CANCELLED",
        "PARTIAL",
        "INTERRUPTED",
    }
    assert TERMINAL_AUDIT_STATUSES == {
        AuditStatus.COMPLETED,
        AuditStatus.COMPLETED_WITH_WARNINGS,
        AuditStatus.FAILED,
        AuditStatus.CANCELLED,
    }
    assert {item.value for item in OverrideOperation} == {
        "ADD_NODE",
        "UPDATE_NODE",
        "MOVE_NODE",
        "SUPPRESS_NODE",
        "RESTORE_NODE",
        "ADD_EDGE",
        "UPDATE_EDGE",
        "SUPPRESS_EDGE",
        "RESTORE_EDGE",
    }
    assert {item.value for item in EntityOrigin} == {"INFERRED", "MANUAL"}


def test_validation_supporting_enums_are_explicit() -> None:
    assert {item.value for item in LlmValidatorDecision} == {
        "SUPPORTED",
        "CONTRADICTED",
        "INSUFFICIENT_EVIDENCE",
        "AMBIGUOUS",
        "INVALID_SEMANTICS",
    }
    assert {item.value for item in EvidenceStrength} == {"STRONG", "MEDIUM", "WEAK"}
    assert {item.value for item in EvidenceSourceType} == {
        "SOURCE_CODE",
        "MANIFEST",
        "CONFIGURATION",
        "DEPLOYMENT",
        "API_CONTRACT",
        "DOCUMENTATION",
    }
    assert ReasonCode.EVIDENCE_MISSING.value == "EVIDENCE_MISSING"
    assert ReasonCode.REVIEW_REQUIRED.value == "REVIEW_REQUIRED"


def test_parse_enum_value_rejects_unknown_values_explicitly() -> None:
    assert parse_enum_value(NodeType, "MICROSERVICE") is NodeType.MICROSERVICE

    with pytest.raises(UnknownEnumValueError) as exc_info:
        parse_enum_value(NodeType, "SERVICE")

    assert exc_info.value.enum_name == "NodeType"
    assert exc_info.value.raw_value == "SERVICE"
