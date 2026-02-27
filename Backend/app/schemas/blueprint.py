"""
Pydantic v2 schemas for the ExamBlueprint resource.

Blueprint config is defined as the nested ``BlueprintConfig`` model.
It is validated on every create/update and stored serialised as JSON
in ``ExamBlueprint.config_json``.

Structure
---------
BlueprintConfig
├── question_counts    QuestionTypeCounts  – counts per question type
├── difficulty_mix     DifficultyMix       – fraction per difficulty (must sum ≈ 1.0)
├── bloom_mix          BloomMix | None     – optional fraction per Bloom level
├── topic_mix          TopicMix            – auto (even spread) or manual (per-topic counts)
├── total_points       int                 – total exam score budget
└── duration_minutes   int | None          – exam duration in minutes

API schemas
-----------
BlueprintCreateRequest   – POST body
BlueprintUpdateRequest   – PATCH body (all fields optional)
BlueprintResponse        – full response; config_json decoded as BlueprintConfig
BlueprintListItem        – lightweight row for list views
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ═══════════════════════════════════════════════════════════════════
# Nested config models
# ═══════════════════════════════════════════════════════════════════


class QuestionTypeCounts(BaseModel):
    """
    Number of questions to generate per question type.

    At least one count must be > 0.
    """

    mcq: int = Field(default=0, ge=0, description="Number of MCQ questions.")
    true_false: int = Field(default=0, ge=0, description="Number of True/False questions.")
    short_answer: int = Field(default=0, ge=0, description="Number of Short Answer questions.")
    essay: int = Field(default=0, ge=0, description="Number of Essay / Development questions.")

    @model_validator(mode="after")
    def at_least_one(self) -> "QuestionTypeCounts":
        total = self.mcq + self.true_false + self.short_answer + self.essay
        if total < 1:
            raise ValueError("question_counts must contain at least one question (total ≥ 1).")
        return self

    @property
    def total(self) -> int:
        return self.mcq + self.true_false + self.short_answer + self.essay


class DifficultyMix(BaseModel):
    """
    Fraction of questions per difficulty level.

    Values are proportions (0.0–1.0).  They should sum to approximately 1.0;
    a tolerance of ±0.01 is allowed to accommodate floating-point rounding.
    Set all to 0.0 will be rejected.
    """

    easy: float = Field(default=0.34, ge=0.0, le=1.0)
    medium: float = Field(default=0.33, ge=0.0, le=1.0)
    hard: float = Field(default=0.33, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def proportions_sum_to_one(self) -> "DifficultyMix":
        total = self.easy + self.medium + self.hard
        if total < 0.99 or total > 1.01:
            raise ValueError(
                f"difficulty_mix proportions must sum to 1.0 (got {total:.4f})."
            )
        return self


class BloomMix(BaseModel):
    """
    Optional fraction of questions targeting each Bloom taxonomy level.

    When provided, values must sum to approximately 1.0.
    Omit entirely to have the system assign bloom levels automatically.
    """

    remember: float = Field(default=0.0, ge=0.0, le=1.0)
    understand: float = Field(default=0.0, ge=0.0, le=1.0)
    apply: float = Field(default=0.0, ge=0.0, le=1.0)
    analyze: float = Field(default=0.0, ge=0.0, le=1.0)
    evaluate: float = Field(default=0.0, ge=0.0, le=1.0)
    create: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def proportions_sum_to_one(self) -> "BloomMix":
        total = (
            self.remember
            + self.understand
            + self.apply
            + self.analyze
            + self.evaluate
            + self.create
        )
        if total < 0.99 or total > 1.01:
            raise ValueError(
                f"bloom_mix proportions must sum to 1.0 (got {total:.4f})."
            )
        return self


class TopicEntry(BaseModel):
    """A single topic and the number of questions to draw from it."""

    topic_id: uuid.UUID = Field(..., description="UUID of an existing topic for this course.")
    question_count: int = Field(..., ge=1, description="Questions to draw from this topic.")


class TopicMix(BaseModel):
    """
    Controls how questions are distributed across topics.

    mode="auto"   – questions are distributed evenly across all course topics.
    mode="manual" – professor specifies a list of TopicEntry items; the counts
                    must sum to the total question count in QuestionTypeCounts.
    """

    mode: Literal["auto", "manual"] = Field(
        default="auto",
        description="'auto' for even distribution, 'manual' for per-topic counts.",
    )
    topics: list[TopicEntry] = Field(
        default_factory=list,
        description="Required when mode='manual'. Ignored when mode='auto'.",
    )

    @model_validator(mode="after")
    def manual_requires_topics(self) -> "TopicMix":
        if self.mode == "manual" and len(self.topics) == 0:
            raise ValueError(
                "topic_mix.topics must not be empty when mode='manual'."
            )
        return self


class BlueprintConfig(BaseModel):
    """
    Full validated configuration for an exam blueprint.

    This is the canonical shape stored in ``ExamBlueprint.config_json``.
    All nested models carry their own validators so the config can never
    be stored in an inconsistent state.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question_counts": {"mcq": 10, "true_false": 5, "short_answer": 3, "essay": 2},
                "difficulty_mix": {"easy": 0.30, "medium": 0.40, "hard": 0.30},
                "bloom_mix": None,
                "topic_mix": {"mode": "auto", "topics": []},
                "total_points": 100,
                "duration_minutes": 90,
            }
        }
    )

    question_counts: QuestionTypeCounts = Field(
        ...,
        description="Number of questions per type.",
    )
    difficulty_mix: DifficultyMix = Field(
        default_factory=DifficultyMix,
        description="Target proportion per difficulty level (must sum to 1.0).",
    )
    bloom_mix: BloomMix | None = Field(
        default=None,
        description="Optional target proportion per Bloom level (must sum to 1.0 if provided).",
    )
    topic_mix: TopicMix = Field(
        default_factory=TopicMix,
        description="Topic distribution mode and optional per-topic counts.",
    )
    total_points: int = Field(
        default=100,
        ge=1,
        description="Total points available in the exam.",
    )
    duration_minutes: int | None = Field(
        default=None,
        ge=5,
        description="Exam duration in minutes (optional).",
    )

    @model_validator(mode="after")
    def manual_topic_counts_match_total(self) -> "BlueprintConfig":
        """
        When topic_mix.mode='manual', the sum of per-topic question_counts
        must equal the total question count.
        """
        if self.topic_mix.mode == "manual":
            topic_total = sum(t.question_count for t in self.topic_mix.topics)
            q_total = self.question_counts.total
            if topic_total != q_total:
                raise ValueError(
                    f"topic_mix manual counts ({topic_total}) must equal the total "
                    f"question count ({q_total})."
                )
        return self


