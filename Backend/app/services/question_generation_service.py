"""
Question Generation Service

Responsible for generating exam questions using the LLM provider and
persisting them to the database with full traceability (source chunks,
model metadata).

Supported types:
  - MCQ             (multiple-choice, 4 options, exactly 1 correct)
  - True/False      (declarative statement + boolean answer)
  - Short Answer    (question + model answer + key grading points)
  - Essay           (open-ended prompt + model outline + rubric)

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
from app.llm.prompts.essay_generation import (
    ESSAY_GENERATION_SYSTEM,
    ESSAY_GENERATION_USER,
)
from app.llm.prompts.mcq_generation import MCQ_GENERATION_SYSTEM, MCQ_GENERATION_USER
from app.llm.prompts.short_answer_generation import (
    SHORT_ANSWER_GENERATION_SYSTEM,
    SHORT_ANSWER_GENERATION_USER,
)
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
    EssayGenerationOutput,
    EssayQuestionOutput,
    MCQGenerationOutput,
    MCQQuestionOutput,
    ShortAnswerGenerationOutput,
    ShortAnswerQuestionOutput,
    TrueFalseGenerationOutput,
    TFQuestionOutput,
)
from app.services.context_builder import ContextBuilder
from app.services.diversity_service import DiversityContext, DiversityService
from app.services.retrieval_service import MIN_CONTEXT_CHUNKS, RetrievalService, RetrievedChunk
from app.services.validation_service import CorrectnessResult, ValidationService
from app.utils.chunk_filter import DEFAULT_BLOOM_FOR_DIFFICULTY, is_duplicate_question, is_excluded_for_generation, should_reject_trivial
from app.utils.text_normalization import normalize_mcs_notation

logger = logging.getLogger(__name__)

# Bump these strings whenever the corresponding prompt templates change.
MCQ_PROMPT_VERSION = "mcq-v4"
TF_PROMPT_VERSION = "tf-v3"
SA_PROMPT_VERSION = "sa-v2"
ESSAY_PROMPT_VERSION = "essay-v1"


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
        diversity_service: DiversityService | None = None,
    ) -> None:
        # Allow injection for tests; fall back to factory / defaults at runtime.
        self._provider: BaseLLMProvider = provider or get_llm_provider()
        self._retrieval: RetrievalService = retrieval_service or RetrievalService()
        self._validation_svc = ValidationService()
        self._diversity_svc: DiversityService = diversity_service or DiversityService()

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
        exclude_chunk_ids: set[uuid.UUID] | None = None,
        _out_chunk_ids: list[uuid.UUID] | None = None,
        used_question_stems: list[str] | None = None,
        target_bloom: str | None = None,
        diversity_ctx: DiversityContext | None = None,
        generation_seed: int | None = None,
        penalize_chunk_ids: set[uuid.UUID] | None = None,
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
        List of persisted Question objects (may be empty if context is
        insufficient or grounding validation fails).
        """
        # ── 1. Retrieve context chunks (with course scoping + fallback) ───
        query = retrieval_query or topic_name
        chunks: list[RetrievedChunk] = await self._retrieval.retrieve_for_generation(
            db,
            query=query,
            topic_id=topic_id,
            course_id=course_id,
            top_k=top_k_chunks,
            min_score=0.1,
            exclude_chunk_ids=exclude_chunk_ids,
            penalize_chunk_ids=penalize_chunk_ids,
            generation_seed=generation_seed,
        )

        logger.info(
            "generate_mcq: retrieved %d chunks for course=%s topic=%r topic_id=%s "
            "(min_required=%d) context_chars=%d",
            len(chunks), course_id, topic_name, topic_id, MIN_CONTEXT_CHUNKS,
            sum(len(c.content) for c in chunks),
        )

        if _out_chunk_ids is not None:
            _out_chunk_ids.extend(c.chunk_id for c in chunks)

        if not chunks:
            logger.warning(
                "generate_mcq: SKIP — 0 chunks after fallback for course=%s topic=%r",
                course_id, topic_name,
            )
            return []

        # ── Defense-in-depth: text-based re-filter ─────────────────────────
        # Catches boilerplate chunks that were persisted before the chunk_type
        # column existed (server_default sets them all to 'instructional').
        # For chunks persisted post-migration this is a fast no-op.
        chunks = [c for c in chunks if not is_excluded_for_generation(c.content)]
        if len(chunks) < MIN_CONTEXT_CHUNKS:
            logger.warning(
                "generate_mcq: SKIP after pre-LLM text safeguard — "
                "%d chunk(s) remain (need %d) for course=%s topic=%r",
                len(chunks), MIN_CONTEXT_CHUNKS, course_id, topic_name,
            )
            return []

        # ── 2. Build compact, token-efficient context ──────────────────────
        bloom = target_bloom or DEFAULT_BLOOM_FOR_DIFFICULTY.get(difficulty.lower(), "apply")
        context_text = ContextBuilder.build(chunks)
        prompt = self._build_mcq_prompt(
            context=context_text,
            topic=topic_name,
            difficulty=difficulty,
            count=count,
            target_bloom=bloom,
        )

        # ── 3. Call LLM ────────────────────────────────────────────────
        logger.info(
            "generate_mcq: calling LLM provider=%s count=%d topic=%r difficulty=%s "
            "context_chunks=%d",
            self._provider.provider_name, count, topic_name, difficulty, len(chunks),
        )
        try:
            output: MCQGenerationOutput = await self._provider.generate_json(
                prompt,
                MCQGenerationOutput,
                generation_settings,
            )
        except Exception as exc:
            logger.error(
                "generate_mcq: LLM call failed for course=%s topic=%r: %s",
                course_id, topic_name, exc, exc_info=True,
            )
            return []

        # ── 4. Hard grounding gate ─────────────────────────────────────
        # If the LLM flagged insufficient context, discard all returned questions.
        # They were likely hallucinated from external knowledge.
        if output.insufficient_context:
            logger.warning(
                "generate_mcq: LLM returned insufficient_context=True for "
                "course=%s topic=%r — discarding %d question(s) to prevent hallucination",
                course_id, topic_name, len(output.questions),
            )
            return []

        if not output.questions:
            logger.warning(
                "generate_mcq: LLM returned 0 questions (no insufficient_context flag) "
                "for course=%s topic=%r",
                course_id, topic_name,
            )
            return []

        # ── 5–7. Persist questions + options + sources ─────────────────
        saved: list[Question] = []
        for q_output in output.questions:
            # B) Normalize MCS / math-symbol artifacts in all text fields.
            q_output = q_output.model_copy(update={
                "stem": normalize_mcs_notation(q_output.stem),
                "options": [
                    opt.model_copy(update={"text": normalize_mcs_notation(opt.text)})
                    for opt in q_output.options
                ],
                "explanation": (
                    normalize_mcs_notation(q_output.explanation)
                    if q_output.explanation else None
                ),
            })

            # Validate MCQ structure before persisting.
            if not self._validate_mcq_structure(q_output):
                logger.warning(
                    "generate_mcq: invalid MCQ structure (stem=%r) — skipping",
                    q_output.stem[:80],
                )
                continue
            # Duplicate detection across the current generation job.
            if used_question_stems is not None:
                is_dup, sim = is_duplicate_question(q_output.stem, used_question_stems)
                if is_dup:
                    logger.warning(
                        "generate_mcq: DUPLICATE detected (sim=%.2f) stem=%r — skipping",
                        sim, q_output.stem[:80],
                    )
                    continue
            # Triviality guard: skip trivial stems for medium/hard slots.
            if should_reject_trivial(q_output.stem, difficulty, bloom):
                logger.warning(
                    "generate_mcq: TRIVIAL stem for %s/%s — skipping stem=%r",
                    difficulty, bloom, q_output.stem[:80],
                )
                continue

            # ── Diversity checks: fingerprint + embedding ──────────────
            q_fp = self._diversity_svc.compute_fingerprint(q_output.stem)
            try:
                q_emb = await self._diversity_svc.compute_embedding(q_output.stem)
            except Exception as _emb_exc:
                logger.warning(
                    "generate_mcq: embedding failed (%s) — diversity checks skipped",
                    _emb_exc,
                )
                q_emb = []

            if diversity_ctx is not None and q_emb:
                _bl, _bl_reason = self._diversity_svc.is_blacklisted(
                    q_output.stem, q_emb, diversity_ctx
                )
                if _bl:
                    diversity_ctx.blacklist_avoided += 1
                    logger.warning(
                        "generate_mcq: BLACKLISTED (%s) stem=%r — skipping",
                        _bl_reason, q_output.stem[:80],
                    )
                    continue
                _rd, _rd_reason = self._diversity_svc.is_recent_duplicate(
                    q_output.stem, q_emb, diversity_ctx
                )
                if _rd:
                    diversity_ctx.dedup_avoided += 1
                    logger.warning(
                        "generate_mcq: RECENT_DUPLICATE (%s) stem=%r — skipping",
                        _rd_reason, q_output.stem[:80],
                    )
                    continue

            # A) Pre-persist MCQ correctness verification.
            mcq_correctness: CorrectnessResult | None = None
            try:
                options_fmt = "\n".join(
                    f"  {opt.key}. {opt.text}"
                    + ("  \u2190 marked correct" if opt.is_correct else "")
                    for opt in q_output.options
                )
                claimed_key = next(
                    (opt.key for opt in q_output.options if opt.is_correct), "?"
                )
                mcq_correctness = await self._validation_svc.verify_mcq_correctness(
                    stem=q_output.stem,
                    options_text=options_fmt,
                    claimed_correct=claimed_key,
                    context_text=context_text,
                    provider=self._provider,
                )
                if mcq_correctness.should_reject:
                    logger.warning(
                        "generate_mcq: CORRECTNESS FAIL — rejecting stem=%r "
                        "(verdict=%s confidence=%.2f)",
                        q_output.stem[:80],
                        mcq_correctness.verdict.value,
                        mcq_correctness.confidence,
                    )
                    continue
            except Exception as exc:
                logger.warning(
                    "generate_mcq: correctness check error — proceeding: %s", exc
                )

            try:
                question = await self._persist_mcq_question(
                    db,
                    q_output=q_output,
                    question_set_id=question_set_id,
                    difficulty=difficulty,
                    chunks=chunks,
                    insufficient_context=False,
                    fingerprint=q_fp,
                    embedding=q_emb if q_emb else None,
                    generation_run_id=question_set_id,
                )
                saved.append(question)
                if used_question_stems is not None:
                    used_question_stems.append(q_output.stem)
                await self._run_validators(
                    db, question, is_mcq=True,
                    target_difficulty=difficulty, target_bloom=bloom,
                    correctness_result=mcq_correctness,
                )
                if len(saved) >= count:
                    break  # LLM over-produced; stop persisting beyond requested count
            except Exception as exc:
                # One bad question should not abort the whole batch.
                logger.error(
                    "generate_mcq: failed to persist question (stem=%r): %s",
                    q_output.stem[:60], exc, exc_info=True,
                )
                continue

        logger.info(
            "generate_mcq: saved %d/%d MCQ question(s) for course=%s topic=%r",
            len(saved), len(output.questions), course_id, topic_name,
        )
        return saved

    # ------------------------------------------------------------------ #
    # Structure validators (pre-persist)                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_mcq_structure(q_output: "MCQQuestionOutput") -> bool:
        """
        Return False (and log a warning) if the MCQ output is structurally invalid.

        Checks:
        - Exactly 4 options present.
        - Option keys are exactly {A, B, C, D} (no repeats).
        - Exactly one option has is_correct=True.
        - Stem is non-empty.
        """
        if not q_output.stem or not q_output.stem.strip():
            logger.warning("_validate_mcq_structure: empty stem")
            return False

        if len(q_output.options) != 4:
            logger.warning(
                "_validate_mcq_structure: expected 4 options, got %d",
                len(q_output.options),
            )
            return False

        keys = {opt.key for opt in q_output.options}
        if keys != {"A", "B", "C", "D"}:
            logger.warning(
                "_validate_mcq_structure: option keys %s ≠ {A,B,C,D}", keys
            )
            return False

        correct_count = sum(1 for opt in q_output.options if opt.is_correct)
        if correct_count != 1:
            logger.warning(
                "_validate_mcq_structure: expected 1 correct option, got %d",
                correct_count,
            )
            return False

        return True

    # ------------------------------------------------------------------ #
    # Post-generation validators                                           #
    # ------------------------------------------------------------------ #

    async def _run_validators(
        self,
        db: AsyncSession,
        question: Question,
        *,
        is_mcq: bool,
        target_difficulty: str = "medium",
        target_bloom: str = "apply",
        correctness_result: CorrectnessResult | None = None,
    ) -> None:
        """
        Run all quality-control validators against *question* in sequence.

        Validators applied
        ------------------
          1. grounding      — all question types
          2. mcq_distractors — MCQ only
          3. difficulty     — all question types (heuristic + optional LLM)
          4. bloom          — all question types (heuristic + optional LLM)
          5. triviality     — all question types (heuristic; WARN/FAIL)
          6. correctness    — MCQ + TF (persists pre-computed LLM verification result)
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

        # 3. Difficulty tagging — heuristic, for the validation audit row ONLY.
        #    The question was generated for a specific blueprint-requested difficulty;
        #    we must NOT overwrite that with an unreliable heuristic guess.
        #    update_question=False keeps the generation-requested difficulty intact
        #    while still recording the heuristic result in question_validations.
        try:
            await self._validation_svc.tag_difficulty(
                db, question, provider=None, update_question=False
            )
        except Exception as exc:
            logger.warning(
                "_run_validators: difficulty tagging failed for question=%s: %s",
                question.id,
                exc,
            )

        # 4. Bloom taxonomy tagging — heuristic only (same reason as above).
        try:
            await self._validation_svc.tag_bloom(
                db, question, provider=None
            )
        except Exception as exc:
            logger.warning(
                "_run_validators: bloom tagging failed for question=%s: %s",
                question.id,
                exc,
            )

        # 5. Triviality check
        try:
            await self._validation_svc.validate_triviality(
                db, question,
                target_difficulty=target_difficulty,
                target_bloom=target_bloom,
            )
        except Exception as exc:
            logger.warning(
                "_run_validators: triviality check failed for question=%s: %s",
                question.id, exc,
            )

        # 6. Correctness — persist a pre-computed CorrectnessResult when provided.
        #    The actual LLM verification ran before persistence so we only write
        #    the stored result here (no extra LLM call at this stage).
        if correctness_result is not None:
            try:
                await self._validation_svc.persist_correctness_result(
                    db, question.id, correctness_result
                )
            except Exception as exc:
                logger.warning(
                    "_run_validators: correctness persist failed for question=%s: %s",
                    question.id, exc,
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
        exclude_chunk_ids: set[uuid.UUID] | None = None,
        _out_chunk_ids: list[uuid.UUID] | None = None,
        used_question_stems: list[str] | None = None,
        target_bloom: str | None = None,
        diversity_ctx: DiversityContext | None = None,
        generation_seed: int | None = None,
        penalize_chunk_ids: set[uuid.UUID] | None = None,
    ) -> list[Question]:
        """
        Generate *count* True/False question(s) grounded in the course material.

        Parameters mirror generate_mcq(); no MCQ options are created.

        Returns
        -------
        List of persisted Question objects (may be empty if context is
        insufficient or grounding validation fails).
        """
        # ── 1. Retrieve context chunks (with course scoping + fallback) ───
        query = retrieval_query or topic_name
        chunks: list[RetrievedChunk] = await self._retrieval.retrieve_for_generation(
            db,
            query=query,
            topic_id=topic_id,
            course_id=course_id,
            top_k=top_k_chunks,
            min_score=0.1,
            exclude_chunk_ids=exclude_chunk_ids,
            penalize_chunk_ids=penalize_chunk_ids,
            generation_seed=generation_seed,
        )

        logger.info(
            "generate_true_false: retrieved %d chunks for course=%s topic=%r topic_id=%s "
            "(min_required=%d) context_chars=%d",
            len(chunks), course_id, topic_name, topic_id, MIN_CONTEXT_CHUNKS,
            sum(len(c.content) for c in chunks),
        )

        if _out_chunk_ids is not None:
            _out_chunk_ids.extend(c.chunk_id for c in chunks)

        if not chunks:
            logger.warning(
                "generate_true_false: SKIP — 0 chunks after fallback for course=%s topic=%r",
                course_id, topic_name,
            )
            return []

        # ── Defense-in-depth: text-based re-filter ─────────────────────────
        chunks = [c for c in chunks if not is_excluded_for_generation(c.content)]
        if len(chunks) < MIN_CONTEXT_CHUNKS:
            logger.warning(
                "generate_true_false: SKIP after pre-LLM text safeguard — "
                "%d chunk(s) remain (need %d) for course=%s topic=%r",
                len(chunks), MIN_CONTEXT_CHUNKS, course_id, topic_name,
            )
            return []

        # ── 2. Build compact, token-efficient context ──────────────────────
        bloom = target_bloom or DEFAULT_BLOOM_FOR_DIFFICULTY.get(difficulty.lower(), "apply")
        context_text = ContextBuilder.build(chunks)
        prompt = self._build_tf_prompt(
            context=context_text,
            topic=topic_name,
            difficulty=difficulty,
            count=count,
            target_bloom=bloom,
        )

        # ── 3. Call LLM ────────────────────────────────────────────────
        logger.info(
            "generate_true_false: calling LLM provider=%s count=%d topic=%r difficulty=%s "
            "context_chunks=%d",
            self._provider.provider_name, count, topic_name, difficulty, len(chunks),
        )
        try:
            output: TrueFalseGenerationOutput = await self._provider.generate_json(
                prompt,
                TrueFalseGenerationOutput,
                generation_settings,
            )
        except Exception as exc:
            logger.error(
                "generate_true_false: LLM call failed for course=%s topic=%r: %s",
                course_id, topic_name, exc, exc_info=True,
            )
            return []

        # ── 4. Hard grounding gate ─────────────────────────────────────
        if output.insufficient_context:
            logger.warning(
                "generate_true_false: LLM returned insufficient_context=True for "
                "course=%s topic=%r — discarding %d question(s) to prevent hallucination",
                course_id, topic_name, len(output.questions),
            )
            return []

        if not output.questions:
            logger.warning(
                "generate_true_false: LLM returned 0 questions for course=%s topic=%r",
                course_id, topic_name,
            )
            return []

        # ── 5–6. Persist questions + sources (no options for TF) ───────
        saved: list[Question] = []
        for q_output in output.questions:
            # B) Normalize MCS / math-symbol artifacts.
            q_output = q_output.model_copy(update={
                "statement": normalize_mcs_notation(q_output.statement),
                "explanation": (
                    normalize_mcs_notation(q_output.explanation)
                    if q_output.explanation else None
                ),
            })

            # Duplicate detection
            if used_question_stems is not None:
                is_dup, sim = is_duplicate_question(q_output.statement, used_question_stems)
                if is_dup:
                    logger.warning(
                        "generate_true_false: DUPLICATE detected (sim=%.2f) statement=%r — skipping",
                        sim, q_output.statement[:80],
                    )
                    continue
            # Triviality guard
            if should_reject_trivial(q_output.statement, difficulty, bloom):
                logger.warning(
                    "generate_true_false: TRIVIAL for %s/%s — skipping statement=%r",
                    difficulty, bloom, q_output.statement[:80],
                )
                continue

            # ── Diversity checks: fingerprint + embedding ──────────────────
            tf_fp = self._diversity_svc.compute_fingerprint(q_output.statement)
            try:
                tf_emb = await self._diversity_svc.compute_embedding(q_output.statement)
            except Exception as _emb_exc:
                logger.warning(
                    "generate_true_false: embedding failed (%s) — diversity checks skipped",
                    _emb_exc,
                )
                tf_emb = []

            if diversity_ctx is not None and tf_emb:
                _bl, _bl_reason = self._diversity_svc.is_blacklisted(
                    q_output.statement, tf_emb, diversity_ctx
                )
                if _bl:
                    diversity_ctx.blacklist_avoided += 1
                    logger.warning(
                        "generate_true_false: BLACKLISTED (%s) statement=%r — skipping",
                        _bl_reason, q_output.statement[:80],
                    )
                    continue
                _rd, _rd_reason = self._diversity_svc.is_recent_duplicate(
                    q_output.statement, tf_emb, diversity_ctx
                )
                if _rd:
                    diversity_ctx.dedup_avoided += 1
                    logger.warning(
                        "generate_true_false: RECENT_DUPLICATE (%s) statement=%r — skipping",
                        _rd_reason, q_output.statement[:80],
                    )
                    continue

            # A) Pre-persist TF correctness verification.
            tf_correctness: CorrectnessResult | None = None
            try:
                tf_correctness = await self._validation_svc.verify_tf_correctness(
                    statement=q_output.statement,
                    is_true=q_output.is_true,
                    context_text=context_text,
                    provider=self._provider,
                )
                if tf_correctness.should_reject:
                    logger.warning(
                        "generate_true_false: CORRECTNESS FAIL — rejecting statement=%r "
                        "(verdict=%s confidence=%.2f)",
                        q_output.statement[:80],
                        tf_correctness.verdict.value,
                        tf_correctness.confidence,
                    )
                    continue
                if tf_correctness.should_flip and tf_correctness.correct_is_true is not None:
                    logger.info(
                        "generate_true_false: FLIP label %s\u2192%s for statement=%r",
                        q_output.is_true, tf_correctness.correct_is_true,
                        q_output.statement[:60],
                    )
                    q_output = q_output.model_copy(
                        update={"is_true": tf_correctness.correct_is_true}
                    )
            except Exception as exc:
                logger.warning(
                    "generate_true_false: correctness check error — proceeding: %s", exc
                )

            try:
                question = await self._persist_tf_question(
                    db,
                    q_output=q_output,
                    question_set_id=question_set_id,
                    difficulty=difficulty,
                    chunks=chunks,
                    insufficient_context=False,
                    fingerprint=tf_fp,
                    embedding=tf_emb if tf_emb else None,
                    generation_run_id=question_set_id,
                )
                saved.append(question)
                if used_question_stems is not None:
                    used_question_stems.append(q_output.statement)
                await self._run_validators(
                    db, question, is_mcq=False,
                    target_difficulty=difficulty, target_bloom=bloom,
                    correctness_result=tf_correctness,
                )
                if len(saved) >= count:
                    break  # LLM over-produced; stop persisting beyond requested count
            except Exception as exc:
                logger.error(
                    "generate_true_false: failed to persist question (statement=%r): %s",
                    q_output.statement[:60], exc, exc_info=True,
                )
                continue

        logger.info(
            "generate_true_false: saved %d/%d TF question(s) for course=%s topic=%r",
            len(saved), len(output.questions), course_id, topic_name,
        )
        return saved

    # ------------------------------------------------------------------ #
    # Short Answer Generation                                              #
    # ------------------------------------------------------------------ #

    async def generate_short_answer(
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
        exclude_chunk_ids: set[uuid.UUID] | None = None,
        _out_chunk_ids: list[uuid.UUID] | None = None,
        used_question_stems: list[str] | None = None,
        target_bloom: str | None = None,
        diversity_ctx: DiversityContext | None = None,
        generation_seed: int | None = None,
        penalize_chunk_ids: set[uuid.UUID] | None = None,
    ) -> list[Question]:
        """
        Generate *count* Short Answer question(s) grounded in the course material.

        Each question has a ``body`` (the question text), a ``correct_answer``
        (model answer), and an ``explanation`` (key grading points joined).

        Returns
        -------
        List of persisted Question objects (may be empty if context is
        insufficient or grounding validation fails).
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
            exclude_chunk_ids=exclude_chunk_ids,
            penalize_chunk_ids=penalize_chunk_ids,
            generation_seed=generation_seed,
        )

        logger.info(
            "generate_short_answer: retrieved %d chunks for course=%s topic=%r "
            "topic_id=%s (min_required=%d) context_chars=%d",
            len(chunks), course_id, topic_name, topic_id, MIN_CONTEXT_CHUNKS,
            sum(len(c.content) for c in chunks),
        )

        if _out_chunk_ids is not None:
            _out_chunk_ids.extend(c.chunk_id for c in chunks)

        if not chunks:
            logger.warning(
                "generate_short_answer: SKIP — 0 chunks after fallback for "
                "course=%s topic=%r",
                course_id, topic_name,
            )
            return []

        # ── Defense-in-depth: text-based re-filter ─────────────────────────
        chunks = [c for c in chunks if not is_excluded_for_generation(c.content)]
        if len(chunks) < MIN_CONTEXT_CHUNKS:
            logger.warning(
                "generate_short_answer: SKIP after pre-LLM text safeguard — "
                "%d chunk(s) remain (need %d) for course=%s topic=%r",
                len(chunks), MIN_CONTEXT_CHUNKS, course_id, topic_name,
            )
            return []

        # ── 2. Build compact context ───────────────────────────────────
        bloom = target_bloom or DEFAULT_BLOOM_FOR_DIFFICULTY.get(difficulty.lower(), "apply")
        context_text = ContextBuilder.build(chunks)
        non_trivial_block = self._build_non_triviality_block(difficulty, bloom)
        user_section = SHORT_ANSWER_GENERATION_USER.format(
            context=context_text,
            topic=topic_name,
            difficulty=difficulty,
            count=count,
            target_bloom=bloom,
            non_triviality_block=non_trivial_block,
        )
        prompt = f"{SHORT_ANSWER_GENERATION_SYSTEM}\n---\n{user_section}"

        # ── 3. Call LLM ────────────────────────────────────────────────
        logger.info(
            "generate_short_answer: calling LLM provider=%s count=%d topic=%r "
            "difficulty=%s context_chunks=%d",
            self._provider.provider_name, count, topic_name, difficulty, len(chunks),
        )
        try:
            output: ShortAnswerGenerationOutput = await self._provider.generate_json(
                prompt,
                ShortAnswerGenerationOutput,
                generation_settings,
            )
        except Exception as exc:
            logger.error(
                "generate_short_answer: LLM call failed for course=%s topic=%r: %s",
                course_id, topic_name, exc, exc_info=True,
            )
            return []

        # ── 4. Hard grounding gate ─────────────────────────────────────
        if output.insufficient_context:
            logger.warning(
                "generate_short_answer: LLM returned insufficient_context=True for "
                "course=%s topic=%r — discarding %d question(s) to prevent hallucination",
                course_id, topic_name, len(output.questions),
            )
            return []

        if not output.questions:
            logger.warning(
                "generate_short_answer: LLM returned 0 questions for "
                "course=%s topic=%r",
                course_id, topic_name,
            )
            return []

        # ── 5. Persist questions + sources ─────────────────────────────
        saved: list[Question] = []
        for q_output in output.questions:
            # B) Normalize MCS / math-symbol artifacts.
            q_output = q_output.model_copy(update={
                "question":     normalize_mcs_notation(q_output.question or ""),
                "model_answer": normalize_mcs_notation(q_output.model_answer or ""),
                "key_points": [
                    normalize_mcs_notation(kp) for kp in (q_output.key_points or [])
                ],
            })

            if not q_output.question or not q_output.question.strip():
                logger.warning(
                    "generate_short_answer: empty question text — skipping"
                )
                continue
            if not q_output.model_answer or not q_output.model_answer.strip():
                logger.warning(
                    "generate_short_answer: empty model_answer — skipping"
                )
                continue
            # Duplicate detection
            if used_question_stems is not None:
                is_dup, sim = is_duplicate_question(q_output.question, used_question_stems)
                if is_dup:
                    logger.warning(
                        "generate_short_answer: DUPLICATE detected (sim=%.2f) q=%r — skipping",
                        sim, q_output.question[:80],
                    )
                    continue
            # Triviality guard
            if should_reject_trivial(q_output.question, difficulty, bloom):
                logger.warning(
                    "generate_short_answer: TRIVIAL for %s/%s — skipping q=%r",
                    difficulty, bloom, q_output.question[:80],
                )
                continue

            # ── Diversity checks: fingerprint + embedding ──────────────────
            sa_fp = self._diversity_svc.compute_fingerprint(q_output.question)
            try:
                sa_emb = await self._diversity_svc.compute_embedding(q_output.question)
            except Exception as _emb_exc:
                logger.warning(
                    "generate_short_answer: embedding failed (%s) — diversity checks skipped",
                    _emb_exc,
                )
                sa_emb = []

            if diversity_ctx is not None and sa_emb:
                _bl, _bl_reason = self._diversity_svc.is_blacklisted(
                    q_output.question, sa_emb, diversity_ctx
                )
                if _bl:
                    diversity_ctx.blacklist_avoided += 1
                    logger.warning(
                        "generate_short_answer: BLACKLISTED (%s) q=%r — skipping",
                        _bl_reason, q_output.question[:80],
                    )
                    continue
                _rd, _rd_reason = self._diversity_svc.is_recent_duplicate(
                    q_output.question, sa_emb, diversity_ctx
                )
                if _rd:
                    diversity_ctx.dedup_avoided += 1
                    logger.warning(
                        "generate_short_answer: RECENT_DUPLICATE (%s) q=%r — skipping",
                        _rd_reason, q_output.question[:80],
                    )
                    continue

            try:
                question = await self._persist_sa_question(
                    db,
                    q_output=q_output,
                    question_set_id=question_set_id,
                    difficulty=difficulty,
                    chunks=chunks,
                    fingerprint=sa_fp,
                    embedding=sa_emb if sa_emb else None,
                    generation_run_id=question_set_id,
                )
                saved.append(question)
                if used_question_stems is not None:
                    used_question_stems.append(q_output.question)
                await self._run_validators(db, question, is_mcq=False,
                                           target_difficulty=difficulty, target_bloom=bloom)
                if len(saved) >= count:
                    break  # LLM over-produced; stop persisting beyond requested count
            except Exception as exc:
                logger.error(
                    "generate_short_answer: failed to persist question=%r: %s",
                    q_output.question[:60], exc, exc_info=True,
                )
                continue

        logger.info(
            "generate_short_answer: saved %d/%d SA question(s) for "
            "course=%s topic=%r",
            len(saved), len(output.questions), course_id, topic_name,
        )
        return saved

    # ------------------------------------------------------------------ #
    # Essay Generation                                                     #
    # ------------------------------------------------------------------ #

    async def generate_essay(
        self,
        db: AsyncSession,
        *,
        question_set_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_id: uuid.UUID | None = None,
        topic_name: str = "General",
        difficulty: str = "medium",
        count: int = 1,
        top_k_chunks: int = 8,
        retrieval_query: str | None = None,
        generation_settings: GenerationSettings | None = None,
        exclude_chunk_ids: set[uuid.UUID] | None = None,
        _out_chunk_ids: list[uuid.UUID] | None = None,
        used_question_stems: list[str] | None = None,
        target_bloom: str | None = None,
        diversity_ctx: DiversityContext | None = None,
        generation_seed: int | None = None,
        penalize_chunk_ids: set[uuid.UUID] | None = None,
    ) -> list[Question]:
        """
        Generate *count* Essay/Development question(s) grounded in course material.

        Each question has a ``body`` (the question prompt), a ``correct_answer``
        (model outline), and an ``explanation`` (student guidance + rubric summary).

        Returns
        -------
        List of persisted Question objects (may be empty if context is
        insufficient or grounding validation fails).
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
            exclude_chunk_ids=exclude_chunk_ids,
            penalize_chunk_ids=penalize_chunk_ids,
            generation_seed=generation_seed,
        )

        logger.info(
            "generate_essay: retrieved %d chunks for course=%s topic=%r "
            "topic_id=%s (min_required=%d) context_chars=%d",
            len(chunks), course_id, topic_name, topic_id, MIN_CONTEXT_CHUNKS,
            sum(len(c.content) for c in chunks),
        )

        if _out_chunk_ids is not None:
            _out_chunk_ids.extend(c.chunk_id for c in chunks)

        if not chunks:
            logger.warning(
                "generate_essay: SKIP — 0 chunks after fallback for "
                "course=%s topic=%r",
                course_id, topic_name,
            )
            return []

        # ── Defense-in-depth: text-based re-filter ─────────────────────────
        chunks = [c for c in chunks if not is_excluded_for_generation(c.content)]
        if len(chunks) < MIN_CONTEXT_CHUNKS:
            logger.warning(
                "generate_essay: SKIP after pre-LLM text safeguard — "
                "%d chunk(s) remain (need %d) for course=%s topic=%r",
                len(chunks), MIN_CONTEXT_CHUNKS, course_id, topic_name,
            )
            return []

        # ── 2. Build prompt ────────────────────────────────────────────
        bloom = target_bloom or DEFAULT_BLOOM_FOR_DIFFICULTY.get(difficulty.lower(), "apply")
        context_text = ContextBuilder.build(chunks)
        prompt = self._build_essay_prompt(
            context=context_text,
            topic=topic_name,
            difficulty=difficulty,
            count=count,
            target_bloom=bloom,
        )

        # ── 3. Call LLM ────────────────────────────────────────────────
        logger.info(
            "generate_essay: calling LLM provider=%s count=%d topic=%r "
            "difficulty=%s context_chunks=%d",
            self._provider.provider_name, count, topic_name, difficulty, len(chunks),
        )
        try:
            output: EssayGenerationOutput = await self._provider.generate_json(
                prompt,
                EssayGenerationOutput,
                generation_settings,
            )
        except Exception as exc:
            logger.error(
                "generate_essay: LLM call failed for course=%s topic=%r: %s",
                course_id, topic_name, exc, exc_info=True,
            )
            return []

        # ── 4. Hard grounding gate ─────────────────────────────────────
        if output.insufficient_context:
            logger.warning(
                "generate_essay: LLM returned insufficient_context=True for "
                "course=%s topic=%r — discarding %d question(s) to prevent hallucination",
                course_id, topic_name, len(output.questions),
            )
            return []

        if not output.questions:
            logger.warning(
                "generate_essay: LLM returned 0 questions for course=%s topic=%r",
                course_id, topic_name,
            )
            return []

        # ── 5. Persist questions + sources ─────────────────────────────
        saved: list[Question] = []
        for q_output in output.questions:
            # Normalize MCS / math-symbol artifacts.
            q_output = q_output.model_copy(update={
                "question":     normalize_mcs_notation(q_output.question or ""),
                "model_outline": normalize_mcs_notation(q_output.model_outline or ""),
                "guidance": (
                    normalize_mcs_notation(q_output.guidance)
                    if q_output.guidance else None
                ),
            })

            if not q_output.question or not q_output.question.strip():
                logger.warning("generate_essay: empty question text — skipping")
                continue
            if not q_output.model_outline or not q_output.model_outline.strip():
                logger.warning("generate_essay: empty model_outline — skipping")
                continue

            # Duplicate detection across current job.
            if used_question_stems is not None:
                is_dup, sim = is_duplicate_question(q_output.question, used_question_stems)
                if is_dup:
                    logger.warning(
                        "generate_essay: DUPLICATE detected (sim=%.2f) q=%r — skipping",
                        sim, q_output.question[:80],
                    )
                    continue

            # Triviality guard (essays at medium/hard must not be recall-only).
            if should_reject_trivial(q_output.question, difficulty, bloom):
                logger.warning(
                    "generate_essay: TRIVIAL for %s/%s — skipping q=%r",
                    difficulty, bloom, q_output.question[:80],
                )
                continue

            # ── Diversity checks: fingerprint + embedding ──────────────────
            es_fp = self._diversity_svc.compute_fingerprint(q_output.question)
            try:
                es_emb = await self._diversity_svc.compute_embedding(q_output.question)
            except Exception as _emb_exc:
                logger.warning(
                    "generate_essay: embedding failed (%s) — diversity checks skipped",
                    _emb_exc,
                )
                es_emb = []

            if diversity_ctx is not None and es_emb:
                _bl, _bl_reason = self._diversity_svc.is_blacklisted(
                    q_output.question, es_emb, diversity_ctx
                )
                if _bl:
                    diversity_ctx.blacklist_avoided += 1
                    logger.warning(
                        "generate_essay: BLACKLISTED (%s) q=%r — skipping",
                        _bl_reason, q_output.question[:80],
                    )
                    continue
                _rd, _rd_reason = self._diversity_svc.is_recent_duplicate(
                    q_output.question, es_emb, diversity_ctx
                )
                if _rd:
                    diversity_ctx.dedup_avoided += 1
                    logger.warning(
                        "generate_essay: RECENT_DUPLICATE (%s) q=%r — skipping",
                        _rd_reason, q_output.question[:80],
                    )
                    continue

            try:
                question = await self._persist_essay_question(
                    db,
                    q_output=q_output,
                    question_set_id=question_set_id,
                    difficulty=difficulty,
                    chunks=chunks,
                    fingerprint=es_fp,
                    embedding=es_emb if es_emb else None,
                    generation_run_id=question_set_id,
                )
                saved.append(question)
                if used_question_stems is not None:
                    used_question_stems.append(q_output.question)
                await self._run_validators(db, question, is_mcq=False,
                                           target_difficulty=difficulty, target_bloom=bloom)
                if len(saved) >= count:
                    break  # LLM over-produced; stop persisting beyond requested count
            except Exception as exc:
                logger.error(
                    "generate_essay: failed to persist question=%r: %s",
                    q_output.question[:60], exc, exc_info=True,
                )
                continue

        logger.info(
            "generate_essay: saved %d/%d essay question(s) for course=%s topic=%r",
            len(saved), len(output.questions), course_id, topic_name,
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
        fingerprint: str | None = None,
        embedding: list[float] | None = None,
        generation_run_id: uuid.UUID | None = None,
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
            fingerprint=fingerprint,
            embedding=embedding,
            generation_run_id=generation_run_id,
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
        fingerprint: str | None = None,
        embedding: list[float] | None = None,
        generation_run_id: uuid.UUID | None = None,
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
            fingerprint=fingerprint,
            embedding=embedding,
            generation_run_id=generation_run_id,
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

    async def _persist_sa_question(
        self,
        db: AsyncSession,
        *,
        q_output: ShortAnswerQuestionOutput,
        question_set_id: uuid.UUID,
        difficulty: str,
        chunks: list[RetrievedChunk],
        fingerprint: str | None = None,
        embedding: list[float] | None = None,
        generation_run_id: uuid.UUID | None = None,
    ) -> Question:
        """
        Insert one Short Answer Question row and its QuestionSource rows.

        Storage conventions:
          body           — the question text shown to the student
          correct_answer — the model answer (1–3 sentences)
          explanation    — key grading points joined with "; "
        """
        try:
            difficulty_enum = Difficulty(difficulty.lower())
        except ValueError:
            logger.warning(
                "_persist_sa_question: unknown difficulty %r, defaulting to medium",
                difficulty,
            )
            difficulty_enum = Difficulty.medium

        # Join key_points list into a readable grading rubric string.
        explanation = (
            "; ".join(q_output.key_points)
            if q_output.key_points
            else None
        )

        question = Question(
            id=uuid.uuid4(),
            question_set_id=question_set_id,
            type=QuestionType.short_answer,
            body=q_output.question,
            correct_answer=q_output.model_answer,
            explanation=explanation,
            difficulty=difficulty_enum,
            status=QuestionStatus.draft,
            model_name=self._provider.provider_name,
            prompt_version=SA_PROMPT_VERSION,
            insufficient_context=False,
            fingerprint=fingerprint,
            embedding=embedding,
            generation_run_id=generation_run_id,
        )
        db.add(question)
        await db.flush()

        await self._persist_sources(
            db,
            question=question,
            source_hint=q_output.source_hint,
            chunks=chunks,
        )

        return question

    async def _persist_essay_question(
        self,
        db: AsyncSession,
        *,
        q_output: EssayQuestionOutput,
        question_set_id: uuid.UUID,
        difficulty: str,
        chunks: list[RetrievedChunk],
        fingerprint: str | None = None,
        embedding: list[float] | None = None,
        generation_run_id: uuid.UUID | None = None,
    ) -> Question:
        """
        Insert one Essay Question row and its QuestionSource rows.

        Storage conventions:
          body           — the essay prompt shown to the student
          correct_answer — the model outline (ideal answer structure)
          explanation    — student guidance; if absent, rubric criteria joined
        """
        try:
            difficulty_enum = Difficulty(difficulty.lower())
        except ValueError:
            logger.warning(
                "_persist_essay_question: unknown difficulty %r, defaulting to medium",
                difficulty,
            )
            difficulty_enum = Difficulty.medium

        # Build explanation: prefer guidance; fall back to rubric summary.
        if q_output.guidance and q_output.guidance.strip():
            explanation = q_output.guidance
        elif q_output.rubric:
            explanation = "; ".join(
                f"{r.criterion} ({r.max_points} pts): {r.description}"
                for r in q_output.rubric
            )
        else:
            explanation = None

        question = Question(
            id=uuid.uuid4(),
            question_set_id=question_set_id,
            type=QuestionType.essay,
            body=q_output.question,
            correct_answer=q_output.model_outline,
            explanation=explanation,
            difficulty=difficulty_enum,
            status=QuestionStatus.draft,
            model_name=self._provider.provider_name,
            prompt_version=ESSAY_PROMPT_VERSION,
            insufficient_context=False,
            fingerprint=fingerprint,
            embedding=embedding,
            generation_run_id=generation_run_id,
        )
        db.add(question)
        await db.flush()

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
    def _derive_bloom_target(difficulty: str) -> str:
        """Return the default Bloom target for *difficulty*."""
        return DEFAULT_BLOOM_FOR_DIFFICULTY.get(difficulty.lower(), "apply")

    @staticmethod
    def _build_non_triviality_block(difficulty: str, bloom: str) -> str:
        """
        Return an instruction paragraph injected into the prompt instructing the
        model to avoid trivial recall questions.

        Returns an empty string for EASY/REMEMBER slots so the prompt is not
        cluttered with unnecessary constraints for straightforward recall.
        """
        if difficulty.lower() == "easy" or bloom.lower() == "remember":
            return ""
        bloom_verbs: dict[str, str] = {
            "understand": "explain in their own words or give a concrete example,",
            "apply":     "apply a rule, procedure, or theorem to a new scenario,",
            "analyze":   "analyse relationships, identify implicit properties, or compare cases,",
            "evaluate":  "evaluate or critique a claim using criteria from the material,",
            "create":    "synthesise or construct a new artifact/proof from provided building blocks,",
        }
        task_desc = bloom_verbs.get(bloom.lower(), "reason and apply knowledge from the context,")
        return (
            f"Non-triviality requirement (difficulty={difficulty.upper()}, "
            f"bloom={bloom.upper()}):\n"
            f"  - Do NOT ask 'What is X?', 'Define X', or 'What does X mean?'.\n"
            f"  - The question MUST require the student to {task_desc}\n"
            f"  - Include a concrete cognitive task: evaluate a claim, apply a theorem,\n"
            f"    identify an error, determine which property holds, or reason from premises.\n"
            f"  - If you can only produce a trivial definition question from the context,\n"
            f"    set insufficient_context to true instead."
        )

    @staticmethod
    def _build_mcq_stem_hints(difficulty: str) -> str:
        """
        Return MCQ stem type suggestions for MEDIUM/HARD slots so the model
        gravitates towards application-style questions.
        """
        if difficulty.lower() == "easy":
            return ""
        return (
            "Preferred MCQ stem patterns for this difficulty:\n"
            "  \u2022 \"Which of the following is equivalent to …?\"\n"
            "  \u2022 \"Which statement must be true given …?\"\n"
            "  \u2022 \"Which inference is valid/invalid and why?\"\n"
            "  \u2022 \"Which property does X satisfy according to the material?\"\n"
            "  \u2022 \"What is the next step in this proof/computation?\"\n"
            "  \u2022 \"Which of the following correctly applies … to this case?\""
        )

    @staticmethod
    def _build_mcq_prompt(
        *,
        context: str,
        topic: str,
        difficulty: str,
        count: int,
        target_bloom: str = "apply",
    ) -> str:
        """
        Combine the MCQ system message and formatted user message into a
        single prompt string accepted by BaseLLMProvider.generate_json().
        """
        non_trivial_block = QuestionGenerationService._build_non_triviality_block(
            difficulty, target_bloom
        )
        stem_hints = QuestionGenerationService._build_mcq_stem_hints(difficulty)
        user_section = MCQ_GENERATION_USER.format(
            context=context,
            topic=topic,
            difficulty=difficulty,
            count=count,
            target_bloom=target_bloom,
            non_triviality_block=non_trivial_block,
            stem_type_hints=stem_hints,
        )
        return f"{MCQ_GENERATION_SYSTEM}\n---\n{user_section}"

    @staticmethod
    def _build_tf_prompt(
        *,
        context: str,
        topic: str,
        difficulty: str,
        count: int,
        target_bloom: str = "apply",
    ) -> str:
        """Combine the TF system + user messages into a single prompt string."""
        non_trivial_block = QuestionGenerationService._build_non_triviality_block(
            difficulty, target_bloom
        )
        user_section = TF_GENERATION_USER.format(
            context=context,
            topic=topic,
            difficulty=difficulty,
            count=count,
            target_bloom=target_bloom,
            non_triviality_block=non_trivial_block,
        )
        return f"{TF_GENERATION_SYSTEM}\n---\n{user_section}"

    @staticmethod
    def _build_essay_prompt(
        *,
        context: str,
        topic: str,
        difficulty: str,
        count: int,
        target_bloom: str = "analyze",
    ) -> str:
        """Combine the Essay system + user messages into a single prompt string."""
        _response_length_map = {
            "easy":   "200–300 words",
            "medium": "400–600 words",
            "hard":   "600–900 words",
        }
        response_length = _response_length_map.get(difficulty.lower(), "400–600 words")
        non_trivial_block = QuestionGenerationService._build_non_triviality_block(
            difficulty, target_bloom
        )
        user_section = ESSAY_GENERATION_USER.format(
            context=context,
            topic=topic,
            difficulty=difficulty,
            count=count,
            target_bloom=target_bloom,
            response_length=response_length,
            non_triviality_block=non_trivial_block,
        )
        return f"{ESSAY_GENERATION_SYSTEM}\n---\n{user_section}"
