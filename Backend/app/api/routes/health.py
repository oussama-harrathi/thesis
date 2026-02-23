"""
Health-check endpoints.

GET /api/v1/health       → basic liveness check
GET /api/v1/health/db    → database connectivity check
"""

from fastapi import APIRouter

from app.core.config import settings
from app.core.database import check_db_connection

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict:
    """Return basic application status."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@router.get("/db")
async def health_db() -> dict:
    """Check database connectivity and return status."""
    db_ok = await check_db_connection()
    return {
        "status": "healthy" if db_ok else "unhealthy",
        "database_connected": db_ok,
    }
