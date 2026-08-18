from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.domain.enums import OverrideOperation
from app.infrastructure.db.models import GraphEdgeRecord, GraphNodeRecord, GraphOverrideRecord
from app.services.graph_service import GraphProjection, GraphService

router = APIRouter(tags=["graphs"])


class GraphNodeProjectionResponse(BaseModel):
    node_id: str
    stable_key: str
    node_type: str
    name: str
    origin: str
    validation_state: str
    confidence: float


class GraphEdgeProjectionResponse(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    origin: str
    validation_state: str
    confidence: float
    protocol: str | None


class GraphHierarchyEdgeResponse(BaseModel):
    edge_id: str
    parent_node_id: str
    child_node_id: str


class GraphProjectionResponse(BaseModel):
    graph_id: str
    audit_id: str
    project_id: str
    repository_state_id: str
    schema_version: str
    status: str
    summary: dict[str, Any]
    nodes: list[GraphNodeProjectionResponse]
    edges: list[GraphEdgeProjectionResponse]
    hierarchy: list[GraphHierarchyEdgeResponse]
    revision: dict[str, Any] | None = None
    layout_hints: dict[str, Any] = Field(default_factory=dict)
    issue_counters: dict[str, int] = Field(default_factory=dict)


class GraphNodeDetailResponse(GraphNodeProjectionResponse):
    evidence: list[dict[str, Any]]
    validation_record: dict[str, Any] | None
    metadata: dict[str, Any]


class GraphEdgeDetailResponse(GraphEdgeProjectionResponse):
    contract: str | None
    evidence: list[dict[str, Any]]
    validation_record: dict[str, Any] | None
    metadata: dict[str, Any]


class GraphRevisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_revision_id: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    created_by: str | None = Field(default=None, min_length=1, max_length=255)


class GraphRevisionResponse(BaseModel):
    revision_id: str
    graph_id: str
    parent_revision_id: str | None
    status: str
    title: str | None
    created_by: str | None
    created_at: datetime
    committed_at: datetime | None


class GraphOverrideCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: OverrideOperation
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = Field(default=None, min_length=1)
    created_by: str | None = Field(default=None, min_length=1, max_length=255)


class GraphOverrideResponse(BaseModel):
    override_id: str
    revision_id: str
    operation: str
    entity_kind: str
    target_node_id: str | None
    target_edge_id: str | None
    payload: dict[str, Any]
    reason: str | None
    created_by: str | None
    created_at: datetime


def get_graph_service(session: Annotated[Session, Depends(get_session)]) -> GraphService:
    return GraphService(session=session)


@router.get("/audits/{audit_id}/graph", response_model=GraphProjectionResponse)
def get_audit_graph(
    audit_id: str,
    service: Annotated[GraphService, Depends(get_graph_service)],
    revision_id: str | None = Query(default=None),
) -> GraphProjectionResponse:
    return _projection_response(service.get_graph_for_audit(audit_id, revision_id=revision_id))


@router.get("/graphs/{graph_id}/nodes/{node_id}", response_model=GraphNodeDetailResponse)
def get_graph_node(
    graph_id: str,
    node_id: str,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> GraphNodeDetailResponse:
    return _node_detail_response(service.get_node(graph_id=graph_id, node_id=node_id))


@router.get("/graphs/{graph_id}/edges/{edge_id}", response_model=GraphEdgeDetailResponse)
def get_graph_edge(
    graph_id: str,
    edge_id: str,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> GraphEdgeDetailResponse:
    return _edge_detail_response(service.get_edge(graph_id=graph_id, edge_id=edge_id))


@router.post(
    "/graphs/{graph_id}/revisions",
    response_model=GraphRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_graph_revision(
    graph_id: str,
    request: GraphRevisionCreateRequest,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> GraphRevisionResponse:
    return _revision_response(
        service.create_revision(
            graph_id=graph_id,
            parent_revision_id=request.parent_revision_id,
            title=request.title,
            created_by=request.created_by,
        )
    )


@router.get("/graphs/{graph_id}/revisions", response_model=list[GraphRevisionResponse])
def list_graph_revisions(
    graph_id: str,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> list[GraphRevisionResponse]:
    return [_revision_response(revision) for revision in service.list_revisions(graph_id)]


@router.post(
    "/revisions/{revision_id}/overrides",
    response_model=GraphOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_graph_override(
    revision_id: str,
    request: GraphOverrideCreateRequest,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> GraphOverrideResponse:
    return _override_response(
        service.add_override(
            revision_id=revision_id,
            operation=request.operation,
            payload=request.payload,
            reason=request.reason,
            created_by=request.created_by,
        )
    )


@router.post("/revisions/{revision_id}/commit", response_model=GraphRevisionResponse)
def commit_graph_revision(
    revision_id: str,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> GraphRevisionResponse:
    return _revision_response(service.commit_revision(revision_id))


@router.delete(
    "/revisions/{revision_id}/manual-nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_unsaved_manual_node(
    revision_id: str,
    node_id: str,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> Response:
    service.delete_unsaved_manual_node(revision_id=revision_id, node_id=node_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _projection_response(projection: GraphProjection) -> GraphProjectionResponse:
    contains_edges = [edge for edge in projection.edges if edge.edge_type == "CONTAINS"]
    return GraphProjectionResponse(
        graph_id=projection.snapshot.snapshot_id,
        audit_id=projection.snapshot.audit_id,
        project_id=projection.snapshot.project_id,
        repository_state_id=projection.snapshot.repository_state_id,
        schema_version=projection.snapshot.schema_version,
        status=projection.snapshot.status,
        summary=projection.snapshot.summary,
        nodes=[_node_projection_response(node) for node in projection.nodes],
        edges=[_edge_projection_response(edge) for edge in projection.edges],
        hierarchy=[
            GraphHierarchyEdgeResponse(
                edge_id=edge.edge_id,
                parent_node_id=edge.source_node_id,
                child_node_id=edge.target_node_id,
            )
            for edge in contains_edges
        ],
        revision=(
            _revision_response(projection.revision).model_dump(mode="json")
            if projection.revision is not None
            else None
        ),
        issue_counters={"total": int(projection.snapshot.summary.get("issue_count", 0))},
    )


def _node_projection_response(node: GraphNodeRecord) -> GraphNodeProjectionResponse:
    return GraphNodeProjectionResponse(
        node_id=node.node_id,
        stable_key=node.stable_key,
        node_type=node.node_type,
        name=node.name,
        origin=node.origin,
        validation_state=node.validation_state,
        confidence=node.confidence,
    )


def _edge_projection_response(edge: GraphEdgeRecord) -> GraphEdgeProjectionResponse:
    return GraphEdgeProjectionResponse(
        edge_id=edge.edge_id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        edge_type=edge.edge_type,
        origin=edge.origin,
        validation_state=edge.validation_state,
        confidence=edge.confidence,
        protocol=edge.protocol,
    )


def _node_detail_response(node: GraphNodeRecord) -> GraphNodeDetailResponse:
    return GraphNodeDetailResponse(
        **_node_projection_response(node).model_dump(),
        evidence=node.evidence,
        validation_record=node.validation_record,
        metadata=node.metadata_json,
    )


def _edge_detail_response(edge: GraphEdgeRecord) -> GraphEdgeDetailResponse:
    return GraphEdgeDetailResponse(
        **_edge_projection_response(edge).model_dump(),
        contract=edge.contract,
        evidence=edge.evidence,
        validation_record=edge.validation_record,
        metadata=edge.metadata_json,
    )


def _revision_response(revision) -> GraphRevisionResponse:
    return GraphRevisionResponse(
        revision_id=revision.revision_id,
        graph_id=revision.snapshot_id,
        parent_revision_id=revision.parent_revision_id,
        status=revision.status,
        title=revision.title,
        created_by=revision.created_by,
        created_at=revision.created_at,
        committed_at=revision.committed_at,
    )


def _override_response(override: GraphOverrideRecord) -> GraphOverrideResponse:
    return GraphOverrideResponse(
        override_id=override.override_id,
        revision_id=override.revision_id,
        operation=override.operation,
        entity_kind=override.entity_kind,
        target_node_id=override.target_node_id,
        target_edge_id=override.target_edge_id,
        payload=override.payload,
        reason=override.reason,
        created_by=override.created_by,
        created_at=override.created_at,
    )
