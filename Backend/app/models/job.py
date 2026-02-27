"""
Job ORM model + JobStatus / JobType enums.

A Job tracks a single background task (e.g. document processing, question
generation).  It is created by an API endpoint and executed by a Celery worker.
Progress (0–100) and a human-readable message are updated as the work proceeds.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class JobStatus(str, enum.Enum):
    """Execution state of a background job."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobType(str, enum.Enum):
    """What kind of work the job performs."""
    document_processing = "document_processing"
    topic_extraction = "topic_extraction"
    question_generation = "question_generation"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ── Job classification ────────────────────────────────────────
    type: Mapped[JobType] = mapped_column(
        SAEnum(JobType, name="job_type", create_type=True),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status", create_type=True),
        nullable=False,
        default=JobStatus.pending,
        server_default=JobStatus.pending.value,
    )

    # ── Optional references to the subject of the job ─────────────
    # These are nullable soft foreign keys (no DB-level FK constraint) so that
    # jobs survive independent of whether the referenced row is deleted first.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    blueprint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_blueprints.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Progress tracking ─────────────────────────────────────────
    progress: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Job id={self.id} type={self.type.value} "
            f"status={self.status.value} progress={self.progress}>"
        )
