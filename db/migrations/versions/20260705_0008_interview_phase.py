"""STAR bank, application themes, substages, stage events (F03 + F11).

Revision ID: 20260705_0008
Revises: 20260705_0007
Create Date: 2026-07-05
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision: str = "20260705_0008"
down_revision: Union[str, None] = "20260705_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("sub_status", sa.String(), nullable=True))

    op.create_table(
        "star_stories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("tags", ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("situation", sa.Text(), nullable=True),
        sa.Column("task", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("reflection", sa.Text(), nullable=True),
        sa.Column("source_job_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ai_drafted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_star_stories_user_id", "star_stories", ["user_id"])

    op.create_table(
        "application_themes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", UUID(as_uuid=True), nullable=False),
        sa.Column("themes", ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.UniqueConstraint("application_id", name="uq_application_themes_application_id"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "application_stage_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=True),
        sa.Column("from_sub", sa.String(), nullable=True),
        sa.Column("to_sub", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_stage_events_app",
        "application_stage_events",
        ["application_id", "occurred_at"],
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, status, updated_at FROM applications")
    ).fetchall()
    for app_id, status, updated_at in rows:
        conn.execute(
            sa.text(
                "INSERT INTO application_stage_events "
                "(id, application_id, from_status, to_status, from_sub, to_sub, occurred_at) "
                "VALUES (:id, :app_id, NULL, :status, NULL, NULL, :occurred_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "app_id": str(app_id),
                "status": status or "approved",
                "occurred_at": updated_at,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_stage_events_app", table_name="application_stage_events")
    op.drop_table("application_stage_events")
    op.drop_table("application_themes")
    op.drop_index("ix_star_stories_user_id", table_name="star_stories")
    op.drop_table("star_stories")
    op.drop_column("applications", "sub_status")
