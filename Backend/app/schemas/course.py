"""
Pydantic v2 schemas for the Course resource.

- CourseCreate  : body for POST /courses
- CourseUpdate  : body for PATCH /courses/{id}
- CourseResponse: shape returned by all endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Request schemas ───────────────────────────────────────────────


class CourseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Algorithms 101"])
    description: str | None = Field(
        default=None,
        max_length=4096,
        examples=["A first course on algorithm design."],
    )


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)


# ── Response schema ───────────────────────────────────────────────


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
