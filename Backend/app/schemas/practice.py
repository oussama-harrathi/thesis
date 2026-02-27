"""
Pydantic v2 schemas for Student Practice Sets.

Request schemas:
  CreatePracticeSetRequest  – body for POST /api/v1/student/practice-sets

Response schemas:
  PracticeSetResponse       – full practice set with all generated questions
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.question import Difficulty, QuestionSetMode, QuestionType
from app.schemas.question import QuestionResponse


# ── Request ───────────────────────────────────────────────────────────────────


class CreatePracticeSetRequest(BaseModel):
    """Body for POST /api/v1/student/practice-sets."""

    course_id: uuid.UUID = Field(
        description="UUID of the course to retrieve practice material from."
    )
    topic_ids: list[uuid.UUID] | None = Field(
        default=None,
        description=(
            "Optional topic UUIDs to constrain retrieval. "
            "If omitted, all course material is used."
        ),
    )
    question_types: list[QuestionType] = Field(
        default=[QuestionType.mcq],
        min_length=1,
        description="One or more question types to include in the practice set.",
    )
    count: int = Field(
        default=5,
        ge=1,
        le=30,
        description=(
            "Total target number of questions. "
            "Distributed evenly across requested types (and topics when supplied)."
        ),
    )
    difficulty: Difficulty | None = Field(
        default=None,
        description="Target difficulty level. Defaults to 'medium' when omitted.",
    )
    title: str | None = Field(
        default=None,
        max_length=255,
        description="Optional display name for the practice set.",
    )


# ── Response ──────────────────────────────────────────────────────────────────


class PracticeSetResponse(BaseModel):
    """Full practice set detail with all generated questions."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    mode: QuestionSetMode
    title: str | None
    created_at: datetime

    generated: int = Field(description="Number of questions successfully generated.")
    questions: list[QuestionResponse] = Field(default_factory=list)
