"""audits and events storage

Revision ID: 0002_audits_events_storage
Revises: 0001_baseline
Create Date: 2026-08-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_audits_events_storage"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("repository_root", sa.Text(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "repository_states",
        sa.Column("repository_state_id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("commit_sha", sa.String(length=128), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("dirty", sa.Boolean(), nullable=False),
        sa.Column("tree_hash", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
    )
    op.create_index(
        "ix_repository_states_project_id",
        "repository_states",
        ["project_id"],
    )
    op.create_table(
        "audits",
        sa.Column("audit_id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("repository_state_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.ForeignKeyConstraint(["repository_state_id"], ["repository_states.repository_state_id"]),
    )
    op.create_index("ix_audits_project_id", "audits", ["project_id"])
    op.create_index("ix_audits_status", "audits", ["status"])
    op.create_table(
        "audit_stages",
        sa.Column("audit_stage_id", sa.String(length=36), primary_key=True),
        sa.Column("audit_id", sa.String(length=36), nullable=False),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.audit_id"]),
        sa.UniqueConstraint("audit_id", "stage_name", name="uq_audit_stages_audit_id_stage_name"),
    )
    op.create_index("ix_audit_stages_audit_id", "audit_stages", ["audit_id"])
    op.create_table(
        "audit_events",
        sa.Column("audit_event_id", sa.String(length=36), primary_key=True),
        sa.Column("audit_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stage_name", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.audit_id"]),
        sa.UniqueConstraint(
            "audit_id",
            "sequence_number",
            name="uq_audit_events_audit_id_sequence_number",
        ),
    )
    op.create_index("ix_audit_events_audit_id", "audit_events", ["audit_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_audit_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_audit_stages_audit_id", table_name="audit_stages")
    op.drop_table("audit_stages")
    op.drop_index("ix_audits_status", table_name="audits")
    op.drop_index("ix_audits_project_id", table_name="audits")
    op.drop_table("audits")
    op.drop_index("ix_repository_states_project_id", table_name="repository_states")
    op.drop_table("repository_states")
    op.drop_table("projects")
