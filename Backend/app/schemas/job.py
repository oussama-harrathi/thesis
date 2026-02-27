"""
Pydantic v2 schemas for the Job resource.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.job import JobStatus, JobType


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: JobType
    status: JobStatus
    document_id: uuid.UUID | None
    course_id: uuid.UUID | None
    blueprint_id: uuid.UUID | None
    progress: int
    message: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class StartGenerationResponse(BaseModel):
    """Response returned immediately when a blueprint generation job is dispatched."""

    job_id: uuid.UUID
    question_set_id: uuid.UUID
    blueprint_id: uuid.UUID
    status: JobStatus
