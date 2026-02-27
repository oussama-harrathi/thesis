"""
Jobs API routes (Phase 9).

GET  /api/v1/jobs/{job_id}  → fetch status of a background job
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.job import Job
from app.schemas.job import JobResponse

router = APIRouter(tags=["jobs"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get the status of a background job",
)
async def get_job(
    job_id: uuid.UUID,
    db: DbSession,
) -> JobResponse:
    """
    Return the current status of the job identified by *job_id*.

    Useful for polling the progress of a blueprint generation job dispatched
    by ``POST /api/v1/blueprints/{blueprint_id}/generate``.

    Response fields
    ---------------
    - ``status``   — ``pending | running | completed | failed``
    - ``progress`` — integer 0–100
    - ``message``  — human-readable progress description
    - ``error``    — set on failure, otherwise null

    Raises **404** if the job does not exist.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )
    return JobResponse.model_validate(job)
