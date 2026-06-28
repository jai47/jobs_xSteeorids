"""Add latex_source to resume_versions.

Revision ID: 20260625_0003
Revises: 20260625_0002
Create Date: 2026-06-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_0003"
down_revision: Union[str, None] = "20260625_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resume_versions", sa.Column("latex_source", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("resume_versions", "latex_source")
