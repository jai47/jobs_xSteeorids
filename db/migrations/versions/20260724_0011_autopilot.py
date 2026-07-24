"""Autopilot JSONB fields + master resume persona label.

Revision ID: 20260724_0011
Revises: 20260723_0010
Create Date: 2026-07-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260724_0011"
down_revision: Union[str, None] = "20260723_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("autopilot", JSONB(), nullable=True))
    op.add_column("applications", sa.Column("autopilot", JSONB(), nullable=True))
    op.add_column("master_resumes", sa.Column("label", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("master_resumes", "label")
    op.drop_column("applications", "autopilot")
    op.drop_column("users", "autopilot")
