"""Networking agent fields on network_contacts.

Revision ID: 20260724_0012
Revises: 20260724_0011
Create Date: 2026-07-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260724_0012"
down_revision: Union[str, None] = "20260724_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "network_contacts",
        sa.Column("agent_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("network_contacts", sa.Column("agent_step", sa.String(), nullable=True))
    op.add_column(
        "network_contacts",
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "network_contacts",
        sa.Column("nudge_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("network_contacts", sa.Column("agent_meta", JSONB(), nullable=True))
    op.create_index(
        "ix_network_contacts_agent_due",
        "network_contacts",
        ["user_id", "agent_enabled", "next_action_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_network_contacts_agent_due", table_name="network_contacts")
    op.drop_column("network_contacts", "agent_meta")
    op.drop_column("network_contacts", "nudge_count")
    op.drop_column("network_contacts", "next_action_at")
    op.drop_column("network_contacts", "agent_step")
    op.drop_column("network_contacts", "agent_enabled")
