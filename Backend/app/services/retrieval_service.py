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
from app.models.document import Document
from app.models.topic import Topic, TopicChunkMap
from app.services.embedding_service import EmbeddingService
from app.utils.chunk_filter import is_excluded_for_generation

logger = logging.getLogger(__name__)

# Minimum number of retrieved chunks required before we call the LLM.
# Below this we attempt a broader (course-wide) fallback search first.
MIN_CONTEXT_CHUNKS = 3


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
        course_id: uuid.UUID | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        """
        Return chunks that were explicitly mapped to *topic_id* during topic extraction,
        ordered by their stored relevance score (descending).

        If *course_id* is provided the result is scoped to chunks belonging to
        documents of that course (prevents cross-course contamination).
        """
        stmt = (
            select(Chunk, TopicChunkMap.relevance_score)
            .join(TopicChunkMap, TopicChunkMap.chunk_id == Chunk.id)
            .where(TopicChunkMap.topic_id == topic_id)
        )

        if course_id is not None:
            stmt = stmt.join(Document, Document.id == Chunk.document_id).where(
                Document.course_id == course_id
            )

        stmt = stmt.order_by(TopicChunkMap.relevance_score.desc().nullslast()).limit(top_k)

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
            "retrieve_by_topic: topic=%s course=%s top_k=%d returned=%d",
            topic_id,
            course_id,
            top_k,
            len(chunks),
        )
        return chunks

    async def retrieve_for_slot(
        self,
        db: AsyncSession,
        *,
        course_id: uuid.UUID,
        topic_id: uuid.UUID | None = None,
        topic_name: str = "General",
        question_type_label: str = "",
        top_k: int = 6,
        exclude_chunk_ids: set[uuid.UUID] | None = None,
        penalize_chunk_ids: set[uuid.UUID] | None = None,
        generation_seed: int | None = None,
    ) -> list[RetrievedChunk]:
        """
        Slot-driven retrieval: builds a richer query seed from *topic_name* and
        *question_type_label* so different slot types pull different chunks even
        for the same topic.

        Parameters
        ----------
        course_id          : Scope retrieval to this course.
        topic_id           : Optional topic for high-precision topic-mapped retrieval.
        topic_name         : Human-readable topic label (from blueprint slot).
        question_type_label: Short string describing the question type intent,
                             e.g. "definition concept example explanation" for MCQ.
        top_k              : How many chunks to return.
        exclude_chunk_ids  : Chunk IDs already used earlier in this job — will
                             be filtered out to promote diversity.
        penalize_chunk_ids : Chunk IDs used in PREVIOUS runs — ranked last when
                             enough fresh candidates are available.
        generation_seed    : Integer seed for reproducible but varied tie-breaking.
        """
        query_seed = f"{topic_name} {question_type_label}".strip()
        return await self.retrieve_for_generation(
            db,
            query=query_seed,
            topic_id=topic_id,
            course_id=course_id,
            top_k=top_k,
            min_score=0.1,
            exclude_noncontent=True,
            exclude_chunk_ids=exclude_chunk_ids,
            penalize_chunk_ids=penalize_chunk_ids,
            generation_seed=generation_seed,
        )

    async def retrieve_for_generation(
        self,
        db: AsyncSession,
        *,
        query: str | None = None,
        topic_id: uuid.UUID | None = None,
        course_id: uuid.UUID | None = None,
        top_k: int = 6,
        min_score: float = 0.1,
        exclude_noncontent: bool = True,
        exclude_chunk_ids: set[uuid.UUID] | None = None,
        penalize_chunk_ids: set[uuid.UUID] | None = None,
        generation_seed: int | None = None,
    ) -> list[RetrievedChunk]:
        """
        Combined retrieval for question generation, with automatic fallback broadening.

        Strategy
        ────────
        1. If *topic_id* is set, retrieve topic-mapped chunks scoped to *course_id*.
        2. Supplement with query-based retrieval (also course-scoped) up to *top_k*.
        3. Filter out non-content boilerplate (references, problem lists) when
           *exclude_noncontent* is True.
        4. Filter out chunk IDs in *exclude_chunk_ids* to promote diversity across
           a multi-slot generation job.
        5. Penalise (rank last) chunk IDs in *penalize_chunk_ids* that belong to
           previous runs; if enough fresh candidates exist they are excluded.
        6. Seeded tie-break sort: when *generation_seed* is set, chunks within
           the same 0.05 score band are shuffled with a deterministic RNG so
           repeated runs pull different representatives of the same topic.
        7. If the combined result after filtering has fewer than MIN_CONTEXT_CHUNKS,
           broaden: drop topic filter, 2× top_k, lower min_score to 0.05.
        5. If the combined result after filtering has fewer than MIN_CONTEXT_CHUNKS,
           broaden: drop topic filter, 2× top_k, lower min_score to 0.05.
        6. Still below MIN_CONTEXT_CHUNKS after broadening → return empty list
           (caller must NOT call the LLM — it would hallucinate).

        At least one of *query* or *topic_id* must be supplied.
        """
        if topic_id is None and query is None:
            raise ValueError("At least one of 'query' or 'topic_id' must be provided.")

        # Fetch extra candidates upfront to compensate for post-retrieval filtering.
        # We request up to 3× requested top_k so we have room after removing
        # boilerplate chunks and already-used chunk IDs.
        fetch_k = top_k * 3

        seen_ids: set[uuid.UUID] = set()
        combined: list[RetrievedChunk] = []

        # 1. Topic-based retrieval (high precision, course-scoped).
        if topic_id is not None:
            topic_chunks = await self.retrieve_by_topic(
                db, topic_id, course_id=course_id, top_k=fetch_k, min_score=min_score
            )
            for c in topic_chunks:
                seen_ids.add(c.chunk_id)
                combined.append(c)

        # 2. Query-based retrieval to fill remaining slots (course-scoped).
        remaining = fetch_k - len(combined)
        if remaining > 0 and query:
            query_chunks = await self.retrieve_by_query(
                db,
                query,
                course_id=course_id,
                top_k=remaining + len(seen_ids),
                min_score=min_score,
            )
            for c in query_chunks:
                if c.chunk_id not in seen_ids and len(combined) < fetch_k:
                    seen_ids.add(c.chunk_id)
                    combined.append(c)

        # 3a. Filter boilerplate / non-instructional chunks.
        if exclude_noncontent:
            before = len(combined)
            combined = [c for c in combined if not is_excluded_for_generation(c.content)]
            excluded_count = before - len(combined)
            if excluded_count:
                logger.info(
                    "retrieve_for_generation: filtered out %d non-content chunk(s) "
                    "(boilerplate/references) for course=%s",
                    excluded_count, course_id,
                )

        # 3b. Filter already-used chunk IDs to promote diversity across slots.
        if exclude_chunk_ids:
            before = len(combined)
            combined = [c for c in combined if c.chunk_id not in exclude_chunk_ids]
            filtered_used = before - len(combined)
            if filtered_used:
                logger.debug(
                    "retrieve_for_generation: filtered out %d already-used chunk(s) "
                    "for course=%s",
                    filtered_used, course_id,
                )

        # 4. Fallback: broaden if still too few chunks after filtering.
        if len(combined) < MIN_CONTEXT_CHUNKS and course_id is not None and query:
            logger.info(
                "retrieve_for_generation: only %d chunks after filtering; "
                "broadening to course-wide retrieval (course=%s, query=%r)",
                len(combined), course_id, (query or "")[:60],
            )
            broad_top_k = fetch_k * 2
            broad_chunks = await self.retrieve_by_query(
                db,
                query,
                course_id=course_id,
                top_k=broad_top_k,
                min_score=0.05,
            )
            already_used = exclude_chunk_ids or set()
            for c in broad_chunks:
                boilerplate = exclude_noncontent and is_excluded_for_generation(c.content)
                if (
                    c.chunk_id not in seen_ids
                    and c.chunk_id not in already_used
                    and not boilerplate
                    and len(combined) < broad_top_k
                ):
                    seen_ids.add(c.chunk_id)
                    combined.append(c)
            logger.info(
                "retrieve_for_generation: after broadening: %d chunk(s) for course=%s",
                len(combined), course_id,
            )

        # 4. Final check — do not return results that would force hallucination.
        if len(combined) < MIN_CONTEXT_CHUNKS:
            logger.warning(
                "retrieve_for_generation: insufficient context even after broadening "
                "(%d < %d) for course=%s — returning empty to block LLM call",
                len(combined), MIN_CONTEXT_CHUNKS, course_id,
            )
            return []

        # 5. Seeded tie-break sort: within the same 0.05 score band, shuffle
        #    deterministically so repeated runs pull different chunk representatives.
        if generation_seed is not None:
            import random as _rnd
            rng = _rnd.Random(generation_seed)
            # Score band = floor(score * 20) / 20  (0.05 precision)
            combined.sort(
                key=lambda c: (round(c.score * 20) / 20, rng.random()), reverse=True
            )
        else:
            combined.sort(key=lambda c: c.score, reverse=True)

        # 6. Penalise historical chunk IDs: prefer chunks not used in previous
        #    runs; fill remainder from penalised pool only when necessary.
        if penalize_chunk_ids:
            preferred = [c for c in combined if c.chunk_id not in penalize_chunk_ids]
            penalised = [c for c in combined if c.chunk_id in penalize_chunk_ids]
            if len(preferred) >= top_k:
                # Enough fresh material — drop penalised entirely this slot.
                combined = preferred
                logger.debug(
                    "retrieve_for_generation: penalised %d historical chunk(s) "
                    "(enough fresh preferred=%d available)",
                    len(penalised), len(preferred),
                )
            else:
                # Not enough fresh; append penalised as fallback.
                combined = preferred + penalised
                logger.debug(
                    "retrieve_for_generation: penalised %d chunk(s) ranked last "
                    "(only %d fresh preferred available, need %d)",
                    len(penalised), len(preferred), top_k,
                )

        return combined[:top_k]

    # ------------------------------------------------------------------ #
    # Diversity stats helper                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def count_excluded(chunks_raw: list[RetrievedChunk]) -> int:
        """Return the number of chunks in *chunks_raw* that would be filtered out."""
        return sum(1 for c in chunks_raw if is_excluded_for_generation(c.content))

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
