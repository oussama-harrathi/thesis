"""
ChunkPersistenceService — saves TextChunks + embeddings to the database.

Designed for use inside Celery workers (synchronous SQLAlchemy session).

Pipeline
────────
1. Receive list[TextChunk] + list[list[float]] vectors (pre-computed).
2. Bulk-insert Chunk rows with content, offsets, and embedding vectors.
3. Return the list of persisted Chunk ids.

Typical usage
─────────────
    from app.workers.db import get_sync_db
    from app.services.chunk_persistence_service import ChunkPersistenceService

    with get_sync_db() as db:
        svc = ChunkPersistenceService(db)
        chunk_ids = svc.save_chunks(document_id, text_chunks, embedding_vectors)
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.services.chunking_service import TextChunk

logger = logging.getLogger(__name__)


class ChunkPersistenceService:
    """Persist chunks and their embeddings for a single document."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save_chunks(
        self,
        document_id: uuid.UUID,
        chunks: Sequence[TextChunk],
        vectors: Sequence[list[float]],
    ) -> list[uuid.UUID]:
        """
        Bulk-insert Chunk rows and return their ids.

        Parameters
        ----------
        document_id : UUID of the parent Document row
        chunks      : ordered list of TextChunk objects (from ChunkingService)
        vectors     : parallel list of embedding vectors — must be same length
                      as ``chunks``.  Pass an empty list to skip embedding storage.

        Returns
        -------
        List of inserted Chunk UUIDs (in the same order as ``chunks``).

        Raises
        ------
        ValueError  : if len(vectors) > 0 and len(vectors) != len(chunks)
        """
        if len(vectors) > 0 and len(vectors) != len(chunks):
            raise ValueError(
                f"Mismatch: {len(chunks)} chunks but {len(vectors)} vectors."
            )

        has_vectors = len(vectors) == len(chunks) and len(vectors) > 0
        inserted_ids: list[uuid.UUID] = []

        logger.info(
            "Persisting %d chunks for document_id=%s (embeddings=%s)",
            len(chunks),
            document_id,
            has_vectors,
        )

        for idx, chunk in enumerate(chunks):
            embedding = vectors[idx] if has_vectors else None

            row = Chunk(
                document_id=document_id,
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                embedding=embedding,
            )
            self._db.add(row)
            # flush every 50 rows to avoid very large pending state
            if (idx + 1) % 50 == 0:
                self._db.flush()
                logger.debug("Flushed %d/%d chunks", idx + 1, len(chunks))

        self._db.flush()                          # flush any remaining rows

        # Collect ids after flush (primary keys are now populated)
        # Re-query is not needed because Chunk.id has a Python-side default
        for row in self._db.new:                  # session.new still holds them
            if isinstance(row, Chunk) and row.document_id == document_id:
                inserted_ids.append(row.id)

        logger.info(
            "Saved %d chunks for document_id=%s",
            len(chunks),
            document_id,
        )
        return inserted_ids
