"""
Celery tasks for the Exam Builder worker.

All tasks are bound (bind=True) so they have access to `self` for retries.

Tasks
─────
process_document(document_id, job_id)
    Full Phase 4 pipeline:
    PDF extraction → text cleaning → chunking → embedding → pgvector persist

generate_from_blueprint(blueprint_id, job_id, question_set_id)
    Phase 9 blueprint generation pipeline:
    Expand blueprint config into slots → generate questions per slot →
    update Job progress → mark complete
"""

from __future__ import annotations

import uuid
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.chunk_persistence_service import ChunkPersistenceService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.topic_extraction_service import TopicExtractionService
from app.utils.pdf import extract_pages
from app.utils.text_cleaning import clean_text
from app.workers.celery_app import celery_app
from app.workers.db import get_sync_db
from app.workers.job_updater import JobUpdater

logger = get_task_logger(__name__)


def _get_document(db: Session, doc_id: uuid.UUID) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise ValueError(f"Document {doc_id} not found in database.")
    return doc


# ── process_document ─────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_document",
    max_retries=3,
    default_retry_delay=30,  # seconds between retries
    acks_late=True,
)
def process_document(self: Task, document_id: str, job_id: str) -> dict[str, Any]:
    """
    Background task: process a newly uploaded PDF document.

    Pipeline
    ────────
    1.  Mark job running + document processing
    2.  Load Document row → get file_path
    3.  PDF text extraction  (PyMuPDF)
    4.  Text cleaning
    5.  Chunking with overlap
    6.  Embedding  (SentenceTransformers all-MiniLM-L6-v2)
    7.  Persist Chunk rows + vectors to pgvector
    8.  Mark document completed + job completed

    Topic extraction (Phase 5) is not executed here yet.
    """
    doc_uuid = uuid.UUID(document_id)
    job_uuid = uuid.UUID(job_id)

    logger.info(
        "process_document started | document_id=%s job_id=%s",
        document_id,
        job_id,
    )

    try:
        with get_sync_db() as db:
            updater = JobUpdater(db, job_uuid)

            # ── step 1: mark running ──────────────────────────────
            updater.start("Pipeline starting…")
            updater.set_document_status(doc_uuid, DocumentStatus.processing)
            logger.info("[%s] status → processing", document_id)

            # ── step 2: load document row ─────────────────────────
            doc = _get_document(db, doc_uuid)
            logger.info("[%s] file_path=%s", document_id, doc.file_path)

            # ── step 3: PDF extraction ────────────────────────────
            updater.progress(10, "Extracting text from PDF…")
            extraction = extract_pages(doc.file_path)
            logger.info(
                "[%s] extracted %d pages, ~%d chars",
                document_id, extraction.total_pages, extraction.total_chars,
            )

            # ── step 4: text cleaning ─────────────────────────────
            updater.progress(20, "Cleaning extracted text…")
            cleaned = clean_text(extraction.full_text)
            logger.info("[%s] cleaned text length=%d", document_id, len(cleaned))

            if not cleaned.strip():
                logger.warning(
                    "[%s] No text found after cleaning (scanned/image PDF?)",
                    document_id,
                )

            # ── step 5: chunking ──────────────────────────────────
            updater.progress(40, "Splitting text into chunks…")
            text_chunks = ChunkingService().chunk_document(cleaned, extraction=extraction)
            logger.info("[%s] produced %d chunks", document_id, len(text_chunks))

            # ── step 6: embedding ─────────────────────────────────
            updater.progress(60, "Generating embeddings…")
            vectors: list[list[float]] = []
            emb_svc = EmbeddingService()
            if text_chunks:
                vectors = emb_svc.encode([c.content for c in text_chunks])
                logger.info(
                    "[%s] embedded %d chunks (dim=%d)",
                    document_id, len(vectors), len(vectors[0]) if vectors else 0,
                )

            # ── step 7: persist chunks ────────────────────────────
            updater.progress(80, "Saving chunks to database…")
            if text_chunks:
                ChunkPersistenceService(db).save_chunks(
                    doc_uuid, text_chunks, vectors
                )
            logger.info("[%s] chunks persisted", document_id)

            # ── step 8: topic extraction (Phase 5) ──────────────
            updater.progress(85, "Extracting topics…")
            persisted_chunks: list[Chunk] = list(
                db.execute(
                    select(Chunk).where(Chunk.document_id == doc_uuid)
                ).scalars().all()
            )
            topic_count = 0
            if persisted_chunks:
                topics = TopicExtractionService().save_topics_v2(
                    db,
                    doc.course_id,
                    persisted_chunks,
                    source_path=doc.file_path,
                    embedding_service=emb_svc if text_chunks else None,
                )
                topic_count = len(topics)
                logger.info(
                    "[%s] extracted and saved %d topics",
                    document_id, topic_count,
                )

            # ── step 9: complete ──────────────────────────────────
            updater.set_document_status(doc_uuid, DocumentStatus.completed)
            updater.complete(
                f"Done. {len(text_chunks)} chunks, {topic_count} topics stored."
            )
            logger.info("[%s] Completed successfully", document_id)

    except Exception as exc:
        logger.exception(
            "process_document failed | document_id=%s job_id=%s error=%s",
            document_id,
            job_id,
            exc,
        )
        # Best-effort: mark failed in a fresh session
        try:
            with get_sync_db() as db:
                updater = JobUpdater(db, job_uuid)
                updater.fail(str(exc))
                updater.set_document_status(doc_uuid, DocumentStatus.failed)
        except Exception:
            logger.exception("Could not write failure status to DB")

        # Retry with exponential back-off
        raise self.retry(exc=exc)

    return {"document_id": document_id, "job_id": job_id, "status": "completed"}


