"""
Integration tests: Exam assembly from a blueprint and approved questions.

An ExamBlueprint ties exam configuration to a course.  ExamAssemblyService
collects all ``approved`` Question rows that belong to the course (or a
specific question set) and creates:
  - one Exam row
  - one ExamQuestion row per approved question

Tests also verify that assembly returns an empty exam when no approved
questions exist (graceful degradation).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.exam import Exam, ExamBlueprint, ExamQuestion
from app.models.question import Question, QuestionSet, QuestionStatus
from app.schemas.exam import AssembleExamRequest
from app.services.exam_assembly_service import ExamAssemblyService
from tests.integration.conftest import make_blueprint, make_mcq_question


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
async def approved_question(
    db_session: AsyncSession,
    question_set: QuestionSet,
) -> Question:
    """Create and commit an approved MCQ question."""
    return await make_mcq_question(
        db_session,
        question_set,
        status=QuestionStatus.approved,
    )


@pytest.fixture()
async def blueprint(
    db_session: AsyncSession,
    course: Course,
) -> ExamBlueprint:
    """Create and commit an ExamBlueprint for the integration test course."""
    return await make_blueprint(db_session, course)


@pytest.fixture()
async def assembled_exam(
    db_session: AsyncSession,
    blueprint: ExamBlueprint,
    approved_question: Question,
    question_set: QuestionSet,
) -> Exam:
    """
    Assemble an exam from the blueprint + one approved question.

    Commits the result so that ExamQuestion rows are visible to subsequent
    queries within the same session.
    """
    svc = ExamAssemblyService(db_session)
    payload = AssembleExamRequest(
        title="Integration Test Exam",
        description="Auto-assembled by pytest.",
        question_set_id=question_set.id,
    )
    exam = await svc.assemble(blueprint, payload)
    await db_session.commit()
    return exam


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestExamAssemblyCreatesExamRow:

    async def test_exam_row_exists_in_db(
        self,
        db_session: AsyncSession,
        assembled_exam: Exam,
    ) -> None:
        result = await db_session.execute(
            select(Exam).where(Exam.id == assembled_exam.id)
        )
        found = result.scalar_one_or_none()
        assert found is not None

    async def test_exam_title_persisted(
        self,
        db_session: AsyncSession,
        assembled_exam: Exam,
    ) -> None:
        result = await db_session.execute(
            select(Exam).where(Exam.id == assembled_exam.id)
        )
        found = result.scalar_one()
        assert found.title == "Integration Test Exam"

    async def test_exam_linked_to_blueprint(
        self,
        db_session: AsyncSession,
        assembled_exam: Exam,
        blueprint: ExamBlueprint,
    ) -> None:
        result = await db_session.execute(
            select(Exam).where(Exam.id == assembled_exam.id)
        )
        found = result.scalar_one()
        assert found.blueprint_id == blueprint.id

    async def test_exam_linked_to_course(
        self,
        db_session: AsyncSession,
        assembled_exam: Exam,
        course: Course,
    ) -> None:
        result = await db_session.execute(
            select(Exam).where(Exam.id == assembled_exam.id)
        )
        found = result.scalar_one()
        assert found.course_id == course.id


class TestExamAssemblyCreatesExamQuestions:

    async def test_one_exam_question_row_created(
        self,
        db_session: AsyncSession,
        assembled_exam: Exam,
    ) -> None:
        result = await db_session.execute(
            select(ExamQuestion).where(ExamQuestion.exam_id == assembled_exam.id)
        )
        rows = result.scalars().all()
        assert len(rows) == 1

    async def test_exam_question_links_to_approved_question(
        self,
        db_session: AsyncSession,
        assembled_exam: Exam,
        approved_question: Question,
    ) -> None:
        result = await db_session.execute(
            select(ExamQuestion).where(ExamQuestion.exam_id == assembled_exam.id)
        )
        rows = result.scalars().all()
        question_ids = {eq.question_id for eq in rows}
        assert approved_question.id in question_ids

    async def test_exam_question_position_starts_at_one(
        self,
        db_session: AsyncSession,
        assembled_exam: Exam,
    ) -> None:
        result = await db_session.execute(
            select(ExamQuestion).where(ExamQuestion.exam_id == assembled_exam.id)
        )
        rows = result.scalars().all()
        positions = sorted(eq.position for eq in rows)
        assert positions[0] == 1


class TestExamAssemblyWithNoDraftQuestions:
    """Assembly with only draft (not approved) questions yields an empty exam."""

    async def test_empty_exam_when_no_approved_questions(
        self,
        db_session: AsyncSession,
        course: Course,
        question_set: QuestionSet,
    ) -> None:
        # Insert a DRAFT question — assembly should ignore it.
        await make_mcq_question(db_session, question_set, status=QuestionStatus.draft)

        bp = await make_blueprint(db_session, course, title="No-Approved Blueprint")
        svc = ExamAssemblyService(db_session)
        payload = AssembleExamRequest(
            title="Empty Exam",
            question_set_id=question_set.id,
        )
        exam = await svc.assemble(bp, payload)
        await db_session.commit()

        result = await db_session.execute(
            select(ExamQuestion).where(ExamQuestion.exam_id == exam.id)
        )
        rows = result.scalars().all()
        assert len(rows) == 0, "Draft questions must not be assembled."
