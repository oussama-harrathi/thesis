"""
Export Service

Renders an assembled exam and its answer key to LaTeX, attempts PDF
compilation via ``pdflatex``, and falls back to raw ``.tex`` if the compiler
is unavailable or fails.

Export flow (for one exam)
--------------------------
1. Load Exam + ordered ExamQuestions (with Question → mcq_options) from DB.
2. Create two Export rows (exam + answer_key) in ``pending`` state; flush.
3. Render exam .tex  using ``exam_template.tex.j2``      via Jinja2.
4. Render answer-key .tex using ``answer_key_template.tex.j2`` via Jinja2.
5. Write both .tex files to ``EXPORT_DIR/{exam_id}/``.
6. For each file:
   a. If ``pdflatex`` is on PATH, compile to PDF.
   b. If compile succeeds  → set export_type = exam_pdf / answer_key_pdf,
                             file_path = <pdf_path>, status = completed.
   c. If compile fails/absent → set export_type = exam_tex / answer_key_tex,
                                file_path = <tex_path>, status = completed,
                                error_message = "<reason>".
7. Update each Export row and flush.

Returns a tuple ``(exam_export, answer_key_export)``.

Caller (FastAPI route, future) commits the session after return.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.exam import Exam, ExamQuestion
from app.models.export import Export, ExportStatus, ExportType
from app.models.question import Question
from app.utils.latex import (
    LatexError,
    compile_pdf,
    latex_escape,
    pdflatex_available,
    write_tex,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Jinja2 environment ────────────────────────────────────────────

# Using non-default delimiters to avoid conflicts with LaTeX { } braces.
# Templates use << var >>, <% block %>, <# comment #>.
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "latex"

_jinja_env: Environment | None = None


def _get_jinja_env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=False,            # LaTeX is not HTML — no HTML escaping
            block_start_string="<%",
            block_end_string="%>",
            variable_start_string="<<",
            variable_end_string=">>",
            comment_start_string="<#",
            comment_end_string="#>",
            keep_trailing_newline=True,
        )
        _jinja_env.filters["latex_escape"] = latex_escape
    return _jinja_env


# ── Service ───────────────────────────────────────────────────────


class ExportService:
    """
    Renders and (optionally) compiles exports for an assembled exam.

    All async methods accept an open SQLAlchemy AsyncSession.
    The caller is responsible for committing or rolling back.
    """

    # ------------------------------------------------------------------ #
    # Public entry-point                                                   #
    # ------------------------------------------------------------------ #

    async def export_exam(
        self,
        db: AsyncSession,
        exam_id: uuid.UUID,
    ) -> tuple[Export, Export]:
        """
        Produce an exam export and an answer-key export.

        Returns ``(exam_export, answer_key_export)``.

        Raises
        ------
        ValueError
            If the exam does not exist.
        """
        # ── 1. Load exam with all dependencies ────────────────────
        exam = await self._load_exam(db, exam_id)
        if exam is None:
            raise ValueError(f"Exam {exam_id} not found.")

        # Ordered list of ExamQuestion slots (already selectin-loaded)
        items = list(exam.exam_questions)

        logger.info(
            "export_exam: starting export for exam=%s (%s, %d questions)",
            exam_id,
            exam.title,
            len(items),
        )

        # ── 2. Create pending Export rows ─────────────────────────
        exam_export = Export(
            id=uuid.uuid4(),
            exam_id=exam.id,
            export_type=ExportType.exam_tex,    # will be updated after compile
            status=ExportStatus.pending,
        )
        answer_key_export = Export(
            id=uuid.uuid4(),
            exam_id=exam.id,
            export_type=ExportType.answer_key_tex,
            status=ExportStatus.pending,
        )
        db.add(exam_export)
        db.add(answer_key_export)
        await db.flush()    # get IDs before writing files

        # ── 3. Render .tex strings ─────────────────────────────────
        env = _get_jinja_env()
        try:
            exam_tex = self._render_exam_tex(env, exam, items)
        except Exception as exc:
            logger.error("export_exam: exam template render failed: %s", exc, exc_info=True)
            await self._mark_failed(db, exam_export, f"Template render failed: {exc}")
            await self._mark_failed(db, answer_key_export, "Skipped — exam render failed.")
            return exam_export, answer_key_export

        try:
            key_tex = self._render_answer_key_tex(env, exam, items)
        except Exception as exc:
            logger.error("export_exam: answer-key template render failed: %s", exc, exc_info=True)
            await self._mark_failed(db, answer_key_export, f"Template render failed: {exc}")
            key_tex = None  # skip disk write below

        # ── 4. Write .tex files to disk ────────────────────────────
        export_dir = Path(settings.EXPORT_DIR) / str(exam_id)
        exam_tex_path   = export_dir / "exam.tex"
        key_tex_path    = export_dir / "answer_key.tex"

        try:
            write_tex(exam_tex, exam_tex_path)
        except OSError as exc:
            logger.error("export_exam: could not write exam.tex: %s", exc)
            await self._mark_failed(db, exam_export, f"Disk write failed: {exc}")
        else:
            await self._compile_and_update(
                db,
                export_record=exam_export,
                tex_path=exam_tex_path,
                pdf_type=ExportType.exam_pdf,
                tex_type=ExportType.exam_tex,
            )

        if key_tex is not None:
            try:
                write_tex(key_tex, key_tex_path)
            except OSError as exc:
                logger.error("export_exam: could not write answer_key.tex: %s", exc)
                await self._mark_failed(db, answer_key_export, f"Disk write failed: {exc}")
            else:
                await self._compile_and_update(
                    db,
                    export_record=answer_key_export,
                    tex_path=key_tex_path,
                    pdf_type=ExportType.answer_key_pdf,
                    tex_type=ExportType.answer_key_tex,
                )

        await db.flush()
        # Refresh both objects so all server-set columns (e.g. updated_at) are
        # loaded while we are still inside the async context.  Without this,
        # accessing those columns in synchronous helper code causes a
        # MissingGreenlet error because SQLAlchemy would try to lazy-load them.
        await db.refresh(exam_export)
        await db.refresh(answer_key_export)
        return exam_export, answer_key_export

    async def list_by_exam(
        self,
        db: AsyncSession,
        exam_id: uuid.UUID,
    ) -> list[Export]:
        """Return all Export records for the given exam (newest first)."""
        result = await db.execute(
            select(Export)
            .where(Export.exam_id == exam_id)
            .order_by(Export.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(
        self,
        db: AsyncSession,
        export_id: uuid.UUID,
    ) -> Export | None:
        """Return a single Export record by primary key, or None."""
        result = await db.execute(
            select(Export).where(Export.id == export_id)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Template rendering                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _render_exam_tex(env: Environment, exam: Exam, items: list[ExamQuestion]) -> str:
        """Render *exam_template.tex.j2* and return the .tex source string."""
        template = env.get_template("exam_template.tex.j2")
        return template.render(exam=exam, items=items)

    @staticmethod
    def _render_answer_key_tex(env: Environment, exam: Exam, items: list[ExamQuestion]) -> str:
        """Render *answer_key_template.tex.j2* and return the .tex source string."""
        template = env.get_template("answer_key_template.tex.j2")
        return template.render(exam=exam, items=items)

    # ------------------------------------------------------------------ #
    # Compile + update helpers                                             #
    # ------------------------------------------------------------------ #

    async def _compile_and_update(
        self,
        db: AsyncSession,
        *,
        export_record: Export,
        tex_path: Path,
        pdf_type: ExportType,
        tex_type: ExportType,
    ) -> None:
        """
        Try to compile *tex_path* to PDF.

        On success  → export_type = *pdf_type*,  file_path = pdf path.
        On fallback → export_type = *tex_type*,  file_path = tex path,
                      error_message = reason.
        Either way → status = completed.
        """
        if not pdflatex_available():
            reason = "pdflatex not found on PATH — returning .tex source."
            logger.warning("_compile_and_update: %s (exam=%s)", reason, export_record.exam_id)
            export_record.export_type = tex_type
            export_record.file_path   = str(tex_path)
            export_record.status      = ExportStatus.completed
            export_record.error_message = reason
            return

        try:
            pdf_path = compile_pdf(tex_path)
        except LatexError as exc:
            reason = str(exc)
            logger.warning(
                "_compile_and_update: pdflatex failed for %s — falling back to .tex: %s",
                tex_path,
                reason,
            )
            export_record.export_type   = tex_type
            export_record.file_path     = str(tex_path)
            export_record.status        = ExportStatus.completed
            export_record.error_message = reason
            return

        export_record.export_type   = pdf_type
        export_record.file_path     = str(pdf_path)
        export_record.status        = ExportStatus.completed
        export_record.error_message = None
        logger.info(
            "_compile_and_update: PDF export completed → %s",
            pdf_path,
        )

    @staticmethod
    async def _mark_failed(
        db: AsyncSession,
        export_record: Export,
        reason: str,
    ) -> None:
        """Set export status to failed with an error message."""
        export_record.status = ExportStatus.failed
        export_record.error_message = reason
        logger.error("export marked as failed (id=%s): %s", export_record.id, reason)

    # ------------------------------------------------------------------ #
    # DB helpers                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _load_exam(db: AsyncSession, exam_id: uuid.UUID) -> Exam | None:
        """
        Load an exam with:
          exam_questions → (question → mcq_options)

        Uses selectinload to avoid N+1 queries.
        """
        result = await db.execute(
            select(Exam)
            .where(Exam.id == exam_id)
            .options(
                selectinload(Exam.exam_questions).selectinload(
                    ExamQuestion.question
                ).selectinload(Question.mcq_options)
            )
        )
        return result.scalar_one_or_none()
