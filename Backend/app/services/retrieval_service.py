"""
Retrieval Service

Provides semantic chunk retrieval from pgvector for use in question generation.
Two retrieval strategies are supported:
  1. Query-based: embed a free-text query and find the closest chunks by cosine similarity.
  2. Topic-based:  return chunks that were mapped to a topic during extraction, ordered
     by relevance score stored in TopicChunkMap.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.topic import Topic, TopicChunkMap
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A chunk returned by the retrieval service, with its relevance score."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    chunk_index: int
    score: float  # cosine similarity (0-1, higher = more relevant)


class RetrievalService:
    """Semantic and topic-based chunk retrieval using pgvector."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self._embedding_service = embedding_service or EmbeddingService()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def retrieve_by_query(
        self,
        db: AsyncSession,
        query: str,
        *,
        course_id: uuid.UUID | None = None,
        document_id: uuid.UUID | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        """
        Embed *query* and return the top-k most similar chunks from the database.

        Parameters
        ----------
        db:          Async SQLAlchemy session.
        query:       Free-text query to embed and search with.
        course_id:   Optional — restrict search to chunks belonging to this course.
        document_id: Optional — restrict search to chunks from a single document.
        top_k:       Number of chunks to return.
        min_score:   Minimum cosine similarity threshold (0–1).
        """
        query_embedding: list[float] = await self._embed_query(query)

        stmt = self._build_similarity_query(
            query_embedding=query_embedding,
            course_id=course_id,
            document_id=document_id,
            top_k=top_k,
        )

        result = await db.execute(stmt)
        rows = result.all()

        chunks: list[RetrievedChunk] = []
        for row in rows:
            chunk: Chunk = row[0]
            cosine_distance: float = float(row[1])
            score = max(0.0, 1.0 - cosine_distance)
            if score >= min_score:
                chunks.append(
                    RetrievedChunk(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        content=chunk.content,
                        chunk_index=chunk.chunk_index,
                        score=score,
                    )
                )

        logger.debug(
            "retrieve_by_query: query=%r course=%s doc=%s top_k=%d returned=%d",
            query[:60],
            course_id,
            document_id,
            top_k,
            len(chunks),
        )
        return chunks

    async def retrieve_by_topic(
        self,
        db: AsyncSession,
        topic_id: uuid.UUID,
        *,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        """
        Return chunks that were explicitly mapped to *topic_id* during topic extraction,
        ordered by their stored relevance score (descending).
        """
        stmt = (
            select(Chunk, TopicChunkMap.relevance_score)
            .join(TopicChunkMap, TopicChunkMap.chunk_id == Chunk.id)
            .where(TopicChunkMap.topic_id == topic_id)
            .order_by(TopicChunkMap.relevance_score.desc().nullslast())
            .limit(top_k)
        )

        result = await db.execute(stmt)
        rows = result.all()

        chunks: list[RetrievedChunk] = [
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                score=float(score) if score is not None else 0.0,
            )
            for chunk, score in rows
            if (score is None or float(score) >= min_score)
        ]

        logger.debug(
            "retrieve_by_topic: topic=%s top_k=%d returned=%d",
            topic_id,
            top_k,
            len(chunks),
        )
        return chunks

    async def retrieve_for_generation(
        self,
        db: AsyncSession,
        *,
        query: str | None = None,
        topic_id: uuid.UUID | None = None,
        course_id: uuid.UUID | None = None,
        top_k: int = 6,
        min_score: float = 0.1,
    ) -> list[RetrievedChunk]:
        """
        Combined retrieval for question generation.

        If *topic_id* is provided, first retrieves topic-mapped chunks and
        supplements with query-based retrieval when needed.  If only *query*
        is given, falls back to pure query-based retrieval.

        At least one of *query* or *topic_id* must be supplied.
        """
        if topic_id is None and query is None:
            raise ValueError("At least one of 'query' or 'topic_id' must be provided.")

        seen_ids: set[uuid.UUID] = set()
        combined: list[RetrievedChunk] = []

        # 1. Topic-based retrieval (high precision)
        if topic_id is not None:
            topic_chunks = await self.retrieve_by_topic(
                db, topic_id, top_k=top_k, min_score=min_score
            )
            for c in topic_chunks:
                seen_ids.add(c.chunk_id)
                combined.append(c)

        # 2. Query-based retrieval to fill remaining slots
        remaining = top_k - len(combined)
        if remaining > 0 and query:
            query_chunks = await self.retrieve_by_query(
                db,
                query,
                course_id=course_id,
                top_k=remaining + len(seen_ids),  # over-fetch to account for de-dup
                min_score=min_score,
            )
            for c in query_chunks:
                if c.chunk_id not in seen_ids and len(combined) < top_k:
                    seen_ids.add(c.chunk_id)
                    combined.append(c)

        # Sort final list by score desc
        combined.sort(key=lambda c: c.score, reverse=True)
        return combined[:top_k]

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    async def _embed_query(self, query: str) -> list[float]:
        """Embed a query string using the shared EmbeddingService (runs in thread pool)."""
        loop = asyncio.get_event_loop()
        embeddings: list[list[float]] = await loop.run_in_executor(
            None, lambda: self._embedding_service.encode([query])
        )
        return embeddings[0]

    def _build_similarity_query(
        self,
        query_embedding: list[float],
        *,
        course_id: uuid.UUID | None,
        document_id: uuid.UUID | None,
        top_k: int,
    ):
        """
        Build a SQLAlchemy SELECT that returns (Chunk, cosine_distance) pairs,
        ordered ascending by cosine distance (closest first).

        pgvector cosine distance operator: <=>
        We cast the query vector as a literal string for compatibility.
        """
        # pgvector cosine distance: Chunk.embedding <=> '[x,x,...x]'
        cosine_distance = Chunk.embedding.cosine_distance(query_embedding)  # type: ignore[attr-defined]

        stmt = select(Chunk, cosine_distance.label("cosine_distance")).where(
            Chunk.embedding.isnot(None)  # type: ignore[attr-defined]
        )

        if document_id is not None:
            stmt = stmt.where(Chunk.document_id == document_id)

        if course_id is not None:
            # Join to document to filter by course
            from app.models.document import Document

            stmt = stmt.join(Document, Document.id == Chunk.document_id).where(
                Document.course_id == course_id
            )

        stmt = stmt.order_by(cosine_distance).limit(top_k)
        return stmt
