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

    _maybe_stamp_alembic(target, after)
    return created


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
