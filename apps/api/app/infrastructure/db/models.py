from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectRecord(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repository_root: Mapped[str] = mapped_column(Text, nullable=False)
    is_archived: Mapped[bool] = mapped_column(default=False, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    repository_states: Mapped[list[RepositoryStateRecord]] = relationship(back_populates="project")
    audits: Mapped[list[AuditRecord]] = relationship(back_populates="project")


class RepositoryStateRecord(Base):
    __tablename__ = "repository_states"

    repository_state_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(128))
    branch: Mapped[str | None] = mapped_column(String(255))
    dirty: Mapped[bool] = mapped_column(default=False, nullable=False)
    tree_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped[ProjectRecord] = relationship(back_populates="repository_states")
    audits: Mapped[list[AuditRecord]] = relationship(back_populates="repository_state")


class AuditRecord(Base):
    __tablename__ = "audits"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), nullable=False)
    repository_state_id: Mapped[str] = mapped_column(
        ForeignKey("repository_states.repository_state_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[ProjectRecord] = relationship(back_populates="audits")
    repository_state: Mapped[RepositoryStateRecord] = relationship(back_populates="audits")
    stages: Mapped[list[AuditStageRecord]] = relationship(back_populates="audit")
    events: Mapped[list[AuditEventRecord]] = relationship(back_populates="audit")
    graph_snapshots: Mapped[list[GraphSnapshotRecord]] = relationship(back_populates="audit")


class AuditStageRecord(Base):
    __tablename__ = "audit_stages"

    audit_stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.audit_id"), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    audit: Mapped[AuditRecord] = relationship(back_populates="stages")


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    audit_event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.audit_id"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stage_name: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    audit: Mapped[AuditRecord] = relationship(back_populates="events")


class GraphSnapshotRecord(Base):
    __tablename__ = "graph_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), nullable=False)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.audit_id"), nullable=False)
    repository_state_id: Mapped[str] = mapped_column(
        ForeignKey("repository_states.repository_state_id"),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    audit: Mapped[AuditRecord] = relationship(back_populates="graph_snapshots")
    nodes: Mapped[list[GraphNodeRecord]] = relationship(back_populates="snapshot")
    edges: Mapped[list[GraphEdgeRecord]] = relationship(back_populates="snapshot")
    revisions: Mapped[list[GraphRevisionRecord]] = relationship(back_populates="snapshot")


class GraphNodeRecord(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "stable_key",
            name="uq_graph_nodes_snapshot_id_stable_key",
        ),
    )

    node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("graph_snapshots.snapshot_id"),
        nullable=False,
    )
    stable_key: Mapped[str] = mapped_column(String(512), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_state: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    validation_record: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    snapshot: Mapped[GraphSnapshotRecord] = relationship(back_populates="nodes")


class GraphEdgeRecord(Base):
    __tablename__ = "graph_edges"

    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("graph_snapshots.snapshot_id"),
        nullable=False,
    )
    source_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.node_id"), nullable=False)
    target_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.node_id"), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_state: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    contract: Mapped[str | None] = mapped_column(Text)
    protocol: Mapped[str | None] = mapped_column(String(64))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    validation_record: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    snapshot: Mapped[GraphSnapshotRecord] = relationship(back_populates="edges")


class GraphRevisionRecord(Base):
    __tablename__ = "graph_revisions"

    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("graph_snapshots.snapshot_id"),
        nullable=False,
    )
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("graph_revisions.revision_id"),
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    snapshot: Mapped[GraphSnapshotRecord] = relationship(back_populates="revisions")
    overrides: Mapped[list[GraphOverrideRecord]] = relationship(back_populates="revision")


class GraphOverrideRecord(Base):
    __tablename__ = "graph_overrides"

    override_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("graph_revisions.revision_id"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_node_id: Mapped[str | None] = mapped_column(String(36))
    target_edge_id: Mapped[str | None] = mapped_column(String(36))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    revision: Mapped[GraphRevisionRecord] = relationship(back_populates="overrides")
