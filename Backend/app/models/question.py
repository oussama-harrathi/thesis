"""
Question-related ORM models + enums.

Tables:
  question_sets         – a batch of questions (professor blueprint or student practice)
  questions             – individual questions
  mcq_options           – answer choices for MCQ questions
  question_sources      – traceability: which chunks backed each question
  question_validations  – quality-control results per question
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk


# ── Enums ─────────────────────────────────────────────────────────

class QuestionSetMode(str, enum.Enum):
    professor = "professor"
    student = "student"


class QuestionType(str, enum.Enum):
    mcq = "mcq"
    true_false = "true_false"
    short_answer = "short_answer"
    essay = "essay"


class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class BloomLevel(str, enum.Enum):
    remember = "remember"
    understand = "understand"
    apply = "apply"
    analyze = "analyze"
    evaluate = "evaluate"
    create = "create"


class QuestionStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"


# ── Models ────────────────────────────────────────────────────────

class QuestionSet(Base):
    """A named batch of generated questions (professor exam prep or student practice)."""

    __tablename__ = "question_sets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[QuestionSetMode] = mapped_column(
        SAEnum(QuestionSetMode, name="question_set_mode", create_type=True),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    questions: Mapped[list[Question]] = relationship(
        "Question",
        back_populates="question_set",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<QuestionSet id={self.id} mode={self.mode.value}>"


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    question_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Content ───────────────────────────────────────────────────
    type: Mapped[QuestionType] = mapped_column(
        SAEnum(QuestionType, name="question_type", create_type=True),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Tagging ───────────────────────────────────────────────────
    difficulty: Mapped[Difficulty] = mapped_column(
        SAEnum(Difficulty, name="difficulty", create_type=True),
        nullable=False,
        default=Difficulty.medium,
        server_default=Difficulty.medium.value,
    )
    bloom_level: Mapped[BloomLevel | None] = mapped_column(
        SAEnum(BloomLevel, name="bloom_level", create_type=True),
        nullable=True,
    )
    status: Mapped[QuestionStatus] = mapped_column(
        SAEnum(QuestionStatus, name="question_status", create_type=True),
        nullable=False,
        default=QuestionStatus.draft,
        server_default=QuestionStatus.draft.value,
    )

    # ── Generation metadata ───────────────────────────────────────
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    insufficient_context: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # ── Diversity / fingerprint ───────────────────────────────────
    # SHA-256 of normalised question stem — used for exact-duplicate detection.
    fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    # Sentence-Transformers embedding (all-MiniLM-L6-v2, dim=384).
    # Enables semantic near-duplicate detection against blacklist and recent runs.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384), nullable=True
    )
    # The QuestionSet id (= job's question_set_id) this question belongs to,
    # stored as a convenience for cross-run analytics without extra joins.
    generation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    question_set: Mapped[QuestionSet] = relationship(
        "QuestionSet", back_populates="questions"
    )
    mcq_options: Mapped[list[McqOption]] = relationship(
        "McqOption",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="McqOption.label",
    )
    sources: Mapped[list[QuestionSource]] = relationship(
        "QuestionSource",
        back_populates="question",
        cascade="all, delete-orphan",
    )
    validations: Mapped[list[QuestionValidation]] = relationship(
        "QuestionValidation",
        back_populates="question",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Question id={self.id} type={self.type.value} status={self.status.value}>"


class McqOption(Base):
    """One answer choice for an MCQ question (A / B / C / D)."""

    __tablename__ = "mcq_options"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(4), nullable=False)   # "A" … "D"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    question: Mapped[Question] = relationship("Question", back_populates="mcq_options")

    def __repr__(self) -> str:
        return f"<McqOption {self.label} correct={self.is_correct}>"


class QuestionSource(Base):
    """Traceability: which chunk snippet was used to generate this question."""

    __tablename__ = "question_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    snippet: Mapped[str] = mapped_column(Text, nullable=False)

    question: Mapped[Question] = relationship("Question", back_populates="sources")
    chunk: Mapped[Chunk | None] = relationship("Chunk", lazy="select")

    def __repr__(self) -> str:
        return f"<QuestionSource question={self.question_id} chunk={self.chunk_id}>"


class QuestionValidation(Base):
    """Result of a single quality-control check on a question."""

    __tablename__ = "question_validations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # e.g. "grounding", "difficulty_tag", "bloom_tag", "distractor_validation", "duplicate"
    validation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    question: Mapped[Question] = relationship("Question", back_populates="validations")

    def __repr__(self) -> str:
        return (
            f"<QuestionValidation type={self.validation_type!r} passed={self.passed}>"
        )
