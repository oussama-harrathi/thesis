"""
Chunk ORM model.

A Chunk is a piece of text extracted from a Document during the ingestion
pipeline.  Each chunk stores its raw text plus a pgvector embedding
(all-MiniLM-L6-v2, dim=384) for semantic retrieval.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

from app.core.database import Base

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
