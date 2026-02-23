"""
FastAPI application entry-point.

Run with:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes.health import router as health_router
from app.api.routes.courses import router as courses_router
from app.api.routes.documents import router as documents_router
from app.api.routes.topics import courses_router as topics_courses_router
from app.api.routes.topics import topics_router


# ── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown hook (placeholder for future resource init)."""
    # startup
    yield
    # shutdown


# ── App factory ──────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────
app.include_router(health_router, prefix="/api/v1")
app.include_router(courses_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(topics_courses_router, prefix="/api/v1")
app.include_router(topics_router, prefix="/api/v1")
