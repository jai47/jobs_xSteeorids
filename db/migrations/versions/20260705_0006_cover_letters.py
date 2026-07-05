"""Cover letters table + user angle prompts (F01).

Revision ID: 20260705_0006
Revises: 20260705_0004
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "20260705_0006"
down_revision: Union[str, None] = "20260705_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ANGLES = (
    '{"why_company": "Explain genuine interest in the company mission and recent work.", '
    '"problem_i_solve": "Describe the problem this role addresses and how your experience maps to it.", '
    '"my_approach": "Highlight your approach to delivering results in similar contexts.", '
    '"tone": "Professional, concise, and confident — never arrogant."}'
)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("cover_letter_angles", JSONB(), nullable=False, server_default=DEFAULT_ANGLES),
    )
    op.create_table(
        "cover_letters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("generation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("angles_snapshot", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("application_id", name="uq_cover_letters_application_id"),
    )


def downgrade() -> None:
    op.drop_table("cover_letters")
    op.drop_column("users", "cover_letter_angles")
