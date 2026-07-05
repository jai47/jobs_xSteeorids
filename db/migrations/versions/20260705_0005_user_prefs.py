"""Add user preference columns for F02 (score warning threshold).

Revision ID: 20260705_0005
Revises: 20260625_0003
Create Date: 2026-07-05

Pulled forward from migration 0005 in docs/implementation/04_DATABASE_DESIGN.md.
Cover-letter and notification user columns ship with M2/M3 migrations.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260705_0005"
down_revision: Union[str, None] = "20260625_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("score_warning_threshold", sa.Integer(), nullable=False, server_default="40"),
    )


def downgrade() -> None:
    op.drop_column("users", "score_warning_threshold")
