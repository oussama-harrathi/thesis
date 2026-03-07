"""
Chunk ORM model.

A Chunk is a piece of text extracted from a Document during the ingestion
pipeline.  Each chunk stores its raw text plus a pgvector embedding
(all-MiniLM-L6-v2, dim=384) for semantic retrieval.

chunk_type classifies the chunk's educational content role so that
retrieval can hard-filter out admin/boilerplate at the DB level.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SaEnum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

from app.core.database import Base
from app.utils.chunk_classifier import ChunkType  # noqa: F401 – re-exported for ORM usage

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.topic import TopicChunkMap


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Text content ──────────────────────────────────────────────
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Page range (1-based) -- populated when extraction result is available
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Embedding (pgvector, dim=384) ─────────────────────────────
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384), nullable=True
    )

    # ── Content classification (set during ingestion) ─────────────
    # Deterministic rule-based: see app.utils.chunk_classifier.
    # Used for hard DB-level filtering at retrieval time so admin / boilerplate
    # chunks are never included in question-generation context.
    chunk_type: Mapped[ChunkType] = mapped_column(
        SaEnum(ChunkType, name="chunktype", create_constraint=True),
        nullable=False,
        default=ChunkType.instructional,
        server_default=ChunkType.instructional.value,
        index=True,
    )
    chunk_type_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    document: Mapped[Document] = relationship(
        "Document",
        lazy="select",
    )
    topic_mappings: Mapped[list[TopicChunkMap]] = relationship(
        "TopicChunkMap",
        back_populates="chunk",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Chunk id={self.id} doc={self.document_id} idx={self.chunk_index}>"