# ── generate_from_blueprint ───────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.workers.tasks.generate_from_blueprint",
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def generate_from_blueprint(
    self: Task,
    blueprint_id: str,
    job_id: str,
    question_set_id: str,
) -> dict[str, Any]:
    """
    Background task: generate questions from an exam blueprint.

    Pipeline
    ────────
    1.  Load ExamBlueprint and parse config_json (sync DB).
    2.  Expand config into ordered GenerationSlots (pure Python).
    3.  For each slot, call the async QuestionGenerationService
        (MCQ and TF implemented; Short-Answer / Essay skipped with a warning).
    4.  Update Job progress after every slot.
    5.  Mark Job completed (or failed on error).

    Runs the async generation loop via ``asyncio.run()``; the outer try/except
    converts failures to Celery retries and writes the ``failed`` status.
    """
    import asyncio
    import json as _json

    bp_uuid = uuid.UUID(blueprint_id)
    job_uuid = uuid.UUID(job_id)
    qs_uuid = uuid.UUID(question_set_id)

    logger.info(
        "generate_from_blueprint started | blueprint=%s job=%s question_set=%s",
        blueprint_id,
        job_id,
        question_set_id,
    )

    # ── Step 1: load blueprint config (sync) ──────────────────────────
    with get_sync_db() as db:
        from app.models.exam import ExamBlueprint
        from app.models.job import Job, JobStatus

        blueprint = db.get(ExamBlueprint, bp_uuid)
        if blueprint is None:
            # Fail immediately — no point retrying a missing blueprint.
            job = db.get(Job, job_uuid)
            if job:
                job.status = JobStatus.failed
                job.error = f"Blueprint {blueprint_id} not found."
                db.flush()
            return {"status": "failed", "error": "blueprint not found"}

        config_json_str: str = blueprint.config_json
        course_id: uuid.UUID = blueprint.course_id

    # ── Step 2: expand into slots (pure Python, no DB) ────────────────
    from app.schemas.blueprint import BlueprintConfig
    from app.services.blueprint_service import BlueprintService, GenerationSlot

    config = BlueprintConfig.model_validate(_json.loads(config_json_str))
    slots: list[GenerationSlot] = BlueprintService.expand_to_slots(config)

    logger.info(
        "generate_from_blueprint: expanded %d slot(s) for blueprint=%s",
        len(slots),
        blueprint_id,
    )

    if not slots:
        with get_sync_db() as db:
            from app.models.job import Job, JobStatus

            updater = JobUpdater(db, job_uuid)
            updater.complete("Blueprint has zero questions to generate.")
        return {"status": "completed", "generated": 0}

    # ── Steps 3–5: async generation of all slots ──────────────────────

    # Query suffix per question type: makes retrieval pull different chunks
    # for different cognitive tasks even when the topic name is identical.
    _SLOT_QUERY_SUFFIXES: dict[str, str] = {
        "mcq":          "definition concept example explain property",
        "true_false":   "fact statement property rule characteristic",
        "short_answer": "how why describe steps process mechanism",
        "essay":        "discuss compare analyze relationship impact",
    }

    def _build_slot_query(topic_name: str, q_type_value: str) -> str:
        suffix = _SLOT_QUERY_SUFFIXES.get(q_type_value, "")
        # When the topic name is the synthetic fallback "General" it adds no
        # semantic information — prepending it skews the embedding toward generic
        # boilerplate text and starves the retrieval of real instructional chunks.
        # Use only the type-specific suffix for the vector search in that case.
        effective_topic = "" if topic_name.strip().lower() == "general" else topic_name
        return f"{effective_topic} {suffix}".strip() or topic_name

    # Maximum LLM attempts per individual question before marking it failed.
    MAX_SLOT_ATTEMPTS = 3

    async def _run_generation() -> dict[str, Any]:
        """
        Async inner function: runs inside asyncio.run().

        Expands each slot's count into individual 1-question attempts, retrying
        up to MAX_SLOT_ATTEMPTS times per question.  Returns a summary dict.

        Returns
        -------
        dict with keys: requested, generated, failed, failure_reasons
        """
        from app.core.database import async_session_factory
        from app.models.job import Job, JobStatus
        from app.models.question import QuestionType
        from app.services.diversity_service import DiversityContext, DiversityService
        from app.services.question_generation_service import QuestionGenerationService
        from app.utils.chunk_filter import DEFAULT_BLOOM_FOR_DIFFICULTY, is_trivial_question

        svc = QuestionGenerationService()
        diversity_svc = DiversityService()

        # ── Generate a per-run seed from job UUID ───────────────────────────
        # The seed changes every run (job UUID is unique) so chunk selection
        # and slot ordering vary across repeated blueprint runs.
        generation_seed: int = job_uuid.int & 0xFFFF_FFFF
        logger.info(
            "generate_from_blueprint: generation_seed=%d for job=%s",
            generation_seed, job_id,
        )

        # ── Load diversity context + historical chunk IDs (once per run) ─────
        diversity_ctx: DiversityContext
        penalize_chunk_ids: set[uuid.UUID]
        async with async_session_factory() as db:
            diversity_ctx = await diversity_svc.load_context(
                db, course_id=course_id, recent_limit=100
            )
            penalize_chunk_ids = await diversity_svc.load_recent_chunk_ids(
                db, course_id=course_id, limit=200
            )
        logger.info(
            "generate_from_blueprint: diversity loaded — blacklist=%d recent=%d penalize_chunks=%d",
            len(diversity_ctx.blacklist_fingerprints),
            len(diversity_ctx.recent_fingerprints),
            len(penalize_chunk_ids),
        )

        # ── Job-level diversity state ─────────────────────────────────
        # chunk IDs used across ALL slots; passed to retrieval to avoid reuse.
        used_chunk_ids: set[uuid.UUID] = set()
        # Question stems/texts generated so far; used for duplicate detection.
        used_question_stems: list[str] = []
        # Per-slot diagnostics stored in job metadata.
        slot_diagnostics: list[dict[str, Any]] = []
        # Trivial fraction guard: if trivial questions exceed this share of
        # all generated questions, subsequent medium/hard slots get their
        # Bloom target overridden to ANALYZE to force application questions.
        TRIVIAL_FRACTION_LIMIT: float = 0.30

        # Build a flat list of individual question specs (count=1 each).
        individual_items: list[dict[str, Any]] = []
        for slot in slots:
            for _ in range(slot.count):
                individual_items.append({
                    "question_type": slot.question_type,
                    "difficulty": slot.difficulty,
                    "topic_id": slot.topic_id,
                    "topic_name": slot.topic_name,
                })

        # ── Seeded shuffle for cross-run slot order diversity ─────────────
        # Randomising slot order changes which topic/chunks get retrieved first,
        # which in turn shifts what the accumulating exclude_chunk_ids set
        # blocks in later slots — producing meaningfully different questions.
        import random as _rnd_slots
        _rng_slots = _rnd_slots.Random(generation_seed)
        _rng_slots.shuffle(individual_items)
        logger.info(
            "generate_from_blueprint: shuffled %d item(s) with seed=%d",
            len(individual_items), generation_seed,
        )

        total_requested = len(individual_items)
        total_generated = 0
        failed_count = 0
        failure_reasons: list[str] = []

        logger.info(
            "generate_from_blueprint: %d slot(s) → %d individual question(s) to generate",
            len(slots),
            total_requested,
        )

        async with async_session_factory() as db:
            job = await db.get(Job, job_uuid)
            if job:
                job.status = JobStatus.running
                job.progress = 0
                job.message = f"Generating {total_requested} question(s)…"
                await db.flush()
                await db.commit()

        for item_idx, item in enumerate(individual_items):
            q_type: QuestionType = item["question_type"]
            difficulty_enum = item["difficulty"]
            topic_id = item["topic_id"]
            topic_name = item["topic_name"]
            diff_str = difficulty_enum.value

            item_label = (
                f"[{item_idx + 1}/{total_requested}] "
                f"type={q_type.value} diff={diff_str} topic={topic_name!r}"
            )

            slot_retrieval_query = _build_slot_query(topic_name, q_type.value)

            # Chunks retrieved in failed attempts within this slot — excluded on
            # subsequent retries so the LLM always gets a fresh context window.
            retry_exclude_chunk_ids: set[uuid.UUID] = set()

            # Derive Bloom target for this slot.
            base_bloom = DEFAULT_BLOOM_FOR_DIFFICULTY.get(diff_str, "apply")

            # Distribution guard: if too many trivial questions have been
            # generated so far, override Bloom to ANALYZE for non-easy slots.
            if diff_str != "easy" and used_question_stems:
                trivial_in_job = sum(
                    1 for s in used_question_stems if is_trivial_question(s)
                )
                trivial_ratio = trivial_in_job / len(used_question_stems)
                if trivial_ratio > TRIVIAL_FRACTION_LIMIT:
                    base_bloom = "analyze"
                    logger.info(
                        "generate_from_blueprint: trivial ratio=%.0f%% > limit=%.0f%% — "
                        "overriding bloom to ANALYZE for %s",
                        trivial_ratio * 100, TRIVIAL_FRACTION_LIMIT * 100, item_label,
                    )

            generated_this = False
            last_failure = "unknown"

            for attempt in range(1, MAX_SLOT_ATTEMPTS + 1):
                # Reset per-attempt chunk accumulator so each retry starts clean.
                chunk_ids_this_slot: list[uuid.UUID] = []

                # Vary the seed per-attempt so retrieval tie-breaking shuffles
                # differently and doesn't keep surfacing the same top chunks.
                attempt_seed = generation_seed ^ (attempt * 0x9E3779B9)

                # Combine job-level used chunks with this slot's retry-poisoned chunks.
                effective_exclude = used_chunk_ids | retry_exclude_chunk_ids

                logger.info(
                    "generate_from_blueprint: %s — attempt %d/%d "
                    "(retry_excluded=%d)",
                    item_label, attempt, MAX_SLOT_ATTEMPTS,
                    len(retry_exclude_chunk_ids),
                )

                async with async_session_factory() as db:
                    try:
                        if q_type == QuestionType.mcq:
                            generated = await svc.generate_mcq(
                                db,
                                question_set_id=qs_uuid,
                                course_id=course_id,
                                topic_id=topic_id,
                                topic_name=topic_name,
                                difficulty=diff_str,
                                count=1,
                                retrieval_query=slot_retrieval_query,
                                exclude_chunk_ids=effective_exclude,
                                _out_chunk_ids=chunk_ids_this_slot,
                                used_question_stems=used_question_stems,
                                target_bloom=base_bloom,
                                diversity_ctx=diversity_ctx,
                                generation_seed=attempt_seed,
                                penalize_chunk_ids=penalize_chunk_ids,
                            )
                        elif q_type == QuestionType.true_false:
                            generated = await svc.generate_true_false(
                                db,
                                question_set_id=qs_uuid,
                                course_id=course_id,
                                topic_id=topic_id,
                                topic_name=topic_name,
                                difficulty=diff_str,
                                count=1,
                                retrieval_query=slot_retrieval_query,
                                exclude_chunk_ids=effective_exclude,
                                _out_chunk_ids=chunk_ids_this_slot,
                                used_question_stems=used_question_stems,
                                target_bloom=base_bloom,
                                diversity_ctx=diversity_ctx,
                                generation_seed=attempt_seed,
                                penalize_chunk_ids=penalize_chunk_ids,
                            )
                        elif q_type == QuestionType.short_answer:
                            generated = await svc.generate_short_answer(
                                db,
                                question_set_id=qs_uuid,
                                course_id=course_id,
                                topic_id=topic_id,
                                topic_name=topic_name,
                                difficulty=diff_str,
                                count=1,
                                retrieval_query=slot_retrieval_query,
                                exclude_chunk_ids=effective_exclude,
                                _out_chunk_ids=chunk_ids_this_slot,
                                used_question_stems=used_question_stems,
                                target_bloom=base_bloom,
                                diversity_ctx=diversity_ctx,
                                generation_seed=attempt_seed,
                                penalize_chunk_ids=penalize_chunk_ids,
                            )
                        elif q_type == QuestionType.essay:
                            generated = await svc.generate_essay(
                                db,
                                question_set_id=qs_uuid,
                                course_id=course_id,
                                topic_id=topic_id,
                                topic_name=topic_name,
                                difficulty=diff_str,
                                count=1,
                                retrieval_query=slot_retrieval_query,
                                exclude_chunk_ids=effective_exclude,
                                _out_chunk_ids=chunk_ids_this_slot,
                                used_question_stems=used_question_stems,
                                target_bloom=base_bloom,
                                diversity_ctx=diversity_ctx,
                                generation_seed=attempt_seed,
                                penalize_chunk_ids=penalize_chunk_ids,
                            )
                        else:
                            logger.warning(
                                "generate_from_blueprint: unimplemented type %r — skipping %s",
                                q_type.value,
                                item_label,
                            )
                            last_failure = f"type {q_type.value!r} not implemented"
                            break

                        if generated:
                            # Each blueprint slot is exactly 1 question.
                            # The LLM may occasionally return more (over-generation);
                            # cap to 1 so requested==generated counts stay consistent.
                            generated = generated[:1]
                            total_generated += len(generated)
                            generated_this = True
                            # Register chunks as used so subsequent slots pull different material.
                            used_chunk_ids.update(chunk_ids_this_slot)

                            # Insert blueprint_questions mapping rows for each generated question.
                            try:
                                from app.models.exam import BlueprintQuestion as _BPQ
                                for _q in generated:
                                    _bpq = _BPQ(
                                        blueprint_id=bp_uuid,
                                        question_id=_q.id,
                                    )
                                    db.add(_bpq)
                                    await db.flush()
                            except Exception as _bpq_exc:
                                logger.warning(
                                    "generate_from_blueprint: blueprint_questions insert failed for %s: %s",
                                    item_label, _bpq_exc,
                                )

                            await db.commit()
                            logger.info(
                                "generate_from_blueprint: %s — OK on attempt %d "
                                "(used_chunks=%d chunk_ids=%s)",
                                item_label, attempt,
                                len(used_chunk_ids),
                                [str(c)[:8] for c in chunk_ids_this_slot],
                            )
                            break
                        else:
                            last_failure = "generation returned 0 questions (context insufficient or LLM refusal)"
                            logger.warning(
                                "generate_from_blueprint: %s — attempt %d returned 0 (will %s)",
                                item_label, attempt,
                                "retry" if attempt < MAX_SLOT_ATTEMPTS else "give up",
                            )
                            # Poison the retrieved chunks for this failed attempt so
                            # the next retry fetches a completely different context.
                            retry_exclude_chunk_ids.update(chunk_ids_this_slot)
                            await db.rollback()

                    except Exception as exc:
                        last_failure = f"{type(exc).__name__}: {exc}"
                        logger.error(
                            "generate_from_blueprint: %s — attempt %d raised %s",
                            item_label, attempt, exc, exc_info=True,
                        )
                        await db.rollback()

            if not generated_this:
                failed_count += 1
                failure_reasons.append(f"{item_label}: {last_failure}")
                logger.error(
                    "generate_from_blueprint: %s — FAILED after %d attempts: %s",
                    item_label, MAX_SLOT_ATTEMPTS, last_failure,
                )

            # Record per-slot diagnostic.
            slot_diagnostics.append({
                "slot": item_idx + 1,
                "type": q_type.value,
                "topic": topic_name,
                "diff": diff_str,
                "bloom": base_bloom,
                "retrieval_query": slot_retrieval_query,
                "chunk_ids": [str(c) for c in chunk_ids_this_slot],
                "success": generated_this,
            })

            # Update job progress after each question.
            progress = int((item_idx + 1) / total_requested * 90)
            async with async_session_factory() as db:
                job = await db.get(Job, job_uuid)
                if job:
                    job.progress = progress
                    job.message = (
                        f"{item_idx + 1}/{total_requested} questions attempted — "
                        f"{total_generated} OK, {failed_count} failed."
                    )
                    await db.flush()
                    await db.commit()

        # Build final job summary.
        import json as _json2
        trivial_in_job = sum(1 for s in used_question_stems if is_trivial_question(s))
        summary = {
            "requested": total_requested,
            "generated": total_generated,
            "failed": failed_count,
            "failure_reasons": failure_reasons[:20],
            "unique_chunks_used": len(used_chunk_ids),
            "trivial_questions": trivial_in_job,
            "trivial_fraction": round(trivial_in_job / max(total_generated, 1), 2),
            # Diversity / rejection-memory stats
            "generation_seed": generation_seed,
            "blacklist_avoided": diversity_ctx.blacklist_avoided,
            "cross_run_dedup_avoided": diversity_ctx.dedup_avoided,
            "historical_chunks_penalized": len(penalize_chunk_ids),
            "slots": slot_diagnostics,
        }
        is_partial = total_generated < total_requested
        final_message = (
            f"{'PARTIAL — ' if is_partial else ''}Generated {total_generated}/{total_requested} question(s)."
        )

        async with async_session_factory() as db:
            job = await db.get(Job, job_uuid)
            if job:
                job.status = JobStatus.completed
                job.progress = 100
                job.message = final_message[:500]
                # Store full summary in error field (Text column) when partial.
                if is_partial or failure_reasons:
                    job.error = _json2.dumps(summary, default=str)
                await db.flush()
                await db.commit()

        logger.info(
            "generate_from_blueprint: DONE — requested=%d generated=%d failed=%d blueprint=%s",
            total_requested, total_generated, failed_count, blueprint_id,
        )
        return summary

    try:
        # Dispose the async engine's connection pool before creating a new event
        # loop.  asyncio.run() creates a fresh loop each call; asyncpg connections
        # are bound to the loop they were created on.  Disposing flushes all
        # pooled connections so new ones are opened in the correct loop context.
        from app.core.database import engine as _db_engine  # noqa: PLC0415
        _db_engine.sync_engine.dispose()  # sync-safe: flushes asyncpg pool before new event loop

        summary = asyncio.run(_run_generation())
        n_generated = summary["generated"]
        n_requested = summary["requested"]
        n_failed = summary["failed"]
    except Exception as exc:
        n_generated = 0
        n_requested = sum(s.count for s in slots)
        n_failed = n_requested
        logger.exception(
            "generate_from_blueprint failed | blueprint=%s job=%s error=%s",
            blueprint_id,
            job_id,
            exc,
        )
        try:
            with get_sync_db() as db:
                updater = JobUpdater(db, job_uuid)
                updater.fail(str(exc))
        except Exception:
            logger.exception("Could not write failure status for job=%s", job_id)

        raise self.retry(exc=exc)

    logger.info(
        "generate_from_blueprint completed | blueprint=%s requested=%d generated=%d failed=%d",
        blueprint_id,
        n_requested,
        n_generated,
        n_failed,
    )
    return {
        "blueprint_id": blueprint_id,
        "job_id": job_id,
        "question_set_id": question_set_id,
        "requested": n_requested,
        "generated": n_generated,
        "failed": n_failed,
        "status": "completed" if n_failed == 0 else "partial",
    }
