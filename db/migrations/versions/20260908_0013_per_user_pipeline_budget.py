"""Per-user pipeline runs + llm_budget_usd on users.

Revision ID: 20260908_0013
Revises: 20260724_0012
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260908_0013"
down_revision: Union[str, None] = "20260724_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS llm_budget_usd "
        "DOUBLE PRECISION NOT NULL DEFAULT 1.0"
    )
    op.execute(
        "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS user_id UUID"
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_pipeline_runs_user_id'
          ) THEN
            ALTER TABLE pipeline_runs
              ADD CONSTRAINT fk_pipeline_runs_user_id
              FOREIGN KEY (user_id) REFERENCES users(id);
          END IF;
        END $$;
        """
    )
    # Drop legacy one-run-per-day unique if present (name varies).
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'pipeline_runs_run_date_key'
          ) THEN
            ALTER TABLE pipeline_runs DROP CONSTRAINT pipeline_runs_run_date_key;
          END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_user_run_date "
        "ON pipeline_runs (user_id, run_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pipeline_runs_user_id ON pipeline_runs (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pipeline_runs_user_id")
    op.execute("DROP INDEX IF EXISTS uq_pipeline_user_run_date")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_pipeline_runs_user_id'
          ) THEN
            ALTER TABLE pipeline_runs DROP CONSTRAINT fk_pipeline_runs_user_id;
          END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE pipeline_runs DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS llm_budget_usd")
    op.execute(
        "ALTER TABLE pipeline_runs ADD CONSTRAINT pipeline_runs_run_date_key UNIQUE (run_date)"
    )
