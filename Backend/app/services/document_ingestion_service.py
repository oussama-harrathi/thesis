"""
DocumentIngestionService — handles PDF upload, persistence, and job creation.

Responsibilities:
1. Receive raw file bytes + metadata from the route handler.
2. Compute SHA-256 checksum.
3. Build a unique storage filename: {checksum[:12]}_{uuid}.pdf
4. Write file to UPLOAD_DIR (creates directory if needed).
5. Insert Document record (status = pending).
6. Insert Job record (type = document_processing, status = pending).
7. Return (Document, Job, checksum).

No PDF parsing or Celery enqueueing happens here — that is Phase 4.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentStatus
from app.models.job import Job, JobStatus, JobType

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {"application/pdf"}


class DocumentIngestionService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Public entry points ───────────────────────────────────────

    async def list_by_course(self, course_id: uuid.UUID) -> list[Document]:
        """Return all documents for a course, newest first."""
        result = await self._db.execute(
            select(Document)
            .where(Document.course_id == course_id)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def ingest_upload(
        self,
        course_id: uuid.UUID,
        original_filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> tuple[Document, Job, str]:
        """
        Save the file, create DB rows, return (document, job, checksum_hex).

        Raises:
            ValueError: if the MIME type is not accepted.
            OSError:    if the file cannot be written.
        """
        self._validate_mime(content_type, original_filename)

        checksum = self._sha256(file_bytes)
        storage_filename = f"{checksum[:12]}_{uuid.uuid4().hex}.pdf"
        file_path = self._write_file(storage_filename, file_bytes)

        document = await self._create_document(
            course_id=course_id,
            original_filename=original_filename,
            storage_filename=storage_filename,
            file_path=str(file_path),
            file_size=len(file_bytes),
            mime_type=content_type,
        )

        job = await self._create_job(
            document_id=document.id,
            course_id=course_id,
        )

        logger.info(
            "Ingested document id=%s course_id=%s size=%d checksum=%s",
            document.id,
            course_id,
            len(file_bytes),
            checksum,
        )
        return document, job, checksum

    async def delete(self, document_id: uuid.UUID) -> bool:
        """
        Delete a document row and its file from disk.

        Returns True if the document existed and was deleted,
        False if not found.
        """
        doc = await self._db.get(Document, document_id)
        if doc is None:
            return False

        # Remove file from disk (best-effort — don't fail if already gone)
        file_path = Path(doc.file_path)
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info("Deleted file %s", file_path)
        except OSError:
            logger.warning("Could not delete file %s", file_path, exc_info=True)

        await self._db.delete(doc)
        await self._db.flush()
        logger.info("Deleted document id=%s", document_id)
        return True

    # ── Private helpers ───────────────────────────────────────────

    @staticmethod
    def _validate_mime(content_type: str, filename: str) -> None:
        """Reject non-PDF uploads early."""
        if content_type not in ALLOWED_MIME_TYPES:
            raise ValueError(
                f"Unsupported file type '{content_type}'. Only PDF files are accepted."
            )
        if not filename.lower().endswith(".pdf"):
            raise ValueError("Uploaded file must have a .pdf extension.")

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _write_file(storage_filename: str, data: bytes) -> Path:
        """Write bytes to UPLOAD_DIR and return the absolute path."""
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / storage_filename
        dest.write_bytes(data)
        return dest.resolve()

    async def _create_document(
        self,
        *,
        course_id: uuid.UUID,
        original_filename: str,
        storage_filename: str,
        file_path: str,
        file_size: int,
        mime_type: str,
    ) -> Document:
        doc = Document(
            course_id=course_id,
            filename=storage_filename,
            original_filename=original_filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            status=DocumentStatus.pending,
        )
        self._db.add(doc)
        await self._db.flush()
        await self._db.refresh(doc)
        return doc

    async def _create_job(
        self,
        *,
        document_id: uuid.UUID,
        course_id: uuid.UUID,
    ) -> Job:
        job = Job(
            type=JobType.document_processing,
            status=JobStatus.pending,
            document_id=document_id,
            course_id=course_id,
            progress=0,
            message="Waiting to be processed.",
        )
        self._db.add(job)
        await self._db.flush()
        await self._db.refresh(job)
        return job
