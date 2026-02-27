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
from app.api.routes.generation import router as generation_router
from app.api.routes.blueprints import courses_router as blueprints_courses_router
from app.api.routes.blueprints import blueprints_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.questions import router as questions_router
from app.api.routes.exams import blueprints_router as exams_blueprints_router
from app.api.routes.exams import exams_router
from app.api.routes.student_practice import router as student_practice_router
from app.api.routes.exports import exams_export_router
from app.api.routes.exports import exports_router as exports_dl_router


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
# In development / thesis MVP we allow all origins so the Vite dev server
# (or any port) can reach the API without CORS errors.
_cors_origins = settings.CORS_ORIGINS if not settings.DEBUG else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,  # credentials not supported with wildcard origin
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────
app.include_router(health_router, prefix="/api/v1")
app.include_router(courses_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(topics_courses_router, prefix="/api/v1")
app.include_router(topics_router, prefix="/api/v1")
app.include_router(generation_router, prefix="/api/v1")
app.include_router(blueprints_courses_router, prefix="/api/v1")
app.include_router(blueprints_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(questions_router, prefix="/api/v1")
app.include_router(exams_blueprints_router, prefix="/api/v1")
app.include_router(exams_router, prefix="/api/v1")
app.include_router(student_practice_router, prefix="/api/v1")
app.include_router(exams_export_router, prefix="/api/v1/exams")
app.include_router(exports_dl_router, prefix="/api/v1/exports")
