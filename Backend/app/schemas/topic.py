"""
Pydantic v2 schemas for the Topic resource.

- TopicCreate   : body for POST /courses/{id}/topics
- TopicUpdate   : body for PATCH /topics/{id}
- TopicResponse : shape returned by all endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


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

    # ── Extraction metadata (nullable for older/manual topics) ────
    source: str | None = None           # "AUTO" | "TOC" | "MANUAL"
    level: str | None = None            # "CHAPTER" | "SECTION" | "SUBSECTION"
    parent_topic_id: uuid.UUID | None = None

    # ── Quality/coverage metrics ──────────────────────────────────
    coverage_score: float | None = None
    # Number of chunks mapped to this topic — populated by the service layer
    chunk_count: int = 0

    created_at: datetime
    updated_at: datetime

    # ── Derived field ─────────────────────────────────────────────

    @computed_field  # type: ignore[misc]
    @property
    def is_noisy_suspect(self) -> bool:
        """
        True when the topic likely came from boilerplate or has near-zero
        chunk coverage.  Used by the UI to dim/hide low-quality topics.
        """
        if self.coverage_score is not None and self.coverage_score < 0.01:
            return True
        if self.chunk_count == 0 and self.is_auto_extracted:
            return True
        return False


# ── Extraction-meta response schemas ─────────────────────────────


class CourseExtractionMetaResponse(BaseModel):
    """Confidence/coverage info about the last topic extraction run."""

    model_config = ConfigDict(from_attributes=False)

    chosen_method: str
    overall_confidence: float
    is_low_confidence: bool
    coverage_ratio: float
    topic_count: int


class TopicListResponse(BaseModel):
    """Wraps a topic list with optional extraction metadata."""

    model_config = ConfigDict(from_attributes=False)

    topics: list[TopicResponse]
    extraction_meta: CourseExtractionMetaResponse | None = None
