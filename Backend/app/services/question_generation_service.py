"""
Question Generation Service

Responsible for generating exam questions using the LLM provider and
persisting them to the database with full traceability (source chunks,
model metadata).

Currently supported types:
  - MCQ        (multiple-choice, 4 options, exactly 1 correct)
  - True/False (declarative statement + boolean answer)

Phase 7 stubs:
  - generate_short_answer / generate_essay  (later)

Generation flow for generate_mcq() and generate_true_false():
  1. Retrieve relevant chunks from pgvector via RetrievalService.
  2. Build a grounded prompt that embeds the retrieved context.
  3. Call the LLM provider with generate_json(prompt, <OutputSchema>).
  4. If insufficient_context=True and no questions returned, abort gracefully.
  5. For each parsed question:
       a. Insert a Question row.
       b. Insert McqOption rows A–D (MCQ only).
       c. Insert QuestionSource rows (one per retrieved chunk + source_hint).
  6. Return the list of persisted Question objects.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import BaseLLMProvider, GenerationSettings
from app.llm.factory import get_llm_provider
from app.llm.prompts.mcq_generation import MCQ_GENERATION_SYSTEM, MCQ_GENERATION_USER
from app.llm.prompts.tf_generation import TF_GENERATION_SYSTEM, TF_GENERATION_USER
from app.models.question import (
    Difficulty,
    McqOption,
    Question,
    QuestionSource,
    QuestionStatus,
    QuestionType,
)
from app.schemas.llm_outputs import (
    MCQGenerationOutput,
    MCQQuestionOutput,
    TrueFalseGenerationOutput,
    TFQuestionOutput,
)
from app.services.retrieval_service import RetrievalService, RetrievedChunk
from app.services.validation_service import ValidationService

logger = logging.getLogger(__name__)

# Bump these strings whenever the corresponding prompt templates change.
MCQ_PROMPT_VERSION = "mcq-v1"
TF_PROMPT_VERSION = "tf-v1"


class QuestionGenerationService:
    """
    Generates questions from retrieved course material and persists them.

    All public methods are async and accept an open SQLAlchemy AsyncSession.
    The caller is responsible for committing or rolling back.
    """

    def __init__(
        self,
        provider: BaseLLMProvider | None = None,
        retrieval_service: RetrievalService | None = None,
    ) -> None:
        # Allow injection for tests; fall back to factory / defaults at runtime.
        self._provider: BaseLLMProvider = provider or get_llm_provider()
        self._retrieval: RetrievalService = retrieval_service or RetrievalService()
        self._validation_svc = ValidationService()

    # ------------------------------------------------------------------ #
    # MCQ Generation                                                       #
    # ------------------------------------------------------------------ #

    async def generate_mcq(
        self,
        db: AsyncSession,
        *,
        question_set_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_id: uuid.UUID | None = None,
        topic_name: str = "General",
        difficulty: str = "medium",
        count: int = 1,
        top_k_chunks: int = 6,
        retrieval_query: str | None = None,
        generation_settings: GenerationSettings | None = None,
    ) -> list[Question]:
        """
        Generate *count* MCQ question(s) grounded in the course material.

        Parameters
        ----------
        db               : Open async session. Caller commits/rolls back.
        question_set_id  : The QuestionSet this batch belongs to.
        course_id        : Scope chunk retrieval to this course.
        topic_id         : Optional topic — enables topic-based retrieval.
        topic_name       : Human-readable topic label used in the prompt.
        difficulty       : "easy" | "medium" | "hard" — passed to the prompt.
        count            : How many MCQ questions to request from the LLM.
        top_k_chunks     : Number of chunks to retrieve for context.
        retrieval_query  : Free-text query for semantic retrieval.
                           Falls back to topic_name when not supplied.
        generation_settings : Optional per-call LLM overrides.

        Returns
        -------
        List of persisted Question objects (may be shorter than *count* if
        the LLM signals insufficient context).
        """
        # ── 1. Retrieve context chunks ─────────────────────────────────
        query = retrieval_query or topic_name
        chunks: list[RetrievedChunk] = await self._retrieval.retrieve_for_generation(
            db,
            query=query,
            topic_id=topic_id,
            course_id=course_id,
            top_k=top_k_chunks,
            min_score=0.1,
        )

        if not chunks:
            logger.warning(
                "generate_mcq: no chunks retrieved for course=%s topic=%s — skipping",
                course_id,
                topic_id,
            )
            return []

        logger.debug(
            "generate_mcq: retrieved %d chunks for course=%s topic=%s",
            len(chunks),
            course_id,
            topic_id,
        )

        # ── 2. Build grounded prompt ───────────────────────────────────
        context_text = self._format_context(chunks)
        prompt = self._build_mcq_prompt(
            context=context_text,
            topic=topic_name,
            difficulty=difficulty,
            count=count,
        )

        # ── 3. Call LLM ────────────────────────────────────────────────
        logger.info(
            "generate_mcq: calling LLM provider=%s count=%d topic=%r difficulty=%s",
            self._provider.provider_name,
            count,
            topic_name,
            difficulty,
        )
        try:
            output: MCQGenerationOutput = await self._provider.generate_json(
                prompt,
                MCQGenerationOutput,
                generation_settings,
            )
        except Exception as exc:
            logger.error(
                "generate_mcq: LLM call failed for course=%s topic=%s: %s",
                course_id,
                topic_id,
                exc,
                exc_info=True,
            )
            return []

        # ── 4. Handle insufficient context ────────────────────────────
        if output.insufficient_context and not output.questions:
            logger.warning(
                "generate_mcq: LLM returned insufficient_context=True and "
                "no questions for course=%s topic=%r",
                course_id,
                topic_name,
            )
            return []

        if output.insufficient_context:
            logger.warning(
                "generate_mcq: LLM flagged insufficient_context=True but "
                "returned %d question(s) — saving partial results",
                len(output.questions),
                extra={"course_id": str(course_id), "topic": topic_name},
            )

        # ── 5–7. Persist questions + options + sources ─────────────────
        saved: list[Question] = []
        for q_output in output.questions:
            try:
                question = await self._persist_mcq_question(
                    db,
                    q_output=q_output,
                    question_set_id=question_set_id,
                    difficulty=difficulty,
                    chunks=chunks,
                    insufficient_context=output.insufficient_context,
                )
                saved.append(question)
                await self._run_validators(db, question, is_mcq=True)
            except Exception as exc:
                # One bad question should not abort the whole batch.
                logger.error(
                    "generate_mcq: failed to persist question (stem=%r): %s",
                    q_output.stem[:60],
                    exc,
                    exc_info=True,
                )
                continue

        logger.info(
            "generate_mcq: saved %d/%d MCQ question(s) for course=%s",
            len(saved),
            len(output.questions),
            course_id,
        )
        return saved

    # ------------------------------------------------------------------ #
    # Post-generation validators                                           #
    # ------------------------------------------------------------------ #

    async def _run_validators(
        self,
        db: AsyncSession,
        question: Question,
        *,
        is_mcq: bool,
    ) -> None:
        """
        Run all quality-control validators against *question* in sequence.

        Each validator is individually try/excepted so that a failure in one
        does not prevent the remaining validators from running.

        Validators applied
        ------------------
          1. grounding      — all question types
          2. mcq_distractors — MCQ only
          3. difficulty     — all question types (heuristic + optional LLM)
          4. bloom          — all question types (heuristic + optional LLM)
        """
        # 1. Grounding — every question type
        try:
            await self._validation_svc.validate_grounding(db, question.id)
        except Exception as exc:
            logger.warning(
                "_run_validators: grounding check failed for question=%s: %s",
                question.id,
                exc,
            )

        # 2. MCQ distractor quality — MCQ only
        if is_mcq:
            try:
                await self._validation_svc.validate_mcq_distractors(db, question.id)
            except Exception as exc:
                logger.warning(
                    "_run_validators: distractor check failed for question=%s: %s",
                    question.id,
                    exc,
                )

        # 3. Difficulty tagging
        try:
            await self._validation_svc.tag_difficulty(
                db, question, provider=self._provider
            )
        except Exception as exc:
            logger.warning(
                "_run_validators: difficulty tagging failed for question=%s: %s",
                question.id,
                exc,
            )

        # 4. Bloom taxonomy tagging
        try:
            await self._validation_svc.tag_bloom(
                db, question, provider=self._provider
            )
        except Exception as exc:
            logger.warning(
                "_run_validators: bloom tagging failed for question=%s: %s",
                question.id,
                exc,
            )

    # ------------------------------------------------------------------ #
    # True/False Generation                                                #
    # ------------------------------------------------------------------ #

    async def generate_true_false(
        self,
        db: AsyncSession,
        *,
        question_set_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_id: uuid.UUID | None = None,
        topic_name: str = "General",
        difficulty: str = "medium",
        count: int = 1,
        top_k_chunks: int = 6,
        retrieval_query: str | None = None,
        generation_settings: GenerationSettings | None = None,
    ) -> list[Question]:
        """
        Generate *count* True/False question(s) grounded in the course material.

        Parameters mirror generate_mcq(); no MCQ options are created.

        Returns
        -------
        List of persisted Question objects (may be shorter than *count* if
        the LLM signals insufficient context).
        """
        # ── 1. Retrieve context chunks ─────────────────────────────────
        query = retrieval_query or topic_name
        chunks: list[RetrievedChunk] = await self._retrieval.retrieve_for_generation(
            db,
            query=query,
            topic_id=topic_id,
            course_id=course_id,
            top_k=top_k_chunks,
            min_score=0.1,
        )

        if not chunks:
            logger.warning(
                "generate_true_false: no chunks retrieved for course=%s topic=%s — skipping",
                course_id,
                topic_id,
            )
            return []

        logger.debug(
            "generate_true_false: retrieved %d chunks for course=%s topic=%s",
            len(chunks),
            course_id,
            topic_id,
        )

        # ── 2. Build grounded prompt ───────────────────────────────────
        context_text = self._format_context(chunks)
        prompt = self._build_tf_prompt(
            context=context_text,
            topic=topic_name,
            difficulty=difficulty,
            count=count,
        )

        # ── 3. Call LLM ────────────────────────────────────────────────
        logger.info(
            "generate_true_false: calling LLM provider=%s count=%d topic=%r difficulty=%s",
            self._provider.provider_name,
            count,
            topic_name,
            difficulty,
        )
        try:
            output: TrueFalseGenerationOutput = await self._provider.generate_json(
                prompt,
                TrueFalseGenerationOutput,
                generation_settings,
            )
        except Exception as exc:
            logger.error(
                "generate_true_false: LLM call failed for course=%s topic=%s: %s",
                course_id,
                topic_id,
                exc,
                exc_info=True,
            )
            return []

        # ── 4. Handle insufficient context ────────────────────────────
        if output.insufficient_context and not output.questions:
            logger.warning(
                "generate_true_false: LLM returned insufficient_context=True and "
                "no questions for course=%s topic=%r",
                course_id,
                topic_name,
            )
            return []

        if output.insufficient_context:
            logger.warning(
                "generate_true_false: LLM flagged insufficient_context=True but "
                "returned %d question(s) — saving partial results",
                len(output.questions),
                extra={"course_id": str(course_id), "topic": topic_name},
            )

        # ── 5–6. Persist questions + sources (no options for TF) ───────
        saved: list[Question] = []
        for q_output in output.questions:
            try:
                question = await self._persist_tf_question(
                    db,
                    q_output=q_output,
                    question_set_id=question_set_id,
                    difficulty=difficulty,
                    chunks=chunks,
                    insufficient_context=output.insufficient_context,
                )
                saved.append(question)
                await self._run_validators(db, question, is_mcq=False)
            except Exception as exc:
                logger.error(
                    "generate_true_false: failed to persist question (statement=%r): %s",
                    q_output.statement[:60],
                    exc,
                    exc_info=True,
                )
                continue

        logger.info(
            "generate_true_false: saved %d/%d TF question(s) for course=%s",
            len(saved),
            len(output.questions),
            course_id,
        )
        return saved

    # ------------------------------------------------------------------ #
    # Internal persistence helpers                                         #
    # ------------------------------------------------------------------ #

    async def _persist_mcq_question(
        self,
        db: AsyncSession,
        *,
        q_output: MCQQuestionOutput,
        question_set_id: uuid.UUID,
        difficulty: str,
        chunks: list[RetrievedChunk],
        insufficient_context: bool,
    ) -> Question:
        """
        Insert one MCQ Question row, its McqOption rows, and QuestionSource rows.

        Does NOT flush/commit — the caller (generate_mcq) is responsible.
        """
        # Resolve Difficulty enum, fallback to medium for unrecognised values.
        try:
            difficulty_enum = Difficulty(difficulty.lower())
        except ValueError:
            logger.warning(
                "_persist_mcq_question: unknown difficulty %r, defaulting to medium",
                difficulty,
            )
            difficulty_enum = Difficulty.medium

        # Determine the correct answer text for the Question.correct_answer field.
        correct_option = next(opt for opt in q_output.options if opt.is_correct)

        # ── Insert Question ────────────────────────────────────────────
        question = Question(
            id=uuid.uuid4(),
            question_set_id=question_set_id,
            type=QuestionType.mcq,
            body=q_output.stem,
            correct_answer=f"{correct_option.key}: {correct_option.text}",
            explanation=q_output.explanation,
            difficulty=difficulty_enum,
            status=QuestionStatus.draft,
            model_name=self._provider.provider_name,
            prompt_version=MCQ_PROMPT_VERSION,
            insufficient_context=insufficient_context,
        )
        db.add(question)

        # Flush to get the PK before inserting child rows.
        await db.flush()

        # ── Insert McqOptions ──────────────────────────────────────────
        for opt in q_output.options:
            db.add(
                McqOption(
                    id=uuid.uuid4(),
                    question_id=question.id,
                    label=opt.key,
                    text=opt.text,
                    is_correct=opt.is_correct,
                )
            )

        # ── Insert QuestionSources ─────────────────────────────────────
        await self._persist_sources(
            db,
            question=question,
            source_hint=q_output.source_hint,
            chunks=chunks,
        )

        return question

    async def _persist_tf_question(
        self,
        db: AsyncSession,
        *,
        q_output: TFQuestionOutput,
        question_set_id: uuid.UUID,
        difficulty: str,
        chunks: list[RetrievedChunk],
        insufficient_context: bool,
    ) -> Question:
        """
        Insert one True/False Question row and its QuestionSource rows.

        No McqOption rows are created for TF questions.
        Does NOT flush/commit — the caller (generate_true_false) is responsible.

        Storage conventions:
          body            — the declarative statement shown to the student
          correct_answer  — "True" or "False" (capitalised string)
          explanation     — rationale from the LLM, may be None
        """
        try:
            difficulty_enum = Difficulty(difficulty.lower())
        except ValueError:
            logger.warning(
                "_persist_tf_question: unknown difficulty %r, defaulting to medium",
                difficulty,
            )
            difficulty_enum = Difficulty.medium

        question = Question(
            id=uuid.uuid4(),
            question_set_id=question_set_id,
            type=QuestionType.true_false,
            body=q_output.statement,
            correct_answer="True" if q_output.is_true else "False",
            explanation=q_output.explanation if q_output.explanation else None,
            difficulty=difficulty_enum,
            status=QuestionStatus.draft,
            model_name=self._provider.provider_name,
            prompt_version=TF_PROMPT_VERSION,
            insufficient_context=insufficient_context,
        )
        db.add(question)

        # Flush to obtain PK before inserting child rows.
        await db.flush()

        # ── Insert QuestionSources (no options for TF) ─────────────────
        await self._persist_sources(
            db,
            question=question,
            source_hint=q_output.source_hint,
            chunks=chunks,
        )

        return question

    async def _persist_sources(
        self,
        db: AsyncSession,
        *,
        question: Question,
        source_hint: str | None,
        chunks: list[RetrievedChunk],
    ) -> None:
        """
        Create QuestionSource rows linking this question to its context chunks.

        Shared by all question types (MCQ, TF, …).

        Strategy:
        - One source row per retrieved chunk that contributed to the context.
        - If the LLM provided a source_hint, the first-ranked chunk's snippet
          is replaced with the verbatim source_hint to surface the most relevant
          excerpt.  All remaining chunks use a truncated version of their content.
        """
        if not chunks:
            return

        for idx, chunk in enumerate(chunks):
            # Use the LLM's verbatim source_hint for the top chunk only.
            if idx == 0 and source_hint:
                snippet = source_hint
            else:
                # Truncate long chunks to a readable excerpt.
                snippet = chunk.content[:500].strip()
                if len(chunk.content) > 500:
                    snippet += " …"

            db.add(
                QuestionSource(
                    id=uuid.uuid4(),
                    question_id=question.id,
                    chunk_id=chunk.chunk_id,
                    snippet=snippet,
                )
            )

    # ------------------------------------------------------------------ #
    # Prompt construction                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_context(chunks: list[RetrievedChunk]) -> str:
        """
        Concatenate chunk contents into a single context block.

        Each chunk is separated by a blank line and prefixed with its
        one-based index to give the LLM positional references.
        """
        parts: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            parts.append(f"[{i}] {chunk.content.strip()}")
        return "\n\n".join(parts)

    @staticmethod
    def _build_mcq_prompt(
        *,
        context: str,
        topic: str,
        difficulty: str,
        count: int,
    ) -> str:
        """
        Combine the MCQ system message and formatted user message into a
        single prompt string accepted by BaseLLMProvider.generate_json().
        """
        user_section = MCQ_GENERATION_USER.format(
            context=context,
            topic=topic,
            difficulty=difficulty,
            count=count,
        )
        return f"{MCQ_GENERATION_SYSTEM}\n---\n{user_section}"

    @staticmethod
    def _build_tf_prompt(
        *,
        context: str,
        topic: str,
        difficulty: str,
        count: int,
    ) -> str:
        """Combine the TF system + user messages into a single prompt string."""
        user_section = TF_GENERATION_USER.format(
            context=context,
            topic=topic,
            difficulty=difficulty,
            count=count,
        )
        return f"{TF_GENERATION_SYSTEM}\n---\n{user_section}"
