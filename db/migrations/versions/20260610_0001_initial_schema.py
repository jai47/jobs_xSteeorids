"""Initial schema: all Phase 1 tables.

Revision ID: 20260610_0001
Revises:
Create Date: 2026-06-10

"""
from typing import Sequence, Union

from alembic import op

from db.models import Base

revision: str = "20260610_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)