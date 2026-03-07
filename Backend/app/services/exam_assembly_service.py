"""
Exam Assembly Service

Handles all business logic for:
  - Assembling an exam from approved questions linked to a blueprint
  - CRUD for exam questions (add, remove, reorder, update points)
  - Fetching exams with eager-loaded question slots

Layer: service — never called directly from workers.
All public methods accept an open AsyncSession; the caller commits.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exam import Exam, ExamBlueprint, ExamQuestion
from app.models.question import Question, QuestionSet, QuestionStatus

if TYPE_CHECKING:
    from app.schemas.exam import (
        AssembleExamRequest,
        AddExamQuestionRequest,
        ReorderExamQuestionsRequest,
    )

logger = logging.getLogger(__name__)


class ExamAssemblyService:
    """Service for assembling and managing exams."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def get_blueprint_or_none(self, blueprint_id: uuid.UUID) -> ExamBlueprint | None:
        result = await self.db.execute(
            select(ExamBlueprint).where(ExamBlueprint.id == blueprint_id)
        )
        return result.scalar_one_or_none()

    async def get_exam_or_none(self, exam_id: uuid.UUID) -> Exam | None:
        """Load exam with eager-loaded exam_questions → question → mcq_options + sources."""
        result = await self.db.execute(
            select(Exam)
            .where(Exam.id == exam_id)
            .options(
                selectinload(Exam.exam_questions).selectinload(ExamQuestion.question).selectinload(
                    Question.mcq_options
                ),
                selectinload(Exam.exam_questions).selectinload(ExamQuestion.question).selectinload(
                    Question.sources
                ),
            )
        )
        return result.scalar_one_or_none()

    async def get_exam_question_or_none(
        self, exam_question_id: uuid.UUID
    ) -> ExamQuestion | None:
        result = await self.db.execute(
            select(ExamQuestion).where(ExamQuestion.id == exam_question_id)
        )
        return result.scalar_one_or_none()

    # ── Assembly ──────────────────────────────────────────────────────────────

    async def assemble(
        self,
        blueprint: ExamBlueprint,
        payload: "AssembleExamRequest",
    ) -> Exam:
        """
        Assemble an exam from approved questions.

        If payload.question_set_id is provided, only questions from that set
        are included.  Otherwise, all approved questions in the course are used.

        Questions are ordered by: type, then difficulty (easy → medium → hard),
        then creation time.
        """
        db = self.db

        # ── Collect approved questions ────────────────────────────
        if payload.question_set_id:
            stmt = (
                select(Question)
                .join(QuestionSet)
                .where(
                    QuestionSet.id == payload.question_set_id,
                    QuestionSet.course_id == blueprint.course_id,
                    Question.status == QuestionStatus.approved,
                )
                .order_by(Question.type, Question.created_at)
            )
        else:
            stmt = (
                select(Question)
                .join(QuestionSet)
                .where(
                    QuestionSet.course_id == blueprint.course_id,
                    Question.status == QuestionStatus.approved,
                )
                .order_by(Question.type, Question.created_at)
            )

        rows = await db.execute(stmt)
        questions: list[Question] = list(rows.scalars().all())

        logger.info(
            "ExamAssemblyService.assemble: blueprint=%s collected %d approved questions",
            blueprint.id,
            len(questions),
        )

        if not questions:
            raise ValueError(
                "No approved questions found for this blueprint. "
                "Please go to Question Review and approve some questions first."
            )

        # ── Calculate total_points ────────────────────────────────
        pts = payload.default_points_per_question
        total_points: int | None = None
        if pts is not None:
            total_points = int(pts * len(questions))

        # ── Create Exam row ───────────────────────────────────────
        exam = Exam(
            id=uuid.uuid4(),
            blueprint_id=blueprint.id,
            course_id=blueprint.course_id,
            title=payload.title,
            description=payload.description,
            total_points=total_points,
        )
        db.add(exam)
        await db.flush()  # get exam.id

        # ── Create ExamQuestion rows ──────────────────────────────
        for pos, question in enumerate(questions, start=1):
            eq = ExamQuestion(
                id=uuid.uuid4(),
                exam_id=exam.id,
                question_id=question.id,
                position=pos,
                points=pts,
            )
            db.add(eq)

        await db.flush()
        await db.refresh(exam)

        logger.info(
            "ExamAssemblyService.assemble: exam=%s created with %d questions",
            exam.id,
            len(questions),
        )
        return exam

    # ── List exams for a blueprint ────────────────────────────────────────────

    async def list_by_blueprint(self, blueprint_id: uuid.UUID) -> list[Exam]:
        result = await self.db.execute(
            select(Exam)
            .where(Exam.blueprint_id == blueprint_id)
            .order_by(Exam.created_at.desc())
            .options(selectinload(Exam.exam_questions))
        )
        return list(result.scalars().all())

    # ── Add a question to an exam ─────────────────────────────────────────────

    async def add_question(
        self,
        exam: Exam,
        payload: "AddExamQuestionRequest",
    ) -> ExamQuestion:
        """Append a question at the end of the exam (highest position + 1)."""
        db = self.db

        # Verify question exists and is approved
        result = await db.execute(
            select(Question).where(Question.id == payload.question_id)
        )
        question = result.scalar_one_or_none()
        if question is None:
            raise ValueError(f"Question {payload.question_id} not found.")
        if question.status != QuestionStatus.approved:
            raise ValueError(
                f"Question {payload.question_id} is not approved "
                f"(status={question.status.value}). Only approved questions can be added."
            )

        # Determine next position
        next_pos = (
            max((eq.position for eq in exam.exam_questions), default=0) + 1
            if exam.exam_questions
            else 1
        )

        eq = ExamQuestion(
            id=uuid.uuid4(),
            exam_id=exam.id,
            question_id=payload.question_id,
            position=next_pos,
            points=payload.points,
        )
        db.add(eq)
        await db.flush()
        await db.refresh(eq)
        return eq

    # ── Reorder exam questions ────────────────────────────────────────────────

    async def reorder(
        self,
        exam: Exam,
        payload: "ReorderExamQuestionsRequest",
    ) -> Exam:
        """
        Apply new positions (and optional points) to exam questions.

        Raises ValueError when:
          - An exam_question_id does not belong to this exam
          - Duplicate positions are provided
        """
        db = self.db

        # Validate no duplicate positions
        positions = [item.position for item in payload.items]
        if len(positions) != len(set(positions)):
            raise ValueError("Duplicate position values in reorder request.")

        eq_map: dict[uuid.UUID, ExamQuestion] = {
            eq.id: eq for eq in exam.exam_questions
        }

        for item in payload.items:
            eq = eq_map.get(item.exam_question_id)
            if eq is None:
                raise ValueError(
                    f"ExamQuestion {item.exam_question_id} does not belong to exam {exam.id}."
                )
            eq.position = item.position
            if item.points is not None:
                eq.points = item.points

        await db.flush()

        # Re-sort the in-memory list so the returned object is sorted
        exam.exam_questions.sort(key=lambda eq: eq.position)
        return exam

    # ── Remove a question from an exam ────────────────────────────────────────

    async def remove_question(self, exam_question: ExamQuestion) -> None:
        """Delete an ExamQuestion row and re-compact positions for the exam."""
        db = self.db
        exam_id = exam_question.exam_id

        await db.delete(exam_question)
        await db.flush()

        # Re-compact remaining positions to keep them contiguous (1, 2, 3, …)
        result = await db.execute(
            select(ExamQuestion)
            .where(ExamQuestion.exam_id == exam_id)
            .order_by(ExamQuestion.position)
        )
        remaining: list[ExamQuestion] = list(result.scalars().all())
        for idx, eq in enumerate(remaining, start=1):
            eq.position = idx

        await db.flush()
        logger.debug("ExamAssemblyService.remove_question: re-compacted %d questions", len(remaining))
