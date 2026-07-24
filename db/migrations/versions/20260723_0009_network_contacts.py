"""Network contacts for LinkedIn outreach drafts (SaaS-safe copy-paste flow).

Revision ID: 20260723_0009
Revises: 20260705_0008
Create Date: 2026-07-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260723_0009"
down_revision: Union[str, None] = "20260705_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "network_contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("company", sa.String(), nullable=False, server_default=""),
        sa.Column("person_name", sa.String(), nullable=False),
        sa.Column("linkedin_url", sa.String(), nullable=False),
        sa.Column("role_tag", sa.String(), nullable=False, server_default="recruiter"),
        sa.Column("status", sa.String(), nullable=False, server_default="drafted"),
        sa.Column("message_draft", sa.Text(), nullable=True),
        sa.Column("message_template", sa.String(), nullable=False, server_default="referral"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("follow_up_due", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_network_contacts_user_id", "network_contacts", ["user_id"])
    op.create_index("ix_network_contacts_application_id", "network_contacts", ["application_id"])
    op.create_index("ix_network_contacts_status", "network_contacts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_network_contacts_status", table_name="network_contacts")
    op.drop_index("ix_network_contacts_application_id", table_name="network_contacts")
    op.drop_index("ix_network_contacts_user_id", table_name="network_contacts")
    op.drop_table("network_contacts")
