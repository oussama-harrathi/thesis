"""
Export ORM model.

Tracks every export job: which exam, what type (exam PDF, answer key PDF,
exam .tex, answer key .tex), where the output file lives, and whether
compilation succeeded or fell back to .tex.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.exam import Exam


# ── Enums ─────────────────────────────────────────────────────────


class ExportType(str, enum.Enum):
    exam_pdf = "exam_pdf"
    answer_key_pdf = "answer_key_pdf"
    exam_tex = "exam_tex"
    answer_key_tex = "answer_key_tex"


class ExportStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


# ── Model ─────────────────────────────────────────────────────────


class Export(Base):
    """
    One export record: a rendered (+ optionally compiled) document for an exam.

    ``file_path`` is relative to the process cwd (Backend/).
    ``status`` reflects the final outcome; ``error_message`` stores the
    reason when status == 'failed'.
    """

    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    export_type: Mapped[ExportType] = mapped_column(
        SAEnum(ExportType, name="export_type", create_type=True),
        nullable=False,
    )
    status: Mapped[ExportStatus] = mapped_column(
        SAEnum(ExportStatus, name="export_status", create_type=True),
        nullable=False,
        default=ExportStatus.pending,
        server_default=ExportStatus.pending.value,
    )
    # Path to the output file on disk (relative to Backend/)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    exam: Mapped["Exam"] = relationship("Exam", lazy="select")

    def __repr__(self) -> str:
        return (
            f"<Export id={self.id} exam_id={self.exam_id} "
            f"type={self.export_type.value} status={self.status.value}>"
        )
