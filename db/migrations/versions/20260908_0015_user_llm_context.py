"""Persisted per-user resume + jobs LLM context.

Revision ID: 20260908_0015
Revises: 20260908_0014
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260908_0015"
down_revision: Union[str, None] = "20260908_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_llm_contexts (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
          master_resume_id UUID REFERENCES master_resumes(id) ON DELETE SET NULL,
          resume_summary TEXT NOT NULL DEFAULT '',
          jobs_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
          context_text TEXT NOT NULL DEFAULT '',
          built_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_llm_contexts_user_id ON user_llm_contexts (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_llm_contexts")