# ═══════════════════════════════════════════════════════════════════
# API-facing request / response schemas
# ═══════════════════════════════════════════════════════════════════


class BlueprintCreateRequest(BaseModel):
    """Body for POST /api/v1/courses/{course_id}/blueprints."""

    title: str = Field(..., min_length=1, max_length=255, description="Blueprint title.")
    description: str | None = Field(default=None, max_length=2048)
    config: BlueprintConfig = Field(
        ...,
        description="Full blueprint configuration.",
    )


class BlueprintUpdateRequest(BaseModel):
    """Body for PATCH /api/v1/blueprints/{blueprint_id}. All fields optional."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2048)
    config: BlueprintConfig | None = Field(
        default=None,
        description="If provided, replaces the entire config.",
    )


class BlueprintResponse(BaseModel):
    """Full blueprint response including decoded config."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    description: str | None
    config: BlueprintConfig
    created_at: datetime
    updated_at: datetime

    @field_validator("config", mode="before")
    @classmethod
    def parse_config_json(cls, v: object) -> BlueprintConfig:
        """
        Accept either:
          - a raw JSON string (from the ORM ``config_json`` column), or
          - a dict / BlueprintConfig instance (e.g. from tests).
        """
        if isinstance(v, str):
            return BlueprintConfig.model_validate(json.loads(v))
        if isinstance(v, dict):
            return BlueprintConfig.model_validate(v)
        if isinstance(v, BlueprintConfig):
            return v
        raise ValueError(f"Cannot parse BlueprintConfig from {type(v)}")

    @classmethod
    def from_orm_model(cls, bp: object) -> "BlueprintResponse":
        """
        Build a BlueprintResponse from any object that has .id, .course_id,
        .title, .description, .config_json, .created_at, .updated_at.
        """
        return cls(
            id=bp.id,  # type: ignore[attr-defined]
            course_id=bp.course_id,  # type: ignore[attr-defined]
            title=bp.title,  # type: ignore[attr-defined]
            description=bp.description,  # type: ignore[attr-defined]
            config=bp.config_json,  # type: ignore[attr-defined]  — triggers parse_config_json
            created_at=bp.created_at,  # type: ignore[attr-defined]
            updated_at=bp.updated_at,  # type: ignore[attr-defined]
        )


class BlueprintListItem(BaseModel):
    """Lightweight blueprint row for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    description: str | None
    # Surface the total question count and duration without full config decode.
    total_questions: int
    total_points: int
    duration_minutes: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, bp: object) -> "BlueprintListItem":
        config = BlueprintConfig.model_validate(
            json.loads(bp.config_json)  # type: ignore[attr-defined]
        )
        return cls(
            id=bp.id,  # type: ignore[attr-defined]
            course_id=bp.course_id,  # type: ignore[attr-defined]
            title=bp.title,  # type: ignore[attr-defined]
            description=bp.description,  # type: ignore[attr-defined]
            total_questions=config.question_counts.total,
            total_points=config.total_points,
            duration_minutes=config.duration_minutes,
            created_at=bp.created_at,  # type: ignore[attr-defined]
            updated_at=bp.updated_at,  # type: ignore[attr-defined]
        )
