from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from config import settings


def _engine_kwargs() -> dict[str, Any]:
    """Pool settings: NullPool for PgBouncer transaction mode (Supabase :6543)."""
    if settings.uses_pgbouncer:
        return {
            "poolclass": NullPool,
            "pool_pre_ping": True,
        }
    return {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 3600,
        "pool_timeout": 30,
    }


engine = create_engine(settings.database_url, **_engine_kwargs())

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_db_connection() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
