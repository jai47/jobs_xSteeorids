"""Notifications outbox + user email preferences (NTF).

Revision ID: 20260705_0007
Revises: 20260705_0006
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "20260705_0007"
down_revision: Union[str, None] = "20260705_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_digest_email", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "users",
        sa.Column("notify_followup_email", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("dedupe_key", name="uq_notifications_dedupe"),
    )
    op.create_index(
        "ix_notifications_drain",
        "notifications",
        ["status", "channel", "scheduled_for"],
    )
    op.create_index(
        "ix_notifications_feed",
        "notifications",
        ["user_id", "channel", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_feed", table_name="notifications")
    op.drop_index("ix_notifications_drain", table_name="notifications")
    op.drop_table("notifications")
    op.drop_column("users", "notify_followup_email")
    op.drop_column("users", "notify_digest_email")
