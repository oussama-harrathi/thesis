"""
Document routes.

GET    /api/v1/courses/{course_id}/documents      → list documents for a course
POST   /api/v1/courses/{course_id}/documents      → upload PDF
DELETE /api/v1/documents/{document_id}            → delete document + file
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.document import DocumentResponse, DocumentUploadResponse
from app.services.course_service import CourseService
from app.services.document_ingestion_service import DocumentIngestionService

router = APIRouter(tags=["documents"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its file",
)
async def delete_document(
    document_id: uuid.UUID,
    db: DbSession,
) -> None:
    svc = DocumentIngestionService(db)
    deleted = await svc.delete(document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found.",
        )


@router.get(
    "/courses/{course_id}/documents",
    response_model=list[DocumentResponse],
    summary="List documents for a course",
)
async def list_documents(
    course_id: uuid.UUID,
    db: DbSession,
) -> list[DocumentResponse]:
    """Return all documents uploaded to a course, newest first."""
    course_svc = CourseService(db)
    if await course_svc.get_by_id(course_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
    svc = DocumentIngestionService(db)
    docs = await svc.list_by_course(course_id)
    return [DocumentResponse.model_validate(d) for d in docs]


@router.post(
    "/courses/{course_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF document to a course",
)
async def upload_document(
    course_id: uuid.UUID,
    file: UploadFile,
    db: DbSession,
) -> DocumentUploadResponse:
    """
    Upload a PDF file to a course.

    - Validates that the course exists (404 if not).
    - Accepts only `application/pdf` (415 if wrong type).
    - Enforces MAX_UPLOAD_SIZE_MB size limit (413 if too large).
    - Saves file to `UPLOAD_DIR`, creates a Document (status=pending)
      and a Job (type=document_processing, status=pending).
    - Does **not** process the PDF — that happens in Phase 4.
    """
    # 1. Verify course exists
    course_svc = CourseService(db)
    course = await course_svc.get_by_id(course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )

    # 2. Read bytes (with size guard)
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit "
                f"({len(file_bytes) / 1_048_576:.1f} MB received)."
            ),
        )

    # 3. Ingest (validate mime → save → create rows)
    content_type = file.content_type or ""
    original_filename = file.filename or "upload.pdf"

    ingest_svc = DocumentIngestionService(db)
    try:
        document, job, checksum = await ingest_svc.ingest_upload(
            course_id=course_id,
            original_filename=original_filename,
            content_type=content_type,
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )

    return DocumentUploadResponse(
        document=DocumentResponse.model_validate(document),
        job_id=job.id,
        job_status=job.status.value,
        checksum_sha256=checksum,
    )
