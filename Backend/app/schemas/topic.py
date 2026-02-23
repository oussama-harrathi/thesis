"""
Pydantic v2 schemas for the Topic resource.

- TopicCreate   : body for POST /courses/{id}/topics
- TopicUpdate   : body for PATCH /topics/{id}
- TopicResponse : shape returned by all endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Request schemas ───────────────────────────────────────────────


class TopicCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Relational Algebra"])


class TopicUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


# ── Response schema ───────────────────────────────────────────────


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    name: str
    is_auto_extracted: bool
    created_at: datetime
    updated_at: datetime
