"""
Pydantic v2 schemas for the Exam resource.

Request schemas:
  AssembleExamRequest        – body for POST /blueprints/{id}/assemble
  AddExamQuestionRequest     – body for POST /exams/{id}/questions
  ReorderExamQuestionsRequest – body for PATCH /exams/{id}/questions/reorder

Response schemas:
  ExamQuestionResponse       – one row in an assembled exam
  ExamResponse               – full exam with nested exam_questions
  ExamListItem               – lightweight row for list views
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.question import QuestionResponse


# ── Request schemas ───────────────────────────────────────────────────────────


class AssembleExamRequest(BaseModel):
    """
    Body for POST /api/v1/blueprints/{blueprint_id}/assemble.

    Collects all ``approved`` questions from the blueprint's associated
    question sets, orders them by type then difficulty, and creates an Exam
    with ExamQuestion rows.
    """

    title: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable exam title.",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional exam description / instructions.",
    )
    default_points_per_question: float | None = Field(
        default=None,
        gt=0,
        description=(
            "When supplied, each ExamQuestion is initialised with this point value. "
            "Individual values can be overridden later via PATCH /exams/{id}/questions/reorder."
        ),
    )
    question_set_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Restrict assembly to a specific question set. "
            "When omitted, all approved questions from all sets in the blueprint's "
            "course are assembled."
        ),
    )


class AddExamQuestionRequest(BaseModel):
    """Body for POST /api/v1/exams/{exam_id}/questions."""

    question_id: uuid.UUID = Field(description="UUID of the approved question to add.")
    points: float | None = Field(
        default=None,
        gt=0,
        description="Override point value for this question.",
    )


class ReorderItem(BaseModel):
    """One row in a reorder patch."""

    exam_question_id: uuid.UUID = Field(description="ExamQuestion row UUID.")
    position: Annotated[int, Field(ge=1)] = Field(description="New 1-based position.")
    points: float | None = Field(
        default=None,
        gt=0,
        description="Update points for this question simultaneously.",
    )


class ReorderExamQuestionsRequest(BaseModel):
    """
    Body for PATCH /api/v1/exams/{exam_id}/questions/reorder.

    Supply the complete desired ordering.  Positions are applied as-is —
    duplicates are rejected with 422.
    """

    items: list[ReorderItem] = Field(min_length=1)


# ── Response schemas ──────────────────────────────────────────────────────────


class ExamQuestionResponse(BaseModel):
    """One exam-question slot: position, optional points, and the full question."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exam_id: uuid.UUID
    question_id: uuid.UUID
    position: int
    points: float | None

    # nested full question detail
    question: QuestionResponse


class ExamResponse(BaseModel):
    """Full assembled exam with all ordered question slots."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    blueprint_id: uuid.UUID
    course_id: uuid.UUID
    title: str
    description: str | None
    total_points: int | None
    created_at: datetime
    updated_at: datetime

    exam_questions: list[ExamQuestionResponse] = Field(default_factory=list)


class ExamListItem(BaseModel):
    """Lightweight exam row for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    blueprint_id: uuid.UUID
    course_id: uuid.UUID
    title: str
    description: str | None
    total_points: int | None
    question_count: int = Field(
        default=0,
        description="Number of questions in this exam.",
    )
    created_at: datetime
    updated_at: datetime
