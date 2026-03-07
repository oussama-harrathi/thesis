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
    QuestionSet,
    QuestionStatus,
    QuestionType,
)

if TYPE_CHECKING:
    from app.schemas.question import (
        QuestionListResponse,
        QuestionUpdateRequest,
        RejectRequest,
        ReplacementCandidateResponse,
    )

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
    ) -> "list[QuestionListResponse]":
        """
        Return lightweight question list rows for a course, enriched with
        blueprint context (blueprint_id, blueprint_title) when available.

        Filters are all optional and additive (AND logic).
        Questions are ordered newest-first.
        """
        from app.models.exam import ExamBlueprint, BlueprintQuestion
        from app.schemas.question import QuestionListResponse

        # Left-join Question → QuestionSet → optional ExamBlueprint
        stmt = (
            select(
                Question,
                ExamBlueprint.id.label("bp_id"),
                ExamBlueprint.title.label("bp_title"),
            )
            .join(QuestionSet, QuestionSet.id == Question.question_set_id)
            .outerjoin(ExamBlueprint, ExamBlueprint.id == QuestionSet.blueprint_id)
            .where(QuestionSet.course_id == course_id)
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
        rows = result.all()

        return [
            QuestionListResponse(
                id=q.id,
                question_set_id=q.question_set_id,
                type=q.type,
                body=q.body,
                difficulty=q.difficulty,
                bloom_level=q.bloom_level,
                status=q.status,
                created_at=q.created_at,
                blueprint_id=bp_id,
                blueprint_title=bp_title,
            )
            for q, bp_id, bp_title in rows
        ]

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

        # ── Auto-reset rejected → reviewed when content changes ───────────────
        # If the professor edits any content field on a rejected question it means
        # they have addressed the issue; surface it for re-approval.
        _content_changed = any([
            payload.body is not None,
            payload.correct_answer is not None,
            payload.explanation is not None,
            payload.mcq_options is not None,
        ])
        if _content_changed and question.status == QuestionStatus.rejected:
            question.status = QuestionStatus.reviewed
            logger.info(
                "QuestionService.update: auto-reset question=%s from rejected → reviewed",
                question.id,
            )

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
        Accepts both ``draft`` and ``reviewed`` as valid pre-approval states.
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
        Set question status to ``rejected`` and add it to the course blacklist.

        If *payload.reason* is provided it is appended to (or replaces) the
        question's explanation field for traceability.

        Raises **409** if the question is already rejected.
        """
        if question.status == QuestionStatus.rejected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Question {question.id} is already rejected.",
            )
        reason = payload.reason if payload and payload.reason else None
        question.status = QuestionStatus.rejected
        if reason:
            question.explanation = reason
        self._db.add(question)
        await self._db.flush()
        logger.info("QuestionService.reject: question=%s", question.id)

        # ── Blacklist insertion ───────────────────────────────────────
        # Resolve course_id through the parent QuestionSet.
        try:
            qs = await self._db.get(QuestionSet, question.question_set_id)
            if qs is not None:
                from app.services.diversity_service import DiversityService
                await DiversityService().add_to_blacklist(
                    self._db,
                    course_id=qs.course_id,
                    question=question,
                    reason=reason,
                )
        except Exception as exc:
            # Non-fatal: rejection must always succeed even if blacklist write fails.
            logger.warning(
                "QuestionService.reject: blacklist insertion failed for question=%s: %s",
                question.id, exc,
            )

        return question

    # ── Replacement helpers ────────────────────────────────────────────────── #

    async def list_replacement_candidates(
        self,
        course_id: uuid.UUID,
        question_type: QuestionType,
        exclude_blueprint_id: uuid.UUID,
    ) -> "list[ReplacementCandidateResponse]":
        """
        Return approved questions of *question_type* in *course_id* that are
        NOT already mapped to *exclude_blueprint_id*.

        Used to populate the replacement picker in the Professor review UI.
        """
        from app.models.exam import BlueprintQuestion, ExamBlueprint
        from app.schemas.question import ReplacementCandidateResponse

        # Sub-query: question IDs already in the target blueprint.
        already_in_bp = (
            select(BlueprintQuestion.question_id)
            .where(BlueprintQuestion.blueprint_id == exclude_blueprint_id)
            .scalar_subquery()
        )

        stmt = (
            select(
                Question,
                ExamBlueprint.id.label("bp_id"),
                ExamBlueprint.title.label("bp_title"),
            )
            .join(QuestionSet, QuestionSet.id == Question.question_set_id)
            .outerjoin(ExamBlueprint, ExamBlueprint.id == QuestionSet.blueprint_id)
            .where(QuestionSet.course_id == course_id)
            .where(Question.type == question_type)
            .where(Question.status == QuestionStatus.approved)
            .where(Question.id.not_in(already_in_bp))
            .order_by(Question.created_at.desc())
            .limit(100)
        )

        result = await self._db.execute(stmt)
        rows = result.all()

        return [
            ReplacementCandidateResponse(
                id=q.id,
                type=q.type,
                body=q.body,
                difficulty=q.difficulty,
                bloom_level=q.bloom_level,
                status=q.status,
                blueprint_id=bp_id,
                blueprint_title=bp_title,
            )
            for q, bp_id, bp_title in rows
        ]

    async def replace_in_blueprint(
        self,
        blueprint_id: uuid.UUID,
        old_question_id: uuid.UUID,
        new_question_id: uuid.UUID,
    ) -> None:
        """
        Atomically replace *old_question_id* with *new_question_id* in
        *blueprint_id*'s mapping table.

        Rules:
        - Old question must be mapped to *blueprint_id*.
        - New question must be ``approved``.
        - New question must not already be in *blueprint_id*.
        - Both questions must share the same ``type``.
        """
        from app.models.exam import BlueprintQuestion

        # Load old mapping row.
        old_mapping_stmt = (
            select(BlueprintQuestion)
            .where(BlueprintQuestion.blueprint_id == blueprint_id)
            .where(BlueprintQuestion.question_id == old_question_id)
        )
        old_result = await self._db.execute(old_mapping_stmt)
        old_mapping = old_result.scalar_one_or_none()
        if old_mapping is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Question {old_question_id} is not mapped to blueprint {blueprint_id}.",
            )

        # Load old & new questions for validation.
        old_q = await self._db.get(Question, old_question_id)
        new_q = await self._db.get(Question, new_question_id)

        if new_q is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Replacement question {new_question_id} not found.",
            )
        if new_q.status != QuestionStatus.approved:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Replacement question must be approved.",
            )
        if old_q and new_q.type != old_q.type:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Replacement question type '{new_q.type.value}' does not match "
                    f"original type '{old_q.type.value}'."
                ),
            )

        # Check replacement not already in blueprint.
        dupe_stmt = (
            select(BlueprintQuestion)
            .where(BlueprintQuestion.blueprint_id == blueprint_id)
            .where(BlueprintQuestion.question_id == new_question_id)
        )
        dupe_result = await self._db.execute(dupe_stmt)
        if dupe_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Question {new_question_id} is already in blueprint {blueprint_id}.",
            )

        # Remove old mapping, insert new one.
        await self._db.delete(old_mapping)

        new_mapping = BlueprintQuestion(
            blueprint_id=blueprint_id,
            question_id=new_question_id,
            original_blueprint_id=old_mapping.blueprint_id,
        )
        self._db.add(new_mapping)
        await self._db.flush()

        logger.info(
            "QuestionService.replace_in_blueprint: blueprint=%s old_q=%s new_q=%s",
            blueprint_id, old_question_id, new_question_id,
        )
