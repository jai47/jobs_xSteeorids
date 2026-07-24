"""Store LinkedIn profile coach analysis on users.

Revision ID: 20260723_0010
Revises: 20260723_0009
Create Date: 2026-07-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260723_0010"
down_revision: Union[str, None] = "20260723_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("linkedin_profile_analysis", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "linkedin_profile_analysis")
