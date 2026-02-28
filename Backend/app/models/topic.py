"""
Topic and TopicChunkMap ORM models.

Topics are extracted from course materials (heuristic or LLM-assisted).
TopicChunkMap records which chunks are relevant to each topic, along with a
relevance score that can be used to weight retrieval.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.chunk import Chunk


class Topic(Base):
    __tablename__ = "topics"

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # True if auto-extracted; False if manually added by professor
    is_auto_extracted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ── Hierarchy & metadata (added in migration c1d2e3f4a5b6) ───
    parent_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # "CHAPTER" | "SECTION" | "SUBSECTION" — populated for TOC-extracted topics
    level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "AUTO" | "TOC" | "MANUAL"
    source: Mapped[str | None] = mapped_column(
        String(32), nullable=True, server_default="AUTO"
    )
    # Fraction of course chunks mapped to this topic (0–1); None until computed
    coverage_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    course: Mapped[Course] = relationship("Course", lazy="select")
    chunk_mappings: Mapped[list[TopicChunkMap]] = relationship(
        "TopicChunkMap",
        back_populates="topic",
        cascade="all, delete-orphan",
    )
    # Self-referential: children of this topic
    children: Mapped[list[Topic]] = relationship(
        "Topic",
        foreign_keys="Topic.parent_topic_id",
        back_populates="parent",
        lazy="select",
    )
    parent: Mapped[Topic | None] = relationship(
        "Topic",
        foreign_keys="Topic.parent_topic_id",
        back_populates="children",
        remote_side="Topic.id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Topic id={self.id} name={self.name!r} level={self.level!r}>"


class TopicChunkMap(Base):
    """Association table: which chunks are relevant to a topic."""

    __tablename__ = "topic_chunk_map"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relevance_score: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────
    topic: Mapped[Topic] = relationship("Topic", back_populates="chunk_mappings")
    chunk: Mapped[Chunk] = relationship("Chunk", back_populates="topic_mappings")

    def __repr__(self) -> str:
        return (
            f"<TopicChunkMap topic={self.topic_id} chunk={self.chunk_id} "
            f"score={self.relevance_score}>"
        )
