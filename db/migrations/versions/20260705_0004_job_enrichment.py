"""Job enrichment columns (F06, F07, G8, F09a) + fx_rates table.

Revision ID: 20260705_0004
Revises: 20260705_0005
Create Date: 2026-07-05

Note: numbered 0004 per plan but applied after pulled-forward 0005 user prefs.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "20260705_0004"
down_revision: Union[str, None] = "20260705_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("rate_to_usd", sa.Float(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("currency"),
    )

    op.add_column("jobs", sa.Column("archetype", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("salary_min", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_max", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_currency", sa.String(length=3), nullable=True))
    op.add_column("jobs", sa.Column("salary_period", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("salary_usd_min", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_usd_max", sa.Integer(), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("salary_currency_assumed", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("jobs", sa.Column("legitimacy_flags", JSONB(), server_default="[]", nullable=False))
    op.add_column("jobs", sa.Column("dedup_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("description_hash", sa.String(length=32), nullable=True))
    op.add_column("jobs", sa.Column("repost_of_job_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_jobs_repost_of_job_id",
        "jobs",
        "jobs",
        ["repost_of_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_jobs_dedup_fingerprint", "jobs", ["dedup_fingerprint", "created_at"])
    op.create_index("ix_jobs_archetype", "jobs", ["archetype"])

    # Batched backfill via application code (import path set in env.py cwd).
    bind = op.get_bind()
    _backfill_jobs(bind)


def _backfill_jobs(connection) -> None:
    """Backfill fingerprint, hash, archetype, salary for existing rows."""
    from sqlalchemy.orm import Session

    from db.models import Job
    from pipeline.stages.fx_rates import refresh_fx_rates
    from pipeline.stages.job_enrichment import enrich_job_row

    session = Session(bind=connection)
    try:
        refresh_fx_rates(session)
        batch_size = 500
        offset = 0
        while True:
            rows = (
                session.query(Job)
                .order_by(Job.created_at.asc())
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not rows:
                break
            for job in rows:
                enrich_job_row(session, job)
            session.flush()
            offset += batch_size
    finally:
        session.close()


def downgrade() -> None:
    op.drop_index("ix_jobs_archetype", table_name="jobs")
    op.drop_index("ix_jobs_dedup_fingerprint", table_name="jobs")
    op.drop_constraint("fk_jobs_repost_of_job_id", "jobs", type_="foreignkey")
    for col in (
        "repost_of_job_id",
        "description_hash",
        "dedup_fingerprint",
        "legitimacy_flags",
        "salary_currency_assumed",
        "salary_usd_max",
        "salary_usd_min",
        "salary_period",
        "salary_currency",
        "salary_max",
        "salary_min",
        "archetype",
    ):
        op.drop_column("jobs", col)
    op.drop_table("fx_rates")
