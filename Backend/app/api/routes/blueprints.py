"""
Blueprint API routes (Phase 9).

POST   /api/v1/courses/{course_id}/blueprints      → create blueprint
GET    /api/v1/courses/{course_id}/blueprints      → list blueprints for course
GET    /api/v1/blueprints/{blueprint_id}           → get single blueprint
PATCH  /api/v1/blueprints/{blueprint_id}           → partial update blueprint
POST   /api/v1/blueprints/{blueprint_id}/generate  → start generation job
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.blueprint import (
    BlueprintCreateRequest,
    BlueprintListItem,
    BlueprintResponse,
    BlueprintUpdateRequest,
)
from app.schemas.job import StartGenerationResponse
from app.services.blueprint_service import BlueprintService

# Two routers so we can mount them under different prefixes in main.py
courses_router = APIRouter(tags=["blueprints"])  # prefix: /courses/{course_id}/blueprints
blueprints_router = APIRouter(tags=["blueprints"])  # prefix: /blueprints

DbSession = Annotated[AsyncSession, Depends(get_db)]

_svc = BlueprintService()


# ── Course-scoped endpoints ────────────────────────────────────────────────────


@courses_router.post(
    "/courses/{course_id}/blueprints",
    response_model=BlueprintResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new exam blueprint for a course",
)
async def create_blueprint(
    course_id: uuid.UUID,
    payload: BlueprintCreateRequest,
    db: DbSession,
) -> BlueprintResponse:
    """
    Create a new exam blueprint scoped to *course_id*.

    The ``config`` body is fully validated by Pydantic before persistence —
    invalid proportions, missing question counts, or inconsistent topic totals
    will be rejected with **422 Unprocessable Entity**.
    """
    blueprint = await _svc.create(db, course_id=course_id, payload=payload)
    await db.commit()
    return BlueprintResponse.from_orm_model(blueprint)


@courses_router.get(
    "/courses/{course_id}/blueprints",
    response_model=list[BlueprintListItem],
    summary="List blueprints for a course",
)
async def list_blueprints(
    course_id: uuid.UUID,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[BlueprintListItem]:
    """
    Return all blueprints for *course_id*, newest first.

    Each item surfaces ``total_questions``, ``total_points``, and
    ``duration_minutes`` without returning the full config object —
    use **GET /blueprints/{blueprint_id}** for the complete config.
    """
    blueprints = await _svc.list_for_course(
        db, course_id=course_id, limit=limit, offset=offset
    )
    return [BlueprintListItem.from_orm_model(bp) for bp in blueprints]


# ── Singleton endpoints ────────────────────────────────────────────────────────


@blueprints_router.get(
    "/blueprints/{blueprint_id}",
    response_model=BlueprintResponse,
    summary="Get a single blueprint by ID",
)
async def get_blueprint(
    blueprint_id: uuid.UUID,
    db: DbSession,
) -> BlueprintResponse:
    """
    Return the full blueprint including the decoded ``config`` object.

    Raises **404** if the blueprint does not exist.
    """
    blueprint = await _svc.get_by_id(db, blueprint_id)
    if blueprint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blueprint {blueprint_id} not found.",
        )
    return BlueprintResponse.from_orm_model(blueprint)


@blueprints_router.patch(
    "/blueprints/{blueprint_id}",
    response_model=BlueprintResponse,
    summary="Partially update a blueprint",
)
async def update_blueprint(
    blueprint_id: uuid.UUID,
    payload: BlueprintUpdateRequest,
    db: DbSession,
) -> BlueprintResponse:
    """
    Apply a partial update to an existing blueprint.

    Only the fields present in the request body are changed.
    Supplying ``config`` replaces the entire configuration object
    (it is fully re-validated before storage).

    Raises **404** if the blueprint does not exist.
    """
    blueprint = await _svc.get_by_id(db, blueprint_id)
    if blueprint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blueprint {blueprint_id} not found.",
        )

    updated = await _svc.update(db, blueprint, payload=payload)
    await db.commit()
    return BlueprintResponse.from_orm_model(updated)


@blueprints_router.post(
    "/blueprints/{blueprint_id}/generate",
    response_model=StartGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a background question-generation job from a blueprint",
)
async def start_generation(
    blueprint_id: uuid.UUID,
    db: DbSession,
) -> StartGenerationResponse:
    """
    Dispatch a background Celery task to generate questions from *blueprint_id*.

    Steps performed synchronously before returning **202**:
    1. Load and validate the blueprint.
    2. Create a ``QuestionSet`` (professor mode) to hold the results.
    3. Create a pending ``Job`` row linking blueprint → course.
    4. Enqueue ``generate_from_blueprint`` on the Celery worker.

    The response immediately returns ``job_id`` and ``question_set_id``.
    Poll ``GET /api/v1/jobs/{job_id}`` to track progress.

    Raises **404** if the blueprint does not exist.
    """
    from app.workers.tasks import generate_from_blueprint
    from app.models.job import JobStatus

    blueprint = await _svc.get_by_id(db, blueprint_id)
    if blueprint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blueprint {blueprint_id} not found.",
        )

    job, question_set = await _svc.create_generation_job(db, blueprint)
    await db.commit()

    # Dispatch Celery task after DB commit so IDs are durable.
    generate_from_blueprint.delay(
        str(blueprint.id),
        str(job.id),
        str(question_set.id),
    )

    return StartGenerationResponse(
        job_id=job.id,
        question_set_id=question_set.id,
        blueprint_id=blueprint.id,
        status=JobStatus.pending,
    )
