"""
Question Service

Handles read and review operations on Question rows.
Write operations (generation + persistence) live in QuestionGenerationService.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.question import (
    Difficulty,
    McqOption,
    Question,
    QuestionStatus,
    QuestionType,
)

if TYPE_CHECKING:
    from app.schemas.question import QuestionUpdateRequest, RejectRequest

logger = logging.getLogger(__name__)


class QuestionService:
    """Read-side + review-side service for Question resources."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Read ──────────────────────────────────────────────────────────────── #

    async def list_by_course(
        self,
        course_id: uuid.UUID,
        *,
        question_type: QuestionType | None = None,
        difficulty: Difficulty | None = None,
        status: QuestionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Question]:
        """
        Return questions belonging to a course, with options and sources eager-loaded.

        Filters are all optional and additive (AND logic).
        Questions are ordered newest-first.
        """
        from app.models.question import QuestionSet  # local import to avoid circulars

        stmt = (
            select(Question)
            .join(QuestionSet, QuestionSet.id == Question.question_set_id)
            .where(QuestionSet.course_id == course_id)
            .options(
                selectinload(Question.mcq_options),
                selectinload(Question.sources),
            )
            .order_by(Question.created_at.desc())
        )

        if question_type is not None:
            stmt = stmt.where(Question.type == question_type)
        if difficulty is not None:
            stmt = stmt.where(Question.difficulty == difficulty)
        if status is not None:
            stmt = stmt.where(Question.status == status)

        stmt = stmt.limit(limit).offset(offset)

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, question_id: uuid.UUID) -> Question | None:
        """Return a single question with options and sources, or None."""
        stmt = (
            select(Question)
            .where(Question.id == question_id)
            .options(
                selectinload(Question.mcq_options),
                selectinload(Question.sources),
            )
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    # ── Write / review ─────────────────────────────────────────────────────── #

    async def update(
        self,
        question: Question,
        payload: "QuestionUpdateRequest",
    ) -> Question:
        """
        Apply a partial update to *question*.

        Only non-None fields in *payload* are changed.  For MCQ questions supplying
        ``mcq_options`` triggers option-level editing with safety validation:

        MCQ option editing rules
        ─────────────────────────
        Each ``MCQOptionUpdate`` entry matches an existing option by ``id`` or ``label``.
        Unknown identifiers raise **422**.
        After all per-option changes are applied the service verifies that exactly
        one option carries ``is_correct=True``; violating this constraint raises **422**.

        Parameters
        ----------
        question : Already-loaded ORM Question (options must be accessible).
        payload  : Validated ``QuestionUpdateRequest``.

        Returns
        -------
        The mutated (not yet committed) Question object.
        """
        if payload.body is not None:
            question.body = payload.body

        # correct_answer is only meaningful for non-MCQ types; accept it for all
        # since the professor may want to override the auto-extracted answer.
        if payload.correct_answer is not None:
            question.correct_answer = payload.correct_answer

        if payload.explanation is not None:
            question.explanation = payload.explanation

        if payload.difficulty is not None:
            question.difficulty = payload.difficulty

        if payload.bloom_level is not None:
            question.bloom_level = payload.bloom_level

        # ── MCQ option editing ─────────────────────────────────────────────
        if payload.mcq_options is not None:
            if question.type != QuestionType.mcq:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "mcq_options can only be edited on MCQ questions "
                        f"(this question is type '{question.type.value}')."
                    ),
                )

            # Build a lookup of existing options by id and label.
            by_id: dict[uuid.UUID, McqOption] = {o.id: o for o in question.mcq_options}
            by_label: dict[str, McqOption] = {o.label: o for o in question.mcq_options}

            for opt_update in payload.mcq_options:
                # Resolve target option.
                target: McqOption | None = None
                if opt_update.id is not None:
                    target = by_id.get(opt_update.id)
                    if target is None:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"MCQ option id={opt_update.id} not found on this question.",
                        )
                else:
                    assert opt_update.label is not None  # guaranteed by MCQOptionUpdate validator
                    target = by_label.get(opt_update.label)
                    if target is None:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"MCQ option label='{opt_update.label}' not found on this question.",
                        )

                if opt_update.text is not None:
                    target.text = opt_update.text

                if opt_update.is_correct is not None:
                    if opt_update.is_correct:
                        # Clear all others first, then mark this one.
                        for o in question.mcq_options:
                            o.is_correct = False
                    target.is_correct = opt_update.is_correct
                    self._db.add(target)

            # Verify invariant: exactly one correct option.
            correct_count = sum(1 for o in question.mcq_options if o.is_correct)
            if correct_count != 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"After applying changes, {correct_count} option(s) are marked correct. "
                        "Exactly one MCQ option must be correct."
                    ),
                )

        self._db.add(question)
        await self._db.flush()
        logger.info("QuestionService.update: question=%s", question.id)
        return question

    async def approve(self, question: Question) -> Question:
        """
        Set question status to ``approved``.

        Raises **409** if the question is already approved.
        """
        if question.status == QuestionStatus.approved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Question {question.id} is already approved.",
            )
        question.status = QuestionStatus.approved
        self._db.add(question)
        await self._db.flush()
        logger.info("QuestionService.approve: question=%s", question.id)
        return question

    async def reject(
        self,
        question: Question,
        payload: "RejectRequest | None" = None,
    ) -> Question:
        """
        Set question status to ``rejected``.

        If *payload.reason* is provided it is appended to (or replaces) the
        question's explanation field for traceability.

        Raises **409** if the question is already rejected.
        """
        if question.status == QuestionStatus.rejected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Question {question.id} is already rejected.",
            )
        question.status = QuestionStatus.rejected
        if payload and payload.reason:
            question.explanation = payload.reason
        self._db.add(question)
        await self._db.flush()
        logger.info("QuestionService.reject: question=%s", question.id)
        return question
