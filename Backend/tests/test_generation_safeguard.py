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

def test_general_retrieval_seed_uses_course_subject():
    """General-slot retrieval should stay anchored to the detected course subject."""
    query = QuestionGenerationService.build_retrieval_query_seed(
        "General",
        "essay",
        "medium",
        course_subject="Neural Networks and Machine Learning",
    )

    assert query.startswith("Neural Networks and Machine Learning")


def test_support_chunk_selection_prefers_source_hint_and_caps_by_difficulty():
    """Only the minimum support set should be tracked, anchored to source_hint when possible."""
    chunks = [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content="Backpropagation updates weights by propagating error terms.",
            chunk_index=0,
            score=0.91,
        ),
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content="Overfitting occurs when a model memorizes the training data.",
            chunk_index=1,
            score=0.88,
        ),
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content="A perceptron computes a weighted sum and then applies an activation function.",
            chunk_index=2,
            score=0.86,
        ),
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content="Gradient descent reduces loss by following the negative gradient.",
            chunk_index=3,
            score=0.84,
        ),
    ]

    support = QuestionGenerationService._select_support_chunks(
        chunks,
        difficulty="hard",
        source_hint="A perceptron computes a weighted sum and then applies an activation function.",
    )

    assert len(support) == 3
    assert support[0].chunk_id == chunks[2].chunk_id


def test_hard_common_sense_question_is_rejected_by_difficulty_gate():
    """Hard slots should reject vague common-sense / opinion-like questions."""
    reason = QuestionGenerationService._difficulty_gate_reason(
        "Given that an AI technique requires common sense, what is the likelihood "
        "of it being fully practical in the foreseeable future?",
        "hard",
    )

    assert reason is not None


def test_medium_recall_question_is_rejected_by_difficulty_gate():
    """Medium slots should reject simple identification-style recall questions."""
    reason = QuestionGenerationService._difficulty_gate_reason(
        "Which of the following is a key characteristic of neural networks?",
        "medium",
    )

    assert reason is not None


def test_hard_scenario_question_passes_difficulty_gate():
    """Hard slots should allow scenario/inference-style questions."""
    reason = QuestionGenerationService._difficulty_gate_reason(
        "Given a neural network that fits the training data well but performs "
        "poorly on unseen data, which conclusion best explains this outcome?",
        "hard",
    )

    assert reason is None


def test_downgraded_difficulty_can_drop_hard_question_to_heuristic_level():
    """Weak hard-slot questions should downgrade to the lower heuristic level."""
    accepted = QuestionGenerationService._downgraded_difficulty(
        "How do neural networks contribute to decision-making in complex systems?",
        "hard",
    )

    assert accepted.value == "easy"


def test_downgraded_difficulty_steps_medium_question_down_to_easy():
    """Weak medium-slot questions should be accepted as easy when downgraded."""
    accepted = QuestionGenerationService._downgraded_difficulty(
        "Which characteristic makes neural networks unique?",
        "medium",
    )

    assert accepted.value == "easy"


def test_trivial_medium_question_is_rejected_without_downgrade():
    """Medium trivial questions should still be rejected when downgrade is disabled."""
    svc = QuestionGenerationService(
        provider=MagicMock(),
        retrieval_service=MagicMock(),
    )

    accepted, reason = svc._resolve_generation_acceptance(
        text="What is a qubit?",
        difficulty="medium",
        bloom="apply",
        allow_difficulty_downgrade=False,
    )

    assert accepted is None
    assert reason is not None


def test_trivial_hard_question_can_be_accepted_downgraded():
    """Final-attempt hard slots should keep grounded easy questions instead of failing."""
    svc = QuestionGenerationService(
        provider=MagicMock(),
        retrieval_service=MagicMock(),
    )

    accepted, reason = svc._resolve_generation_acceptance(
        text="What is the key difference between a classical bit and a qubit?",
        difficulty="hard",
        bloom="analyze",
        allow_difficulty_downgrade=True,
    )

    assert accepted in {"easy", "medium"}
    assert reason is not None


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
            course_subject="Algorithms",
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
            course_subject="Algorithms",
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
            course_subject="Algorithms",
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
            course_subject="Algorithms",
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
            course_subject="Algorithms",
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
            course_subject="Algorithms",
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
            course_subject="Algorithms",
        )
        assert result == []
        mock_provider.generate_json.assert_not_called()
