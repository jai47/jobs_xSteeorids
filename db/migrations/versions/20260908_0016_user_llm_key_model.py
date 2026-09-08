"""Per-user BYOK model selection column.

Revision ID: 20260908_0016
Revises: 20260908_0015
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260908_0016"
down_revision: Union[str, None] = "20260908_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_llm_keys ADD COLUMN IF NOT EXISTS model VARCHAR"
    )
    # Migrate Groq BYOK rows still on the shut-down Llama id.
    op.execute(
        """
        UPDATE user_llm_keys
        SET model = 'openai/gpt-oss-120b'
        WHERE provider = 'groq'
          AND (model IS NULL OR model = '' OR model = 'llama-3.3-70b-versatile')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_llm_keys DROP COLUMN IF EXISTS model")
