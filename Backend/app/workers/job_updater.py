"""
JobUpdater — thin helper used by Celery workers to update Job + Document rows.

Keeps all DB mutation logic out of the task function bodies.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus
from app.models.job import Job, JobStatus

if TYPE_CHECKING:
    pass


class JobUpdater:
    """Sync helper for updating a Job (and optionally its linked Document)."""

    def __init__(self, session: Session, job_id: uuid.UUID) -> None:
        self._db = session
        self._job_id = job_id

    # ── Convenience methods ───────────────────────────────────────

    def start(self, message: str = "Processing started.") -> None:
        """Mark job running and reset progress to 0."""
        self._update_job(status=JobStatus.running, progress=0, message=message)

    def progress(self, pct: int, message: str) -> None:
        """Update progress percentage (0-100) and message."""
        self._update_job(status=JobStatus.running, progress=pct, message=message)

    def complete(self, message: str = "Done.") -> None:
        """Mark job completed at 100%."""
        self._update_job(status=JobStatus.completed, progress=100, message=message)

    def fail(self, error: str) -> None:
        """Mark job failed and record the error string."""
        self._update_job(status=JobStatus.failed, message="Failed.", error=error)

    def set_document_status(
        self, document_id: uuid.UUID, status: DocumentStatus
    ) -> None:
        """Update the linked Document's processing status."""
        doc = self._db.get(Document, document_id)
        if doc:
            doc.status = status
            self._db.flush()

    # ── Internal ─────────────────────────────────────────────────

    def _update_job(
        self,
        *,
        status: JobStatus,
        progress: int | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        job = self._db.get(Job, self._job_id)
        if job is None:
            return
        job.status = status
        if progress is not None:
            job.progress = progress
        if message is not None:
            job.message = message
        if error is not None:
            job.error = error
        self._db.flush()
