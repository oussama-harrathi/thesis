"""
Diversity Service

Provides cross-run diversity and rejection-memory features for the question
generation pipeline:

  1. DiversityContext  — immutable snapshot of blacklist + recent questions
                         loaded once at job start and threaded through generation.

  2. DiversityService  — helpers for:
       • computing question fingerprints (text normalisation + SHA-256)
       • computing question embeddings (SentenceTransformers, same model as chunks)
       • checking a new question against the blacklist (exact + cosine)
       • checking a new question against recent-run questions (cross-run dedup)
       • loading DiversityContext from the DB
       • loading historical chunk IDs (for retrieval penalisation)
       • inserting into question_blacklist on rejection

Blacklist threshold      : 0.90 cosine similarity (configurable)
Recent-dedup threshold   : 0.92 cosine similarity (configurable)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blacklist import QuestionBlacklist
from app.models.question import Question, QuestionSet, QuestionSource, QuestionStatus
from app.services.embedding_service import EmbeddingService
from app.utils.question_fingerprint import compute_question_fingerprint

logger = logging.getLogger(__name__)

# ── Default thresholds ────────────────────────────────────────────────────────

BLACKLIST_SIM_THRESHOLD: float = 0.90   # reject if similarity ≥ this (blacklist)
RECENT_DEDUP_SIM_THRESHOLD: float = 0.92  # warn/skip if similarity ≥ this (recent runs)


# ── DiversityContext ─────────────────────────────────────────────────────────


@dataclass
class DiversityContext:
    """
    Immutable (except for counters) snapshot of diversity state for one job.

    Built once per blueprint run by DiversityService.load_context() and passed
    through every call in the generation loop so no extra DB round-trips per
    question are needed.
    """

    # Blacklist data (from question_blacklist table for this course)
    blacklist_fingerprints: frozenset[str] = field(default_factory=frozenset)
    blacklist_embeddings: list[list[float]] = field(default_factory=list)

    # Recent-run question data (last N questions for this course, from previous runs)
    recent_fingerprints: frozenset[str] = field(default_factory=frozenset)
    recent_embeddings: list[list[float]] = field(default_factory=list)

    # Configurable thresholds
    similarity_threshold_blacklist: float = BLACKLIST_SIM_THRESHOLD
    similarity_threshold_recent: float = RECENT_DEDUP_SIM_THRESHOLD

    # Mutable job-level counters (updated by generation service)
    blacklist_avoided: int = 0
    dedup_avoided: int = 0


# ── DiversityService ─────────────────────────────────────────────────────────


class DiversityService:
    """
    Cross-run diversity and rejection-memory helpers.

    All embedding computation is synchronous (SentenceTransformers), executed
    in a thread-pool executor when called from async contexts.
    """

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self._emb = embedding_service or EmbeddingService()

    # ── Fingerprint + embedding ───────────────────────────────────────────── #

    def compute_fingerprint(self, text: str) -> str:
        return compute_question_fingerprint(text)

    def compute_embedding_sync(self, text: str) -> list[float]:
        """Synchronous embedding (for use in sync Celery task context)."""
        return self._emb.encode_one(text)

    async def compute_embedding(self, text: str) -> list[float]:
        """Async embedding (for use in FastAPI / async generation loops)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._emb.encode_one(text)
        )

    # ── Similarity helpers ────────────────────────────────────────────────── #

    @staticmethod
    def max_similarity(
        embedding: list[float],
        others: list[list[float]],
    ) -> float:
        """
        Return the maximum cosine similarity between *embedding* and any vector in
        *others*.  Assumes all vectors are already unit-normalised (they are when
        produced by SentenceTransformers with normalize_embeddings=True).

        Returns 0.0 when *others* is empty.
        """
        if not others:
            return 0.0
        q = np.array(embedding, dtype=np.float32)
        mat = np.array(others, dtype=np.float32)
        sims = mat @ q  # dot product on unit vectors = cosine similarity
        return float(sims.max())

    # ── Check helpers ─────────────────────────────────────────────────────── #

    def is_blacklisted(
        self,
        stem: str,
        embedding: list[float],
        ctx: DiversityContext,
    ) -> tuple[bool, str]:
        """
        Return (True, reason) if *stem* matches anything in the blacklist,
        (False, "") otherwise.  Checks exact fingerprint first, then cosine.
        """
        fp = compute_question_fingerprint(stem)
        if fp in ctx.blacklist_fingerprints:
            return True, f"exact fingerprint match fp={fp[:16]}"

        if ctx.blacklist_embeddings:
            sim = self.max_similarity(embedding, ctx.blacklist_embeddings)
            if sim >= ctx.similarity_threshold_blacklist:
                return True, (
                    f"embedding similarity={sim:.3f} "
                    f">= blacklist threshold={ctx.similarity_threshold_blacklist}"
                )

        return False, ""

    def is_recent_duplicate(
        self,
        stem: str,
        embedding: list[float],
        ctx: DiversityContext,
    ) -> tuple[bool, str]:
        """
        Return (True, reason) if *stem* is too similar to a question from a
        recent run, (False, "") otherwise.
        """
        fp = compute_question_fingerprint(stem)
        if fp in ctx.recent_fingerprints:
            return True, f"exact fingerprint match fp={fp[:16]}"

        if ctx.recent_embeddings:
            sim = self.max_similarity(embedding, ctx.recent_embeddings)
            if sim >= ctx.similarity_threshold_recent:
                return True, (
                    f"embedding similarity={sim:.3f} "
                    f">= recent-dedup threshold={ctx.similarity_threshold_recent}"
                )

        return False, ""

    # ── DB helpers ────────────────────────────────────────────────────────── #

    async def load_context(
        self,
        db: AsyncSession,
        *,
        course_id: uuid.UUID,
        recent_limit: int = 100,
    ) -> DiversityContext:
        """
        Load blacklist + recent-question snapshots for *course_id*.

        Designed to be called ONCE per blueprint run, before the slot loop.
        """
        # ── Blacklist ─────────────────────────────────────────────────────
        bl_rows = (
            await db.execute(
                select(QuestionBlacklist.fingerprint, QuestionBlacklist.embedding)
                .where(QuestionBlacklist.course_id == course_id)
            )
        ).all()

        blacklist_fps = frozenset(r.fingerprint for r in bl_rows)
        blacklist_embs: list[list[float]] = [
            list(r.embedding)
            for r in bl_rows
            if r.embedding is not None
        ]

        # ── Recent questions ──────────────────────────────────────────────
        recent_rows = (
            await db.execute(
                select(Question.fingerprint, Question.embedding)
                .join(QuestionSet, QuestionSet.id == Question.question_set_id)
                .where(
                    QuestionSet.course_id == course_id,
                    Question.fingerprint.isnot(None),
                )
                .order_by(Question.created_at.desc())
                .limit(recent_limit)
            )
        ).all()

        recent_fps = frozenset(r.fingerprint for r in recent_rows if r.fingerprint)
        recent_embs: list[list[float]] = [
            list(r.embedding)
            for r in recent_rows
            if r.embedding is not None
        ]

        logger.info(
            "DiversityService.load_context: course=%s "
            "blacklist=%d (with_emb=%d) recent=%d (with_emb=%d)",
            course_id,
            len(blacklist_fps), len(blacklist_embs),
            len(recent_fps), len(recent_embs),
        )

        return DiversityContext(
            blacklist_fingerprints=blacklist_fps,
            blacklist_embeddings=blacklist_embs,
            recent_fingerprints=recent_fps,
            recent_embeddings=recent_embs,
        )

    async def load_recent_chunk_ids(
        self,
        db: AsyncSession,
        *,
        course_id: uuid.UUID,
        limit: int = 200,
    ) -> set[uuid.UUID]:
        """
        Return the set of chunk IDs used by the most recent *limit* question-source
        records for this course.

        These are passed into retrieval as *penalize_chunk_ids* so the next run
        preferentially pulls fresh material.
        """
        rows = (
            await db.execute(
                select(QuestionSource.chunk_id)
                .join(Question, Question.id == QuestionSource.question_id)
                .join(QuestionSet, QuestionSet.id == Question.question_set_id)
                .where(
                    QuestionSet.course_id == course_id,
                    QuestionSource.chunk_id.isnot(None),
                )
                .order_by(Question.created_at.desc())
                .limit(limit)
            )
        ).all()

        ids = {r.chunk_id for r in rows if r.chunk_id is not None}
        logger.info(
            "DiversityService.load_recent_chunk_ids: course=%s found=%d historical chunk(s)",
            course_id, len(ids),
        )
        return ids

    async def add_to_blacklist(
        self,
        db: AsyncSession,
        *,
        course_id: uuid.UUID,
        question: "Question",
        reason: str | None = None,
    ) -> QuestionBlacklist:
        """
        Insert a rejected question into the blacklist for *course_id*.

        If *question.embedding* is already set it is copied directly.
        Otherwise the embedding is computed inline.
        """
        fp = compute_question_fingerprint(question.body)

        # Use pre-computed embedding if available, else compute now.
        if question.embedding is not None:
            emb: list[float] | None = list(question.embedding)
        else:
            try:
                emb = await self.compute_embedding(question.body)
            except Exception as exc:
                logger.warning(
                    "add_to_blacklist: could not compute embedding for question=%s: %s",
                    question.id, exc,
                )
                emb = None

        entry = QuestionBlacklist(
            id=uuid.uuid4(),
            course_id=course_id,
            fingerprint=fp,
            embedding=emb,
            original_question_id=question.id,
            reason=reason,
        )
        db.add(entry)
        await db.flush()
        logger.info(
            "DiversityService.add_to_blacklist: question=%s fp=%s course=%s",
            question.id, fp[:16], course_id,
        )
        return entry
