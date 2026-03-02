"""
Practice Service — Student Practice Workflow

Orchestrates on-demand question generation for student practice sets.

Generation flow
---------------
1. Create a QuestionSet (mode=STUDENT) and flush to obtain its PK.
2. Distribute the requested *count* evenly across requested question_types.
3. If topic_ids are supplied, further distribute each type's slice across
   the matched topics (round-robin / ceiling division).
4. Delegate to QuestionGenerationService.generate_mcq() /
   .generate_true_false() for each (type, topic) slice.
5. Reload the QuestionSet with full nested relations (options + sources)
   so the route can serialise a complete response.
6. Session commit is left to the FastAPI ``get_db`` dependency.

Supported types (MVP Phase 10)
-------------------------------
  - QuestionType.mcq        → generate_mcq()
  - QuestionType.true_false → generate_true_false()

Short-answer and Essay generators are not yet implemented (planned Phase 7
continuation).  Requests for those types are silently skipped with a warning
log; the practice set is still returned with whatever was generated.
"""

from __future__ import annotations

import logging
import math
import random as _rnd
import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import (
    Difficulty,
    McqOption,
    Question,
    QuestionSet,
    QuestionSetMode,
    QuestionSource,
    QuestionType,
)
from app.models.topic import Topic
from app.schemas.practice import CreatePracticeSetRequest
from app.services.question_generation_service import QuestionGenerationService

logger = logging.getLogger(__name__)

# Question types with implemented generators in this MVP phase.
_SUPPORTED_TYPES: frozenset[QuestionType] = frozenset({
    QuestionType.mcq,
    QuestionType.true_false,
})


