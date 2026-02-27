"""
Export API routes (Phase 11 — Export).

POST   /api/v1/exams/{exam_id}/export          → trigger export; returns ExportPairResponse
GET    /api/v1/exams/{exam_id}/exports         → list exports for an exam
GET    /api/v1/exports/{export_id}/download    → download the generated file (FileResponse)
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.export import ExportStatus
from app.schemas.export import ExportPairResponse, ExportResponse
from app.services.export_service import ExportService

# Two routers mounted from main.py:
#   exams_router   → prefix="/exams"    (sub-routes for a specific exam)
#   exports_router → prefix="/exports"  (standalone export resource)
exams_export_router = APIRouter(tags=["exports"])
exports_router = APIRouter(tags=["exports"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _get_export_service() -> ExportService:
    return ExportService()


ExportServiceDep = Annotated[ExportService, Depends(_get_export_service)]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _export_to_response(export) -> ExportResponse:  # type: ignore[return]
    """Map ORM Export → ExportResponse, deriving `filename` from `file_path`."""
    filename: str | None = None
    if export.file_path:
        filename = Path(export.file_path).name
    return ExportResponse(
        id=export.id,
        exam_id=export.exam_id,
        export_type=export.export_type,
        status=export.status,
        filename=filename,
        error_message=export.error_message,
        created_at=export.created_at,
        updated_at=export.updated_at,
    )


def _safe_file_path(export) -> Path:
    """
    Resolve the file path for download, enforcing that it resides under
    EXPORT_DIR to prevent path-traversal attacks.

    Raises HTTPException 404 / 400 on any invalid state.
    """
    if export.status != ExportStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export is not ready (status={export.status.value}).",
        )
    if not export.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export record has no file path.",
        )

    # Resolve absolute path
    export_path = Path(export.file_path).resolve()

    # Compute the allowed root (EXPORT_DIR may be relative to cwd)
    export_dir = Path(settings.EXPORT_DIR).resolve()
    try:
        export_path.relative_to(export_dir)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requested file is outside the export directory.",
        )

    if not export_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export file not found on disk.",
        )

    return export_path


# ── Endpoints: /exams/{exam_id}/... ──────────────────────────────────────────


@exams_export_router.post(
    "/{exam_id}/export",
    status_code=status.HTTP_201_CREATED,
    response_model=ExportPairResponse,
    summary="Export an exam (generates .tex + optional PDF)",
)
async def trigger_export(
    exam_id: uuid.UUID,
    db: DbSession,
    svc: ExportServiceDep,
):
    """
    Generate the exam document and answer-key document.

    Both are written as LaTeX (.tex) files.  If *pdflatex* is available on the
    server PATH they are also compiled to PDF; otherwise the .tex sources are
    the downloadable artefacts.
    """
    try:
        exam_export, answer_key_export = await svc.export_exam(db, exam_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {exc}",
        )

    return ExportPairResponse(
        exam_export=_export_to_response(exam_export),
        answer_key_export=_export_to_response(answer_key_export),
    )


@exams_export_router.get(
    "/{exam_id}/exports",
    response_model=list[ExportResponse],
    summary="List all exports for an exam",
)
async def list_exam_exports(
    exam_id: uuid.UUID,
    db: DbSession,
    svc: ExportServiceDep,
):
    """Return all export records for an exam, newest first."""
    exports = await svc.list_by_exam(db, exam_id)
    return [_export_to_response(e) for e in exports]


# ── Endpoints: /exports/{export_id}/... ──────────────────────────────────────


@exports_router.get(
    "/{export_id}/download",
    summary="Download an export file",
    response_class=FileResponse,
)
async def download_export(
    export_id: uuid.UUID,
    db: DbSession,
    svc: ExportServiceDep,
):
    """
    Stream the generated file (.tex or .pdf) to the client.

    Only *completed* exports are downloadable.  The file is validated to
    reside within the server's EXPORT_DIR before being served.
    """
    export = await svc.get_by_id(db, export_id)
    if export is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export {export_id} not found.",
        )

    file_path = _safe_file_path(export)

    # Determine MIME type from extension
    suffix = file_path.suffix.lower()
    media_type = (
        "application/pdf" if suffix == ".pdf"
        else "application/x-tex" if suffix == ".tex"
        else "application/octet-stream"
    )

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
    )
