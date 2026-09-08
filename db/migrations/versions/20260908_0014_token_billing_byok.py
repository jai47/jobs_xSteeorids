"""Token billing, BYOK columns, ledger, and admin flags.

Revision ID: 20260908_0014
Revises: 20260908_0013
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260908_0014"
down_revision: Union[str, None] = "20260908_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_balance INTEGER NOT NULL DEFAULT 1000"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_llm_provider VARCHAR"
    )
    # Migrate leftover dollar budgets into tokens when balance is still the default.
    op.execute(
        """
        UPDATE users
        SET token_balance = GREATEST(0, ROUND(COALESCE(llm_budget_usd, 1.0) * 1000)::INTEGER)
        WHERE token_balance = 1000
          AND COALESCE(llm_budget_usd, 1.0) <> 1.0
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_llm_keys (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id),
          provider VARCHAR NOT NULL,
          ciphertext TEXT NOT NULL,
          key_hint VARCHAR(8) NOT NULL DEFAULT '',
          updated_at TIMESTAMPTZ,
          CONSTRAINT uq_user_llm_provider UNIQUE (user_id, provider)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_llm_keys_user_id ON user_llm_keys (user_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS token_ledger (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id),
          delta INTEGER NOT NULL,
          balance_after INTEGER NOT NULL,
          reason VARCHAR NOT NULL,
          ref_id VARCHAR,
          note TEXT,
          created_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_token_ledger_user_id ON token_ledger (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_token_ledger_created_at ON token_ledger (created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_billing_config (
          id INTEGER PRIMARY KEY,
          pipeline_run_tokens INTEGER NOT NULL DEFAULT 600,
          llm_call_tokens INTEGER NOT NULL DEFAULT 5,
          signup_grant_tokens INTEGER NOT NULL DEFAULT 1000,
          usd_per_thousand_tokens DOUBLE PRECISION NOT NULL DEFAULT 1.0,
          updated_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        INSERT INTO app_billing_config (
          id, pipeline_run_tokens, llm_call_tokens, signup_grant_tokens,
          usd_per_thousand_tokens, updated_at
        )
        VALUES (1, 600, 5, 1000, 1.0, NOW())
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_billing_config")
    op.execute("DROP TABLE IF EXISTS token_ledger")
    op.execute("DROP TABLE IF EXISTS user_llm_keys")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS preferred_llm_provider")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_admin")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS token_balance")
