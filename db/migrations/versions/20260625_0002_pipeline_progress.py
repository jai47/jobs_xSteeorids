"""Add pipeline run progress fields.

Revision ID: 20260625_0002
Revises: 20260610_0001
Create Date: 2026-06-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_0002"
down_revision: Union[str, None] = "20260610_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("current_stage", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("progress_log", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_runs", "progress_log")
    op.drop_column("pipeline_runs", "current_stage")
