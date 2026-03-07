"""
Exam-related ORM models.

Tables
------
  exam_blueprints  – professor-defined configuration describing what an exam
                     should contain (question counts, difficulty mix, etc.)
                     Config is stored as a validated JSON string (config_json).
  exams            – assembled exam (ordered list of approved questions)
  exam_questions   – ordered question rows for an exam (with per-question points)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.question import Question

class ExamBlueprint(Base):
    """
    Professor-authored blueprint that describes the shape of an exam.

    The full configuration (question counts per type, difficulty mix, bloom mix,
    topic mix, total points, duration) is stored in ``config_json`` as a JSON
    string validated by ``BlueprintConfig`` on write and read.
    """

    __tablename__ = "exam_blueprints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Serialised BlueprintConfig JSON (validated via Pydantic on every
    # create / update before this field is written).
    config_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="blueprints",
        lazy="select",
    )
    exams: Mapped[list["Exam"]] = relationship(
        "Exam",
        back_populates="blueprint",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<ExamBlueprint id={self.id} course_id={self.course_id} title={self.title!r}>"


class Exam(Base):
    """
    An assembled exam: a titled collection of ordered, approved questions
    drawn from a question set associated with a blueprint.
    """

    __tablename__ = "exams"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_blueprints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_points: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    blueprint: Mapped["ExamBlueprint"] = relationship(
        "ExamBlueprint", back_populates="exams", lazy="select"
    )
    exam_questions: Mapped[list["ExamQuestion"]] = relationship(
        "ExamQuestion",
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="ExamQuestion.position",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Exam id={self.id} title={self.title!r}>"


class ExamQuestion(Base):
    """
    A single question slot within an assembled exam.

    Carries an ordered position (1-based) and optional per-question point value.
    """

    __tablename__ = "exam_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 1-based display order within the exam
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Optional points override; None means "use exam default"
    points: Mapped[float | None] = mapped_column(
        Numeric(precision=6, scale=2), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────
    exam: Mapped["Exam"] = relationship(
        "Exam", back_populates="exam_questions", lazy="select"
    )
    question: Mapped["Question"] = relationship(
        "Question", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<ExamQuestion id={self.id} exam_id={self.exam_id} pos={self.position}>"


class BlueprintQuestion(Base):
    """
    Many-to-many mapping between blueprints and questions.

    Created when a generation task saves a question to a blueprint's set.
    Used for replacement tracking and blueprint-scoped views.
    Deleting either side cascades here (question deleted → mapping gone,
    blueprint deleted → mapping gone).
    """

    __tablename__ = "blueprint_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_blueprints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Tracks the original blueprint if this question was imported via replacement.
    original_blueprint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_blueprints.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    blueprint: Mapped["ExamBlueprint"] = relationship(
        "ExamBlueprint",
        foreign_keys=[blueprint_id],
        lazy="select",
    )
    question: Mapped["Question"] = relationship(
        "Question",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<BlueprintQuestion blueprint={self.blueprint_id} question={self.question_id}>"
