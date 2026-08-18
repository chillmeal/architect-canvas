"""graph snapshots and revisions storage

Revision ID: 0003_graph_snapshots_revisions
Revises: 0002_audits_events_storage
Create Date: 2026-08-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_graph_snapshots_revisions"
down_revision: str | None = "0002_audits_events_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_snapshots",
        sa.Column("snapshot_id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("audit_id", sa.String(length=36), nullable=False),
        sa.Column("repository_state_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.audit_id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.ForeignKeyConstraint(["repository_state_id"], ["repository_states.repository_state_id"]),
    )
    op.create_index("ix_graph_snapshots_audit_id", "graph_snapshots", ["audit_id"])
    op.create_index("ix_graph_snapshots_project_id", "graph_snapshots", ["project_id"])
    op.create_table(
        "graph_nodes",
        sa.Column("node_id", sa.String(length=36), primary_key=True),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("stable_key", sa.String(length=512), nullable=False),
        sa.Column("node_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("validation_state", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("validation_record", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["graph_snapshots.snapshot_id"]),
        sa.UniqueConstraint("snapshot_id", "stable_key", name="uq_graph_nodes_snapshot_id_stable_key"),
    )
    op.create_index("ix_graph_nodes_snapshot_id", "graph_nodes", ["snapshot_id"])
    op.create_table(
        "graph_edges",
        sa.Column("edge_id", sa.String(length=36), primary_key=True),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=False),
        sa.Column("target_node_id", sa.String(length=36), nullable=False),
        sa.Column("edge_type", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("validation_state", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("contract", sa.Text(), nullable=True),
        sa.Column("protocol", sa.String(length=64), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("validation_record", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["graph_snapshots.snapshot_id"]),
        sa.ForeignKeyConstraint(["source_node_id"], ["graph_nodes.node_id"]),
        sa.ForeignKeyConstraint(["target_node_id"], ["graph_nodes.node_id"]),
    )
    op.create_index("ix_graph_edges_snapshot_id", "graph_edges", ["snapshot_id"])
    op.create_table(
        "graph_revisions",
        sa.Column("revision_id", sa.String(length=36), primary_key=True),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_revision_id"], ["graph_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["graph_snapshots.snapshot_id"]),
    )
    op.create_index("ix_graph_revisions_snapshot_id", "graph_revisions", ["snapshot_id"])
    op.create_table(
        "graph_overrides",
        sa.Column("override_id", sa.String(length=36), primary_key=True),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("entity_kind", sa.String(length=16), nullable=False),
        sa.Column("target_node_id", sa.String(length=36), nullable=True),
        sa.Column("target_edge_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["graph_revisions.revision_id"]),
    )
    op.create_index("ix_graph_overrides_revision_id", "graph_overrides", ["revision_id"])


def downgrade() -> None:
    op.drop_index("ix_graph_overrides_revision_id", table_name="graph_overrides")
    op.drop_table("graph_overrides")
    op.drop_index("ix_graph_revisions_snapshot_id", table_name="graph_revisions")
    op.drop_table("graph_revisions")
    op.drop_index("ix_graph_edges_snapshot_id", table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index("ix_graph_nodes_snapshot_id", table_name="graph_nodes")
    op.drop_table("graph_nodes")
    op.drop_index("ix_graph_snapshots_project_id", table_name="graph_snapshots")
    op.drop_index("ix_graph_snapshots_audit_id", table_name="graph_snapshots")
    op.drop_table("graph_snapshots")
