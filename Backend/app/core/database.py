"""
SQLAlchemy 2.0 async engine, session factory, and declarative Base.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.config import settings

# ── Async engine ─────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
)

# ── Session factory ──────────────────────────────────────────────
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Declarative Base ─────────────────────────────────────────────
class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ── Dependency for FastAPI ───────────────────────────────────────
async def get_db() -> AsyncSession:  # type: ignore[misc]
    """Yield an async session and ensure it is closed after the request."""
    async with async_session_factory() as session:
        try:
            yield session # type: ignore
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Utility: check DB connectivity ───────────────────────────────
async def check_db_connection() -> bool:
    """Execute a lightweight query to verify the database is reachable."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
