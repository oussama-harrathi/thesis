"""
Celery tasks for the Exam Builder worker.

All tasks are bound (bind=True) so they have access to `self` for retries.

Tasks
─────
process_document(document_id, job_id)
    Full Phase 4 pipeline:
    PDF extraction → text cleaning → chunking → embedding → pgvector persist
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
