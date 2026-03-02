"""
QuestionBlacklist model.

When a professor rejects a question, an entry is written here so that
future generation runs for the same course automatically avoid questions
that are semantically similar to the rejected one.

Matching is done in two stages:
  1. Exact fingerprint match  (fast, no vectors needed).
  2. Embedding cosine similarity >= threshold (catches paraphrasing).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class QuestionBlacklist(Base):
    """Rejected question fingerprints/embeddings for a course."""

    __tablename__ = "question_blacklist"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Scope: blacklist is per-course so we don't accidentally block identical
    # phrasings in a completely different subject area.
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 of the normalised question stem.
    fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    # Sentence-Transformers embedding for semantic similarity check (may be NULL
    # for entries created by older code before embeddings were computed).
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384), nullable=True
    )
    # Back-reference to the original rejected Question (nullable: the question
    # may have been hard-deleted, or the entry created via migration).
    original_question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    # Optional human-readable rejection reason from the professor.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<QuestionBlacklist course={self.course_id} "
            f"fp={self.fingerprint[:16]}…>"
        )
