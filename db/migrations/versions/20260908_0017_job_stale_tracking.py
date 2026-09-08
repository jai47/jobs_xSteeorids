"""Job discovery freshness columns for stale reconciliation.

Revision ID: 20260908_0017
Revises: 20260908_0016
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260908_0017"
down_revision: Union[str, None] = "20260908_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS consecutive_misses INTEGER "
        "NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS consecutive_misses")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS last_seen_at")
