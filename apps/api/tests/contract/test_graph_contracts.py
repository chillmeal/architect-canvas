import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.graph import Evidence, GraphEdge, GraphNode, GraphSnapshot
from app.domain.enums import (
    EdgeType,
    EntityOrigin,
    EvidenceSourceType,
    EvidenceStrength,
    NodeType,
    ValidationState,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def test_json_schema_files_match_pydantic_models() -> None:
    expected_graph_schema = GraphSnapshot.model_json_schema(by_alias=True)
    expected_graph_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    expected_graph_schema["$id"] = (
        "https://architecture-visualizer.local/contracts/graph.schema.json"
    )
    expected_evidence_schema = Evidence.model_json_schema(by_alias=True)
    expected_evidence_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    expected_evidence_schema["$id"] = (
        "https://architecture-visualizer.local/contracts/evidence.schema.json"
    )

    actual_graph_schema = json.loads(
        (REPOSITORY_ROOT / "contracts" / "graph.schema.json").read_text(encoding="utf-8")
    )
    actual_evidence_schema = json.loads(
        (REPOSITORY_ROOT / "contracts" / "evidence.schema.json").read_text(encoding="utf-8")
    )

    assert actual_graph_schema == expected_graph_schema
    assert actual_evidence_schema == expected_evidence_schema


def test_evidence_contract_requires_identity_location_and_fragment_marker() -> None:
    evidence = make_evidence()

    assert evidence.relative_path == "src/main.py"
    assert evidence.line_start == 1
    assert evidence.line_end == 3
    assert evidence.analysis_unit_id == "unit-1"

    with pytest.raises(ValidationError, match="fragment_hash or source_fragment_marker"):
        make_evidence(fragment_hash=None, source_fragment_marker=None)

    with pytest.raises(ValidationError, match="line_end"):
        make_evidence(line_start=4, line_end=3)


def test_contracts_forbid_unknown_extra_properties() -> None:
    payload = make_evidence().model_dump(by_alias=True)
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_inferred_node_and_edge_require_evidence() -> None:
    with pytest.raises(ValidationError, match="inferred node evidence is required"):
        GraphNode(
            node_id="node-1",
            stable_key="project/MICROSERVICE/owner/name",
            node_type=NodeType.MICROSERVICE,
            name="service",
            origin=EntityOrigin.INFERRED,
            validation_state=ValidationState.CONFIRMED,
            confidence=0.9,
        )

    with pytest.raises(ValidationError, match="inferred edge evidence is required"):
        GraphEdge(
            edge_id="edge-1",
            source_node_id="node-1",
            target_node_id="node-2",
            edge_type=EdgeType.SYNC_CALL,
            origin=EntityOrigin.INFERRED,
            validation_state=ValidationState.CONFIRMED,
            confidence=0.9,
        )


def test_manual_node_can_exist_without_evidence() -> None:
    node = GraphNode(
        node_id="node-1",
        stable_key="project/MODULE/_root/module",
        node_type=NodeType.MODULE,
        name="module",
        origin=EntityOrigin.MANUAL,
        validation_state=ValidationState.CONFIRMED,
        confidence=1.0,
    )

    assert node.evidence == ()


def test_unknown_enum_values_are_rejected_by_contracts() -> None:
    payload = make_evidence().model_dump(by_alias=True)
    payload["sourceType"] = "README_GUESS"

    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def make_evidence(**overrides: object) -> Evidence:
    payload = {
        "evidence_id": "evidence-1",
        "relative_path": "src/main.py",
        "file_hash": "sha256:abc",
        "line_start": 1,
        "line_end": 3,
        "fragment_hash": "sha256:def",
        "source_fragment_marker": None,
        "source_type": EvidenceSourceType.SOURCE_CODE,
        "strength": EvidenceStrength.STRONG,
        "analysis_unit_id": "unit-1",
        "llm_invocation_id": "llm-1",
    }
    payload.update(overrides)
    return Evidence.model_validate(payload)
