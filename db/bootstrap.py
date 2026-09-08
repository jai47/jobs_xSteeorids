"""Idempotent schema bootstrap for empty or partially migrated databases."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from db.engine import engine
from db.models import Base

log = logging.getLogger(__name__)

# Tables the app always needs; used to decide whether to stamp Alembic.
_CORE_TABLES = ("users", "notifications", "pipeline_runs")


def _alembic_head_revision() -> str:
    """Resolve the current Alembic head without requiring a DB connection."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def ensure_schema(bind: Engine | None = None) -> list[str]:
    """Create any missing tables from the current SQLAlchemy models.

    Fresh Supabase projects often have no schema. Running ``alembic upgrade head``
    on an empty DB is unreliable here because revision ``0001`` uses
    ``Base.metadata.create_all`` (current models), then later revisions try to
    ``ADD COLUMN`` / ``CREATE TABLE`` objects that already exist and the whole
    transaction rolls back.

    ``create_all`` is idempotent: existing tables are left alone.
    Returns the names of tables that were newly created.
    """
    target = bind or engine
    before = set(inspect(target).get_table_names())
    Base.metadata.create_all(bind=target)
    after = set(inspect(target).get_table_names())
    created = sorted(after - before)

    if created:
        log.warning("Created missing DB tables: %s", ", ".join(created))
    else:
        log.info("DB schema OK (%d public tables)", len(after))

    _ensure_multi_tenant_columns(target)
    _ensure_token_billing_schema(target)
    _ensure_user_llm_context_table(target)
    _ensure_job_stale_tracking_columns(target)
    _maybe_stamp_alembic(target, after)
    return created


def _ensure_job_stale_tracking_columns(target: Engine) -> None:
    """Add discovery freshness columns used by the stale reconciler."""
    with target.begin() as conn:
        conn.execute(
            text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ")
        )
        conn.execute(
            text(
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS consecutive_misses "
                "INTEGER NOT NULL DEFAULT 0"
            )
        )
    log.info("Ensured jobs.last_seen_at / consecutive_misses columns")


def _ensure_user_llm_context_table(target: Engine) -> None:
    """Create user_llm_contexts if missing."""
    with target.begin() as conn:
        conn.execute(
            text(
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
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_llm_contexts_user_id "
                "ON user_llm_contexts (user_id)"
            )
        )
    log.info("Ensured user_llm_contexts table")


def _ensure_multi_tenant_columns(target: Engine) -> None:
    """Add per-user pipeline + budget columns on existing DBs (create_all won't ALTER)."""
    with target.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS llm_budget_usd "
                "DOUBLE PRECISION NOT NULL DEFAULT 1.0"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS user_id UUID "
                "REFERENCES users(id)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_run_date_key"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_user_run_date "
                "ON pipeline_runs (user_id, run_date)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_pipeline_runs_user_id "
                "ON pipeline_runs (user_id)"
            )
        )
    log.info("Ensured multi-tenant pipeline/budget columns")


def _ensure_token_billing_schema(target: Engine) -> None:
    """Add token billing / BYOK columns and seed billing config on existing DBs."""
    with target.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_balance "
                "INTEGER NOT NULL DEFAULT 1000"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin "
                "BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_llm_provider VARCHAR"
            )
        )
        conn.execute(
            text("ALTER TABLE user_llm_keys ADD COLUMN IF NOT EXISTS model VARCHAR")
        )
        conn.execute(
            text(
                """
                UPDATE user_llm_keys
                SET model = 'openai/gpt-oss-120b'
                WHERE provider = 'groq'
                  AND (model IS NULL OR model = '' OR model = 'llama-3.3-70b-versatile')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO app_billing_config (
                  id, pipeline_run_tokens, llm_call_tokens, signup_grant_tokens,
                  usd_per_thousand_tokens, updated_at
                )
                VALUES (1, 600, 5, 1000, 1.0, NOW())
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
    log.info("Ensured token billing / BYOK columns")


def _maybe_stamp_alembic(target: Engine, tables: set[str]) -> None:
    """Record head revision when core tables exist but Alembic has no version row."""
    if not all(name in tables for name in _CORE_TABLES):
        return

    head = _alembic_head_revision()
    with target.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        if rows:
            return
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": head},
        )
        log.info("Stamped alembic_version to %s", head)
