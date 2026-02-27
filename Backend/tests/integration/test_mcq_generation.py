"""
Integration tests: MCQ question generation end-to-end.

Exercises the full generate_mcq() path with:
  - MockProvider  (deterministic LLM responses)
  - Mocked RetrievalService (no pgvector / embedding calls)

After generation, verifies that every required database row was persisted:
  - Question (1 row)
  - McqOption (4 rows — A/B/C/D)
  - QuestionSource (one row per retrieved chunk referencing a real chunk FK)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.mock_provider import MockProvider
from app.models.chunk import Chunk
from app.models.course import Course
from app.models.question import McqOption, Question, QuestionSet, QuestionSource, QuestionType
from app.services.question_generation_service import QuestionGenerationService
from app.services.retrieval_service import RetrievalService, RetrievedChunk
from tests.integration.conftest import MCQ_MOCK_RESPONSE


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
async def mock_retrieval(chunk: Chunk) -> AsyncMock:
    """
    AsyncMock of RetrievalService that returns one RetrievedChunk backed by
    the real ``chunk`` DB row.

    No pgvector or embedding calls are made.
    """
    svc = AsyncMock(spec=RetrievalService)
    svc.retrieve_for_generation.return_value = [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            content=chunk.content,
            chunk_index=chunk.chunk_index,
            score=0.92,
        )
    ]
    return svc


@pytest.fixture()
async def generated_questions(
    db_session: AsyncSession,
    course: Course,
    question_set: QuestionSet,
    mock_provider: MockProvider,
    mock_retrieval: AsyncMock,
) -> list[Question]:
    """
    Run generate_mcq() once and return the persisted Question list.

    The fixture queues the MCQ mock response so that the first LLM call
    returns a valid MCQGenerationOutput.  Subsequent calls (difficulty + bloom
    tagging) use MockProvider's auto-instance fallback (which returns empty
    strings that are caught gracefully, leaving the heuristic result).
    """
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
    return questions


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestMCQGenerationPersistence:
    """generate_mcq() persists complete Question + options + sources."""

    async def test_returns_one_question(
        self, generated_questions: list[Question]
    ) -> None:
        """Service returns exactly one Question object."""
        assert len(generated_questions) == 1

    async def test_question_type_is_mcq(
        self, generated_questions: list[Question]
    ) -> None:
        q = generated_questions[0]
        assert q.type == QuestionType.mcq

    async def test_question_row_in_db(
        self, db_session: AsyncSession, generated_questions: list[Question]
    ) -> None:
        q = generated_questions[0]
        result = await db_session.execute(
            select(Question).where(Question.id == q.id)
        )
        found = result.scalar_one_or_none()
        assert found is not None

    async def test_question_body_is_not_empty(
        self, generated_questions: list[Question]
    ) -> None:
        q = generated_questions[0]
        assert q.body.strip() != ""

    async def test_question_linked_to_question_set(
        self,
        db_session: AsyncSession,
        generated_questions: list[Question],
        question_set: QuestionSet,
    ) -> None:
        result = await db_session.execute(
            select(Question).where(Question.id == generated_questions[0].id)
        )
        found = result.scalar_one()
        assert found.question_set_id == question_set.id

    async def test_four_mcq_options_created(
        self, db_session: AsyncSession, generated_questions: list[Question]
    ) -> None:
        q = generated_questions[0]
        result = await db_session.execute(
            select(McqOption).where(McqOption.question_id == q.id)
        )
        options = result.scalars().all()
        assert len(options) == 4

    async def test_mcq_option_labels_are_abcd(
        self, db_session: AsyncSession, generated_questions: list[Question]
    ) -> None:
        q = generated_questions[0]
        result = await db_session.execute(
            select(McqOption).where(McqOption.question_id == q.id)
        )
        options = result.scalars().all()
        labels = {o.label for o in options}
        assert labels == {"A", "B", "C", "D"}

    async def test_exactly_one_correct_mcq_option(
        self, db_session: AsyncSession, generated_questions: list[Question]
    ) -> None:
        q = generated_questions[0]
        result = await db_session.execute(
            select(McqOption).where(McqOption.question_id == q.id)
        )
        options = result.scalars().all()
        correct = [o for o in options if o.is_correct]
        assert len(correct) == 1

    async def test_question_source_created(
        self, db_session: AsyncSession, generated_questions: list[Question]
    ) -> None:
        """At least one QuestionSource row links this question to a chunk."""
        q = generated_questions[0]
        result = await db_session.execute(
            select(QuestionSource).where(QuestionSource.question_id == q.id)
        )
        sources = result.scalars().all()
        assert len(sources) >= 1

    async def test_question_source_has_valid_chunk_id(
        self,
        db_session: AsyncSession,
        generated_questions: list[Question],
        chunk: Chunk,
    ) -> None:
        """The QuestionSource.chunk_id must point to the real Chunk row."""
        q = generated_questions[0]
        result = await db_session.execute(
            select(QuestionSource).where(QuestionSource.question_id == q.id)
        )
        sources = result.scalars().all()
        chunk_ids = {s.chunk_id for s in sources}
        assert chunk.id in chunk_ids

    async def test_question_source_snippet_not_empty(
        self, db_session: AsyncSession, generated_questions: list[Question]
    ) -> None:
        q = generated_questions[0]
        result = await db_session.execute(
            select(QuestionSource).where(QuestionSource.question_id == q.id)
        )
        sources = result.scalars().all()
        for src in sources:
            assert src.snippet is not None and src.snippet.strip() != ""

    async def test_mock_provider_called_for_generation(
        self,
        mock_provider: MockProvider,
        generated_questions: list[Question],
    ) -> None:
        """MockProvider was called at least once (MCQ generation + validators)."""
        assert mock_provider.call_count >= 1

    async def test_retrieval_service_called(
        self,
        mock_retrieval: AsyncMock,
        generated_questions: list[Question],
    ) -> None:
        mock_retrieval.retrieve_for_generation.assert_awaited_once()

    async def test_question_model_name_recorded(
        self,
        generated_questions: list[Question],
    ) -> None:
        """Model name must be recorded for traceability."""
        q = generated_questions[0]
        assert q.model_name is not None and q.model_name.strip() != ""

    async def test_question_difficulty_set(
        self,
        generated_questions: list[Question],
    ) -> None:
        """Difficulty is tagged (heuristic fallback when LLM returns empty string)."""
        q = generated_questions[0]
        assert q.difficulty is not None
