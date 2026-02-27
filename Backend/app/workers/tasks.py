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
            if text_chunks:
                emb_svc = EmbeddingService()
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
                topics = TopicExtractionService().save_topics(
                    db, doc.course_id, persisted_chunks
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

    async def _run_generation() -> int:
        """
        Async inner function: runs inside asyncio.run().

        Uses the async SQLAlchemy session factory directly so we can pass the
        session to QuestionGenerationService (which is fully async).

        Returns the total number of persisted Question rows.
        """
        from app.core.database import async_session_factory
        from app.models.job import Job, JobStatus
        from app.models.question import QuestionType
        from app.services.question_generation_service import QuestionGenerationService

        svc = QuestionGenerationService()
        total_slots = len(slots)
        total_generated = 0

        async with async_session_factory() as db:
            # Mark job running.
            job = await db.get(Job, job_uuid)
            if job:
                job.status = JobStatus.running
                job.progress = 0
                job.message = f"Generating questions from {total_slots} slot(s)…"
                await db.flush()
                await db.commit()

        for slot_idx, slot in enumerate(slots):
            slot_label = (
                f"{slot.question_type.value}/{slot.difficulty.value}/"
                f"{slot.topic_name!r} x{slot.count}"
            )
            logger.info(
                "generate_from_blueprint: slot %d/%d — %s",
                slot_idx + 1,
                total_slots,
                slot_label,
            )

            async with async_session_factory() as db:
                try:
                    if slot.question_type == QuestionType.mcq:
                        generated = await svc.generate_mcq(
                            db,
                            question_set_id=qs_uuid,
                            course_id=course_id,
                            topic_id=slot.topic_id,
                            topic_name=slot.topic_name,
                            difficulty=slot.difficulty.value,
                            count=slot.count,
                        )
                    elif slot.question_type == QuestionType.true_false:
                        generated = await svc.generate_true_false(
                            db,
                            question_set_id=qs_uuid,
                            course_id=course_id,
                            topic_id=slot.topic_id,
                            topic_name=slot.topic_name,
                            difficulty=slot.difficulty.value,
                            count=slot.count,
                        )
                    else:
                        logger.warning(
                            "generate_from_blueprint: skipping unimplemented "
                            "question type %r (slot %d)",
                            slot.question_type.value,
                            slot_idx + 1,
                        )
                        generated = []

                    total_generated += len(generated)
                    await db.commit()

                except Exception as slot_exc:
                    logger.error(
                        "generate_from_blueprint: slot %d failed (%s): %s",
                        slot_idx + 1,
                        slot_label,
                        slot_exc,
                        exc_info=True,
                    )
                    await db.rollback()
                    # Continue with remaining slots.

            # Update progress (slot progress fills 0–90%; final 10% on complete).
            progress = int((slot_idx + 1) / total_slots * 90)
            async with async_session_factory() as db:
                job = await db.get(Job, job_uuid)
                if job:
                    job.progress = progress
                    job.message = (
                        f"Slot {slot_idx + 1}/{total_slots} done — "
                        f"{total_generated} questions generated so far."
                    )
                    await db.flush()
                    await db.commit()

        # Mark job complete.
        async with async_session_factory() as db:
            job = await db.get(Job, job_uuid)
            if job:
                job.status = JobStatus.completed
                job.progress = 100
                job.message = (
                    f"Completed: {total_generated} question(s) generated "
                    f"from {total_slots} slot(s)."
                )
                await db.flush()
                await db.commit()

        return total_generated

    try:
        n_generated = asyncio.run(_run_generation())
    except Exception as exc:
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
        "generate_from_blueprint completed | blueprint=%s generated=%d",
        blueprint_id,
        n_generated,
    )
    return {
        "blueprint_id": blueprint_id,
        "job_id": job_id,
        "question_set_id": question_set_id,
        "generated": n_generated,
        "status": "completed",
    }
