"""
Pydantic v2 schemas for the Question resource.

API-facing shapes (not LLM output shapes — those live in llm_outputs.py).

Request schemas:
  GenerateMCQRequest       – body for POST .../generate/mcq
  GenerateTrueFalseRequest – body for POST .../generate/true-false
  MCQOptionUpdate          – one option row in a PATCH options list
  QuestionUpdateRequest    – body for PATCH /questions/{id}

Response schemas:
  MCQOptionResponse        – one A/B/C/D option (read-only)
  QuestionSourceResponse   – one source snippet + chunk reference
  QuestionResponse         – full question, with nested options + sources
  QuestionListResponse     – lightweight row for list views
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.question import BloomLevel, Difficulty, QuestionStatus, QuestionType


# ── Request schemas ───────────────────────────────────────────────────────────


class GenerateMCQRequest(BaseModel):
    """Body for POST /api/v1/courses/{course_id}/generate/mcq."""

    topic_id: uuid.UUID | None = Field(
        default=None,
        description="Optional topic UUID — enables topic-based chunk retrieval.",
    )
    topic_name: str = Field(
        default="General",
        min_length=1,
        max_length=255,
        description="Human-readable topic label embedded in the generation prompt.",
    )
    difficulty: Difficulty = Field(
        default=Difficulty.medium,
        description="Target difficulty level for generated questions.",
    )
    count: int = Field(
        default=1,
        ge=1,
        le=20,
        description="Number of MCQ questions to generate in this request.",
    )
    retrieval_query: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Free-text query for semantic chunk retrieval. "
            "Falls back to topic_name when omitted."
        ),
    )
    question_set_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "QuestionSet to attach questions to. "
            "A new set is created automatically when omitted."
        ),
    )


class GenerateTrueFalseRequest(BaseModel):
    """Body for POST /api/v1/courses/{course_id}/generate/true-false."""

    topic_id: uuid.UUID | None = Field(default=None)
    topic_name: str = Field(default="General", min_length=1, max_length=255)
    difficulty: Difficulty = Field(default=Difficulty.medium)
    count: int = Field(default=1, ge=1, le=20)
    retrieval_query: str | None = Field(default=None, max_length=512)
    question_set_id: uuid.UUID | None = Field(default=None)


class MCQOptionUpdate(BaseModel):
    """
    Describes changes to a single MCQ option in a PATCH request.

    Identify the option by ``id`` (UUID) or ``label`` (A/B/C/D).
    At least one identifier is required; when both are present, ``id`` wins.
    """

    id: uuid.UUID | None = Field(default=None, description="Option UUID (preferred identifier).")
    label: str | None = Field(
        default=None,
        pattern=r"^[A-D]$",
        description="Option label A–D (fallback identifier when id is omitted).",
    )
    text: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="Replacement option text.",
    )
    is_correct: bool | None = Field(
        default=None,
        description="Set to true to mark this option correct (clears others).",
    )

    @model_validator(mode="after")
    def has_identifier(self) -> "MCQOptionUpdate":
        if self.id is None and self.label is None:
            raise ValueError("Each MCQOptionUpdate must have either 'id' or 'label'.")
        return self


class QuestionUpdateRequest(BaseModel):
    """
    Body for PATCH /api/v1/questions/{question_id}.

    All fields are optional — only supplied (non-None) values are applied.

    MCQ option editing notes
    ─────────────────────────
    Supply ``mcq_options`` only for MCQ questions.  Each entry targets one
    option (by id or label) and changes its text/is_correct.
    The service ensures exactly one option is marked correct after applying
    all changes; a 422 is returned if the update would leave zero or multiple
    correct options.
    """

    body: str | None = Field(default=None, min_length=1, description="Question stem / text.")
    correct_answer: str | None = Field(
        default=None,
        description=(
            "For True/False and Short Answer: the authoritative answer string. "
            "For MCQ: ignored — correctness is driven by mcq_options.is_correct."
        ),
    )
    explanation: str | None = Field(
        default=None,
        description="Optional explanation shown after the answer is revealed.",
    )
    difficulty: Difficulty | None = Field(default=None)
    bloom_level: BloomLevel | None = Field(default=None)
    mcq_options: list[MCQOptionUpdate] | None = Field(
        default=None,
        description="Option edits for MCQ questions only. Ignored for other types.",
    )


# ── Response schemas ──────────────────────────────────────────────────────────


class MCQOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    text: str
    is_correct: bool


class QuestionSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_id: uuid.UUID | None
    snippet: str


class QuestionResponse(BaseModel):
    """Full question detail including nested options and sources."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_set_id: uuid.UUID
    type: QuestionType
    body: str
    correct_answer: str | None
    explanation: str | None
    difficulty: Difficulty
    bloom_level: BloomLevel | None
    status: QuestionStatus
    model_name: str | None
    prompt_version: str | None
    insufficient_context: bool
    created_at: datetime
    updated_at: datetime

    # Nested
    mcq_options: list[MCQOptionResponse] = Field(default_factory=list)
    sources: list[QuestionSourceResponse] = Field(default_factory=list)


class QuestionListResponse(BaseModel):
    """Lightweight row for list views — no nested options/sources."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_set_id: uuid.UUID
    type: QuestionType
    body: str
    difficulty: Difficulty
    bloom_level: BloomLevel | None
    status: QuestionStatus
    created_at: datetime

    # Blueprint context (populated from question_sets.blueprint_id join)
    blueprint_id: uuid.UUID | None = None
    blueprint_title: str | None = None

    # Blueprint context — populated when the question belongs to a blueprint's set.
    blueprint_id: uuid.UUID | None = None
    blueprint_title: str | None = None


class GenerationResponse(BaseModel):
    """Envelope returned by generation endpoints."""

    generated: int = Field(description="Number of questions successfully generated and saved.")
    questions: list[QuestionResponse]


class RejectRequest(BaseModel):
    """Optional body for POST /api/v1/questions/{id}/reject."""

    reason: str | None = Field(
        default=None,
        max_length=1024,
        description="Optional rejection reason stored in the question explanation field.",
    )


class QuestionStatusResponse(BaseModel):
    """Minimal response after approve/reject actions."""

    id: uuid.UUID
    status: QuestionStatus


# ── Replacement schemas ───────────────────────────────────────────────────────


class ReplacementCandidateResponse(BaseModel):
    """A candidate question that can replace another in a blueprint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: QuestionType
    body: str
    difficulty: Difficulty
    bloom_level: BloomLevel | None
    status: QuestionStatus
    blueprint_id: uuid.UUID | None = None
    blueprint_title: str | None = None


class ReplaceQuestionRequest(BaseModel):
    """Body for POST /blueprints/{blueprint_id}/questions/{question_id}/replace."""

    replacement_question_id: uuid.UUID = Field(
        description="ID of the approved question to use as the replacement."
    )
