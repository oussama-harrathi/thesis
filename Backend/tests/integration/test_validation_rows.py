"""
Integration tests: QuestionValidation rows written by the validator pipeline.

After generate_mcq() completes, _run_validators() should have written one
QuestionValidation row per check:
  - "grounding"   — question has at least one source snippet
  - "distractor"  — MCQ options pass structural quality checks
  - "difficulty"  — question difficulty is tagged
  - "bloom"       — Bloom taxonomy level is tagged

These tests also verify that the Question's difficulty and bloom_level fields
are updated in-place by the tagging validators.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.mock_provider import MockProvider
from app.models.chunk import Chunk
from app.models.course import Course
from app.models.question import Question, QuestionSet, QuestionValidation
from app.services.question_generation_service import QuestionGenerationService
from app.services.retrieval_service import RetrievalService, RetrievedChunk
from app.services.validation_service import (
    VALIDATION_TYPE_BLOOM,
    VALIDATION_TYPE_DIFFICULTY,
    VALIDATION_TYPE_DISTRACTOR,
    VALIDATION_TYPE_GROUNDING,
)
from tests.integration.conftest import MCQ_MOCK_RESPONSE


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
async def mock_retrieval(chunk: Chunk) -> AsyncMock:
    svc = AsyncMock(spec=RetrievalService)
    svc.retrieve_for_generation.return_value = [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            content=chunk.content,
            chunk_index=chunk.chunk_index,
            score=0.89,
        )
    ]
    return svc


@pytest.fixture()
async def generated_question(
    db_session: AsyncSession,
    course: Course,
    question_set: QuestionSet,
    mock_provider: MockProvider,
    mock_retrieval: AsyncMock,
) -> Question:
    """Run generate_mcq() and return the single persisted Question."""
    mock_provider.queue_response(MCQ_MOCK_RESPONSE)

    svc = QuestionGenerationService(
        provider=mock_provider,
        retrieval_service=mock_retrieval,
    )
    questions = await svc.generate_mcq(
        db_session,
        question_set_id=question_set.id,
        course_id=course.id,
        topic_name="Photosynthesis",
        difficulty="medium",
        count=1,
    )
    await db_session.commit()
    assert len(questions) == 1, "Fixture: generate_mcq() must return exactly 1 question."
    return questions[0]


@pytest.fixture()
async def validation_rows(
    db_session: AsyncSession, generated_question: Question
) -> list[QuestionValidation]:
    """Return all QuestionValidation rows for the generated question."""
    result = await db_session.execute(
        select(QuestionValidation).where(
            QuestionValidation.question_id == generated_question.id
        )
    )
    return list(result.scalars().all())


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestValidationRowsExist:
    """After generate_mcq, exactly one validation row per type must be present."""

    async def test_at_least_four_validation_rows(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        """Grounding + distractor + difficulty + bloom = 4 rows minimum."""
        assert len(validation_rows) >= 4

    async def test_grounding_row_exists(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        types = {r.validation_type for r in validation_rows}
        assert VALIDATION_TYPE_GROUNDING in types

    async def test_distractor_row_exists(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        types = {r.validation_type for r in validation_rows}
        assert VALIDATION_TYPE_DISTRACTOR in types

    async def test_difficulty_row_exists(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        types = {r.validation_type for r in validation_rows}
        assert VALIDATION_TYPE_DIFFICULTY in types

    async def test_bloom_row_exists(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        types = {r.validation_type for r in validation_rows}
        assert VALIDATION_TYPE_BLOOM in types


class TestValidationRowContents:
    """Each validation row carries meaningful values."""

    def _row(
        self,
        rows: list[QuestionValidation],
        validation_type: str,
    ) -> QuestionValidation:
        for r in rows:
            if r.validation_type == validation_type:
                return r
        pytest.fail(f"No validation row for type={validation_type!r}")

    async def test_grounding_passed(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        """Grounding check must pass — question was created with source chunks."""
        row = self._row(validation_rows, VALIDATION_TYPE_GROUNDING)
        assert row.passed is True

    async def test_distractor_passed(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        """Mock MCQ options are structurally valid; distractor check must pass."""
        row = self._row(validation_rows, VALIDATION_TYPE_DISTRACTOR)
        assert row.passed is True

    async def test_difficulty_has_score(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        row = self._row(validation_rows, VALIDATION_TYPE_DIFFICULTY)
        assert row.score is not None
        assert 0.0 <= row.score <= 1.0

    async def test_bloom_has_score(
        self, validation_rows: list[QuestionValidation]
    ) -> None:
        row = self._row(validation_rows, VALIDATION_TYPE_BLOOM)
        assert row.score is not None
        assert 0.0 <= row.score <= 1.0

    async def test_all_rows_linked_to_question(
        self,
        validation_rows: list[QuestionValidation],
        generated_question: Question,
    ) -> None:
        for row in validation_rows:
            assert row.question_id == generated_question.id


class TestQuestionFieldsUpdatedByValidators:
    """Validators must update the Question ORM row fields in-place."""

    async def test_difficulty_field_set_after_tagging(
        self,
        db_session: AsyncSession,
        generated_question: Question,
    ) -> None:
        """tag_difficulty() must update Question.difficulty (heuristic fallback)."""
        result = await db_session.execute(
            select(Question).where(Question.id == generated_question.id)
        )
        found = result.scalar_one()
        assert found.difficulty is not None

    async def test_bloom_level_field_set_after_tagging(
        self,
        db_session: AsyncSession,
        generated_question: Question,
    ) -> None:
        """tag_bloom() must update Question.bloom_level (heuristic fallback)."""
        result = await db_session.execute(
            select(Question).where(Question.id == generated_question.id)
        )
        found = result.scalar_one()
        assert found.bloom_level is not None
