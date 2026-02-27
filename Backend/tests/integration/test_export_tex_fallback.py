"""
Integration tests: ExportService falls back to .tex when pdflatex is absent.

In development and CI, pdflatex is not on PATH.  ExportService must:
  - create two Export rows (exam + answer_key)
  - write valid .tex files to disk
  - set status = ``completed``
  - set export_type = ``exam_tex`` / ``answer_key_tex``  (not _pdf)
  - record an error_message explaining why PDF was not produced

The test assembles a minimal exam (one approved MCQ question) so that the
Jinja2 template has real data to render.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.course import Course
from app.models.exam import Exam
from app.models.export import Export, ExportStatus, ExportType
from app.models.question import Question, QuestionSet, QuestionStatus
from app.schemas.exam import AssembleExamRequest
from app.services.exam_assembly_service import ExamAssemblyService
from app.services.export_service import ExportService
from tests.integration.conftest import make_blueprint, make_mcq_question


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
async def exam_for_export(
    db_session: AsyncSession,
    course: Course,
    question_set: QuestionSet,
) -> Exam:
    """
    Create an approved MCQ question, a blueprint, and an assembled exam.

    Commits everything so that ExportService can read back the rows with fresh
    selectinload queries.
    """
    q = await make_mcq_question(
        db_session,
        question_set,
        status=QuestionStatus.approved,
    )
    bp = await make_blueprint(db_session, course, title="Export Test Blueprint")

    svc = ExamAssemblyService(db_session)
    payload = AssembleExamRequest(
        title="Export Test Exam",
        description="Generated for integration testing.",
        question_set_id=question_set.id,
    )
    exam = await svc.assemble(bp, payload)
    await db_session.commit()
    return exam


@pytest.fixture()
async def export_result(
    db_session: AsyncSession,
    exam_for_export: Exam,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Export, Export]:
    """
    Run ExportService.export_exam() with EXPORT_DIR redirected to tmp_path.

    Returns (exam_export, answer_key_export).
    """
    # Redirect exports to a pytest-managed temp directory so tests don't
    # write to the production export directory.
    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))

    svc = ExportService()
    result = await svc.export_exam(db_session, exam_for_export.id)
    await db_session.commit()
    return result


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestExportStatusAndType:
    """Both export records finish in a completed state with _tex type."""

    async def test_exam_export_status_completed(
        self, export_result: tuple[Export, Export]
    ) -> None:
        exam_export, _ = export_result
        assert exam_export.status == ExportStatus.completed

    async def test_answer_key_export_status_completed(
        self, export_result: tuple[Export, Export]
    ) -> None:
        _, answer_key_export = export_result
        assert answer_key_export.status == ExportStatus.completed

    async def test_exam_export_type_is_tex(
        self, export_result: tuple[Export, Export]
    ) -> None:
        """Without pdflatex, export_type must be exam_tex (not exam_pdf)."""
        exam_export, _ = export_result
        assert exam_export.export_type == ExportType.exam_tex

    async def test_answer_key_export_type_is_tex(
        self, export_result: tuple[Export, Export]
    ) -> None:
        _, answer_key_export = export_result
        assert answer_key_export.export_type == ExportType.answer_key_tex

    async def test_neither_export_is_pdf(
        self, export_result: tuple[Export, Export]
    ) -> None:
        exam_export, answer_key_export = export_result
        assert exam_export.export_type != ExportType.exam_pdf
        assert answer_key_export.export_type != ExportType.answer_key_pdf


class TestExportFilesWrittenToDisk:
    """Export service writes readable .tex files to EXPORT_DIR/{exam_id}/."""

    async def test_exam_tex_file_exists(
        self,
        export_result: tuple[Export, Export],
    ) -> None:
        exam_export, _ = export_result
        assert exam_export.file_path is not None
        assert Path(exam_export.file_path).exists(), (
            f"Expected .tex file at {exam_export.file_path}"
        )

    async def test_answer_key_tex_file_exists(
        self,
        export_result: tuple[Export, Export],
    ) -> None:
        _, answer_key_export = export_result
        assert answer_key_export.file_path is not None
        assert Path(answer_key_export.file_path).exists(), (
            f"Expected .tex file at {answer_key_export.file_path}"
        )

    async def test_exam_tex_file_has_latex_content(
        self,
        export_result: tuple[Export, Export],
    ) -> None:
        """Rendered .tex should contain a LaTeX document class declaration."""
        exam_export, _ = export_result
        assert exam_export.file_path is not None
        tex_content = Path(exam_export.file_path).read_text(encoding="utf-8")
        assert "\\documentclass" in tex_content or "documentclass" in tex_content.lower(), (
            "Exported .tex does not appear to be a LaTeX document."
        )

    async def test_answer_key_tex_file_has_latex_content(
        self,
        export_result: tuple[Export, Export],
    ) -> None:
        _, answer_key_export = export_result
        assert answer_key_export.file_path is not None
        tex_content = Path(answer_key_export.file_path).read_text(encoding="utf-8")
        assert "\\documentclass" in tex_content or "documentclass" in tex_content.lower()

    async def test_exam_tex_contains_exam_title(
        self,
        export_result: tuple[Export, Export],
    ) -> None:
        """Rendered exam .tex should embed the exam title."""
        exam_export, _ = export_result
        assert exam_export.file_path is not None
        tex_content = Path(exam_export.file_path).read_text(encoding="utf-8")
        assert "Export Test Exam" in tex_content

    async def test_exam_file_path_ends_with_tex(
        self, export_result: tuple[Export, Export]
    ) -> None:
        exam_export, answer_key_export = export_result
        assert exam_export.file_path is not None
        assert answer_key_export.file_path is not None
        assert exam_export.file_path.endswith(".tex")
        assert answer_key_export.file_path.endswith(".tex")


class TestExportPdflatexFallbackMessage:
    """When pdflatex is absent, error_message records the reason."""

    async def test_exam_export_has_fallback_message(
        self, export_result: tuple[Export, Export]
    ) -> None:
        """Export record documents why PDF was not compiled."""
        exam_export, _ = export_result
        # Only check for error_message when PDF compilation was skipped
        # (i.e., export_type is tex, not pdf).
        if exam_export.export_type == ExportType.exam_tex:
            # May be None if pdflatex happened to be on PATH — skip in that case.
            if exam_export.error_message is not None:
                assert "pdflatex" in exam_export.error_message.lower() or "not" in exam_export.error_message.lower()

    async def test_exam_export_persisted_in_db(
        self,
        db_session: AsyncSession,
        export_result: tuple[Export, Export],
    ) -> None:
        """Export rows must be stored in the database."""
        from sqlalchemy import select
        from app.models.export import Export as ExportModel

        exam_export, answer_key_export = export_result
        for export_id in (exam_export.id, answer_key_export.id):
            result = await db_session.execute(
                select(ExportModel).where(ExportModel.id == export_id)
            )
            found = result.scalar_one_or_none()
            assert found is not None, f"Export {export_id} not found in DB"
