"""
Synchronous SQLAlchemy session for Celery workers.

Celery tasks run in a plain synchronous context, so we cannot reuse the async
engine from app.core.database.  This module provides a lightweight sync session
factory backed by psycopg2.
"""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_sync_engine = create_engine(
    settings.DATABASE_URL_SYNC,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

_SyncSession = sessionmaker(bind=_sync_engine, expire_on_commit=False)


@contextmanager
def get_sync_db() -> Iterator[Session]:
    """Context-manager that yields a sync session and handles commit/rollback."""
    session: Session = _SyncSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
