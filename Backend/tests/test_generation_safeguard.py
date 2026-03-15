"""
Tests for the pre-LLM chunk-type safeguard in QuestionGenerationService.

These tests verify that when *all* retrieved chunks are classified as
boilerplate / admin content (caught by the text-based defense-in-depth
filter), the generator methods return an empty list and never invoke the
LLM provider.

No database, no real LLM needed: we mock RetrievalService and BaseLLMProvider.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.question_generation_service import QuestionGenerationService
from app.services.retrieval_service import MIN_CONTEXT_CHUNKS, RetrievedChunk

# ── Fixtures ──────────────────────────────────────────────────────────────────

COURSE_ID = uuid.uuid4()
QSET_ID   = uuid.uuid4()
TOPIC_ID  = uuid.uuid4()


def _make_boilerplate_chunks(n: int = 3) -> list[RetrievedChunk]:
    """
    Create n RetrievedChunk objects whose content triggers is_excluded_for_generation
    (the text-based filter used as defense-in-depth in the generation service).

    We use a references-boilerplate heading which is reliably caught.
    """
    return [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content=f"References\n\n[{i}] Knuth, D.E. The Art of Computer Programming.\n",
            chunk_index=i,
            score=0.9,
        )
        for i in range(1, n + 1)
    ]


def _make_real_chunks(n: int = 3) -> list[RetrievedChunk]:
    """Plain instructional content that passes the text safeguard."""
    content = (
        "A spanning tree is a subgraph that connects all vertices with "
        "the minimum possible number of edges (no cycles).  Kruskal's "
        "algorithm greedily selects the cheapest edge at each step."
    )
    return [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content=content,
            chunk_index=i,
            score=0.85,
        )
        for i in range(n)
    ]


# ── MCQ safeguard ─────────────────────────────────────────────────────────────

class TestMCQPreLLMSafeguard:
    @pytest.mark.asyncio
    async def test_all_boilerplate_chunks_blocks_llm(self):
        """
        When retrieve_for_generation returns only boilerplate chunks, the
        generate_mcq method should return [] without calling the LLM.
        """
        mock_provider  = AsyncMock()
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve_for_generation = AsyncMock(
            return_value=_make_boilerplate_chunks(MIN_CONTEXT_CHUNKS + 1)
        )

        db = AsyncMock()
        svc = QuestionGenerationService(
            provider=mock_provider,
            retrieval_service=mock_retrieval,
        )

        result = await svc.generate_mcq(
            db,
            question_set_id=QSET_ID,
            course_id=COURSE_ID,
            topic_name="Algorithms",
            difficulty="medium",
            count=2,
        )

        assert result == []
        # LLM should NOT have been called
        mock_provider.generate_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_chunks_allows_llm(self):
        """
        When retrieve_for_generation returns real instructional chunks,
        generate_mcq proceeds to call the LLM.
        """
        from app.schemas.llm_outputs import MCQGenerationOutput

        mock_provider = AsyncMock()
        # Return a minimal valid output so generation can complete
        mock_provider.generate_json = AsyncMock(
            return_value=MCQGenerationOutput(questions=[], insufficient_context=True)
        )
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve_for_generation = AsyncMock(
            return_value=_make_real_chunks(MIN_CONTEXT_CHUNKS + 1)
        )

        db = AsyncMock()
        svc = QuestionGenerationService(
            provider=mock_provider,
            retrieval_service=mock_retrieval,
        )

        result = await svc.generate_mcq(
            db,
            question_set_id=QSET_ID,
            course_id=COURSE_ID,
            topic_name="Algorithms",
            difficulty="medium",
            count=2,
        )

        # LLM WAS called (even if it returned insufficient_context)
        mock_provider.generate_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_medium_requires_two_chunks(self):
        """Medium questions should not call the LLM when only one good chunk exists."""
        mock_provider = AsyncMock()
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve_for_generation = AsyncMock(
            return_value=_make_real_chunks(1)
        )

        db = AsyncMock()
        svc = QuestionGenerationService(
            provider=mock_provider,
            retrieval_service=mock_retrieval,
        )

        result = await svc.generate_mcq(
            db,
            question_set_id=QSET_ID,
            course_id=COURSE_ID,
            topic_name="Algorithms",
            difficulty="medium",
            count=1,
        )

        assert result == []
        mock_provider.generate_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_detected_subject_is_injected_into_prompt(self):
        """A blank course_subject should be resolved once and inserted into the prompt."""
        from app.schemas.llm_outputs import MCQGenerationOutput

        mock_provider = AsyncMock()
        mock_provider.generate_json = AsyncMock(
            return_value=MCQGenerationOutput(questions=[], insufficient_context=True)
        )
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve_for_generation = AsyncMock(
            return_value=_make_real_chunks(2)
        )

        svc = QuestionGenerationService(
            provider=mock_provider,
            retrieval_service=mock_retrieval,
        )

        with patch(
            "app.services.course_subject_service.detect_course_subject",
            new=AsyncMock(return_value="Linear Algebra"),
        ) as mock_detect:
            await svc.generate_mcq(
                AsyncMock(),
                question_set_id=QSET_ID,
                course_id=COURSE_ID,
                topic_name="Matrices",
                difficulty="medium",
                count=1,
                course_subject="",
            )

        mock_detect.assert_awaited_once()
        prompt = mock_provider.generate_json.await_args.args[0]
        assert "Course subject   : Linear Algebra" in prompt


# ── True/False safeguard ──────────────────────────────────────────────────────

class TestTrueFalsePreLLMSafeguard:
    @pytest.mark.asyncio
    async def test_all_boilerplate_blocks_llm(self):
        mock_provider  = AsyncMock()
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve_for_generation = AsyncMock(
            return_value=_make_boilerplate_chunks(MIN_CONTEXT_CHUNKS + 1)
        )

        svc = QuestionGenerationService(
            provider=mock_provider,
            retrieval_service=mock_retrieval,
        )
        result = await svc.generate_true_false(
            AsyncMock(),
            question_set_id=QSET_ID,
            course_id=COURSE_ID,
            topic_name="Sorting",
            difficulty="easy",
            count=2,
        )
        assert result == []
        mock_provider.generate_json.assert_not_called()


# ── Short Answer safeguard ────────────────────────────────────────────────────

class TestShortAnswerPreLLMSafeguard:
    @pytest.mark.asyncio
    async def test_all_boilerplate_blocks_llm(self):
        mock_provider  = AsyncMock()
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve_for_generation = AsyncMock(
            return_value=_make_boilerplate_chunks(MIN_CONTEXT_CHUNKS + 1)
        )

        svc = QuestionGenerationService(
            provider=mock_provider,
            retrieval_service=mock_retrieval,
        )
        result = await svc.generate_short_answer(
            AsyncMock(),
            question_set_id=QSET_ID,
            course_id=COURSE_ID,
            topic_name="Graphs",
            difficulty="medium",
            count=1,
        )
        assert result == []
        mock_provider.generate_json.assert_not_called()


# ── Essay safeguard ───────────────────────────────────────────────────────────

class TestEssayPreLLMSafeguard:
    @pytest.mark.asyncio
    async def test_all_boilerplate_blocks_llm(self):
        mock_provider  = AsyncMock()
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve_for_generation = AsyncMock(
            return_value=_make_boilerplate_chunks(MIN_CONTEXT_CHUNKS + 1)
        )

        svc = QuestionGenerationService(
            provider=mock_provider,
            retrieval_service=mock_retrieval,
        )
        result = await svc.generate_essay(
            AsyncMock(),
            question_set_id=QSET_ID,
            course_id=COURSE_ID,
            topic_name="Complexity",
            difficulty="hard",
            count=1,
        )
        assert result == []
        mock_provider.generate_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_hard_requires_three_chunks(self):
        """Hard questions should not call the LLM when only two good chunks exist."""
        mock_provider  = AsyncMock()
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve_for_generation = AsyncMock(
            return_value=_make_real_chunks(2)
        )

        svc = QuestionGenerationService(
            provider=mock_provider,
            retrieval_service=mock_retrieval,
        )
        result = await svc.generate_essay(
            AsyncMock(),
            question_set_id=QSET_ID,
            course_id=COURSE_ID,
            topic_name="Complexity",
            difficulty="hard",
            count=1,
        )
        assert result == []
        mock_provider.generate_json.assert_not_called()
