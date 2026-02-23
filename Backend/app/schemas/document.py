"""
Pydantic v2 schemas for the Document resource.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    filename: str               # storage filename (includes checksum prefix)
    original_filename: str      # original name from the user's upload
    file_path: str
    file_size: int | None
    mime_type: str | None
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    """Returned by POST /courses/{course_id}/documents."""

    document: DocumentResponse
    job_id: uuid.UUID
    job_status: str
    checksum_sha256: str        # computed in memory; stored as part of the filename