class PracticeService:
    """
    Creates and retrieves student practice sets.

    Inject a custom ``QuestionGenerationService`` for testing with the
    MockProvider; production code uses the default factory.
    """

    def __init__(
        self,
        generation_service: QuestionGenerationService | None = None,
    ) -> None:
        self._gen = generation_service or QuestionGenerationService()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def create_practice_set(
        self,
        db: AsyncSession,
        payload: CreatePracticeSetRequest,
    ) -> QuestionSet:
        """
        Generate a student practice set from course material and return it.

        Session is NOT committed here — the FastAPI ``get_db`` dependency
        handles commit/rollback after the route handler returns.
        """
        # When difficulty is None (user left it unset / "random"), we vary
        # difficulty randomly per slice instead of always defaulting to medium.
        _use_random_difficulty = payload.difficulty is None
        _RANDOM_DIFFICULTIES = [Difficulty.easy, Difficulty.medium, Difficulty.hard]

        def _pick_difficulty() -> str:
            if _use_random_difficulty:
                return _rnd.choice(_RANDOM_DIFFICULTIES).value
            return payload.difficulty.value  # type: ignore[union-attr]

        # ── Warn about and filter unsupported question types ──────────
        unsupported = [t for t in payload.question_types if t not in _SUPPORTED_TYPES]
        if unsupported:
            logger.warning(
                "create_practice_set: question types %s are not yet implemented "
                "and will be skipped",
                [t.value for t in unsupported],
            )

        active_types = [t for t in payload.question_types if t in _SUPPORTED_TYPES]

        # ── Resolve topic metadata ────────────────────────────────────
        # user_topics: explicitly chosen by the student (may be empty)
        # auto_topics: full shuffled list when no topic_ids supplied;
        #              sliced to per_type inside the generation loop so that
        #              total slices never exceed the requested count.
        user_topics: list[Topic] = []
        auto_topics: list[Topic] = []
        if payload.topic_ids:
            result = await db.execute(
                select(Topic).where(
                    Topic.id.in_(payload.topic_ids),
                    Topic.course_id == payload.course_id,
                )
            )
            user_topics = list(result.scalars().all())
            if not user_topics:
                logger.warning(
                    "create_practice_set: topic_ids provided but none matched "
                    "course=%s — falling back to full-course retrieval",
                    payload.course_id,
                )
        else:
            # No topics selected → load all, shuffle for variety.
            # We deliberately do NOT cap here; the cap is applied per-type
            # inside the loop using per_type, so the total number of
            # generation slices always equals count (not count × n_types).
            result = await db.execute(
                select(Topic).where(Topic.course_id == payload.course_id)
            )
            auto_topics = list(result.scalars().all())
            _rnd.shuffle(auto_topics)
            if auto_topics:
                logger.info(
                    "create_practice_set: auto-topic pool has %d topic(s) for course=%s",
                    len(auto_topics), payload.course_id,
                )

        # ── Create the QuestionSet row ─────────────────────────────────
        type_labels = ", ".join(t.value for t in (active_types or payload.question_types))
        title = payload.title or f"Practice Set ({type_labels})"

        question_set = QuestionSet(
            id=uuid.uuid4(),
            course_id=payload.course_id,
            mode=QuestionSetMode.student,
            title=title,
        )
        db.add(question_set)
        await db.flush()  # obtain PK before inserting child rows

        # ── Generate and persist questions ────────────────────────────
        if active_types:
            # Ceiling-divide count across active types so total ≥ requested count.
            per_type = max(1, math.ceil(payload.count / len(active_types)))

            for qtype in active_types:
                if user_topics:
                    # User picked specific topics → distribute per_type across them.
                    per_topic = max(1, math.ceil(per_type / len(user_topics)))
                    for topic in user_topics:
                        await self._generate_slice(
                            db,
                            qtype=qtype,
                            question_set_id=question_set.id,
                            course_id=payload.course_id,
                            topic_id=topic.id,
                            topic_name=topic.name,
                            difficulty=_pick_difficulty(),
                            count=per_topic,
                        )
                elif auto_topics:
                    # Auto-topic mode: pick exactly per_type topics from the
                    # shuffled pool so we never generate more slices than
                    # requested.  Each slice produces 1 question.
                    type_topics = auto_topics[:per_type]
                    per_topic = max(1, math.ceil(per_type / len(type_topics)))
                    for topic in type_topics:
                        await self._generate_slice(
                            db,
                            qtype=qtype,
                            question_set_id=question_set.id,
                            course_id=payload.course_id,
                            topic_id=topic.id,
                            topic_name=topic.name,
                            difficulty=_pick_difficulty(),
                            count=per_topic,
                        )
                else:
                    # No topics at all — use full course material.
                    await self._generate_slice(
                        db,
                        qtype=qtype,
                        question_set_id=question_set.id,
                        course_id=payload.course_id,
                        topic_id=None,
                        topic_name="General",
                        difficulty=_pick_difficulty(),
                        count=per_type,
                    )
        else:
            logger.warning(
                "create_practice_set: no supported types in request — "
                "returning empty practice set for course=%s",
                payload.course_id,
            )

        # ── Reload with full nested relations for serialisation ────────
        return await self._load_with_relations(db, question_set.id)

    async def get_practice_set(
        self,
        db: AsyncSession,
        question_set_id: uuid.UUID,
    ) -> QuestionSet | None:
        """
        Load a student practice set by ID with all question details.

        Returns ``None`` when not found or when the set is not student-mode.
        """
        result = await db.execute(
            select(QuestionSet)
            .where(
                QuestionSet.id == question_set_id,
                QuestionSet.mode == QuestionSetMode.student,
            )
            .options(
                selectinload(QuestionSet.questions).selectinload(Question.mcq_options),
                selectinload(QuestionSet.questions).selectinload(Question.sources),
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _generate_slice(
        self,
        db: AsyncSession,
        *,
        qtype: QuestionType,
        question_set_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_id: uuid.UUID | None,
        topic_name: str,
        difficulty: str,
        count: int,
    ) -> list[Question]:
        """
        Delegate one generation slice to the appropriate generator.

        Returns the list of persisted Question objects (may be empty if
        context is insufficient or the generator is not yet implemented).
        """
        if qtype == QuestionType.mcq:
            return await self._gen.generate_mcq(
                db,
                question_set_id=question_set_id,
                course_id=course_id,
                topic_id=topic_id,
                topic_name=topic_name,
                difficulty=difficulty,
                count=count,
            )
        elif qtype == QuestionType.true_false:
            return await self._gen.generate_true_false(
                db,
                question_set_id=question_set_id,
                course_id=course_id,
                topic_id=topic_id,
                topic_name=topic_name,
                difficulty=difficulty,
                count=count,
            )
        else:
            logger.warning(
                "_generate_slice: type %r not yet implemented — skipping slice "
                "(question_set=%s)",
                qtype.value,
                question_set_id,
            )
            return []

    async def _load_with_relations(
        self,
        db: AsyncSession,
        question_set_id: uuid.UUID,
    ) -> QuestionSet:
        """
        Reload the QuestionSet eagerly loading questions → mcq_options + sources.

        Uses selectinload to avoid N+1 queries.
        """
        result = await db.execute(
            select(QuestionSet)
            .where(QuestionSet.id == question_set_id)
            .options(
                selectinload(QuestionSet.questions).selectinload(Question.mcq_options),
                selectinload(QuestionSet.questions).selectinload(Question.sources),
            )
        )
        return result.scalar_one()
