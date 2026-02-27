"""
Pydantic v2 schemas for the Export resource.

Request schemas:
  ExportExamRequest    – body for POST /api/v1/exams/{exam_id}/export

Response schemas:
  ExportResponse       – single export record
  ExportListResponse   – list of export records for an exam
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.export import ExportStatus, ExportType


# ── Request ───────────────────────────────────────────────────────────────────


class ExportExamRequest(BaseModel):
    """
    Body for POST /api/v1/exams/{exam_id}/export.

    Currently accepts no fields — both exam and answer-key are always
    generated together.  Reserved for future per-type selection.
    """

    pass


# ── Response ──────────────────────────────────────────────────────────────────


class ExportResponse(BaseModel):
    """Full export record returned after generation or by GET."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exam_id: uuid.UUID
    export_type: ExportType
    status: ExportStatus
    # filename derived from file_path for download label; may be None on failure
    filename: str | None = Field(
        default=None,
        description="Basename of the output file (derived server-side).",
    )
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ExportPairResponse(BaseModel):
    """Pair returned by POST /api/v1/exams/{exam_id}/export."""

    exam_export: ExportResponse
    answer_key_export: ExportResponse
