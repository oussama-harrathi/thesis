"""
LaTeX compilation utility.

Provides:
  - ``latex_escape(text)``   — escape LaTeX special characters in user text
  - ``pdflatex_available()`` — detect whether ``pdflatex`` is on PATH
  - ``compile_pdf(tex_path)`` — compile a .tex file to PDF via pdflatex,
                                with a fallback .tex path on failure/absence

Usage
-----
``compile_pdf`` runs ``pdflatex`` twice (to resolve forward references such as
\tableofcontents) with the output directory set to the same folder as the
.tex file.  It returns the path to the compiled PDF, or raises ``LatexError``
if compilation fails.

The high-level ``ExportService`` catches ``LatexError`` and falls back to
returning the .tex file path instead of a PDF.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────

class LatexError(Exception):
    """Raised when pdflatex compilation fails or is unavailable."""


# ── Character escaping ────────────────────────────────────────────

# Single-pass regex: finds all LaTeX-special characters in one scan so that
# replacement strings (e.g. \textbackslash{}) are never processed a second time.
_SPECIAL_CHARS_RE = re.compile(r"([\\&%$#_{}~^])")

_CHAR_MAP: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    """
    Escape ``text`` so that it is safe to embed verbatim in a LaTeX document.

    Handles all 10 LaTeX special characters in a single regex pass, avoiding
    double-escaping of the replacement strings themselves.
    """
    if not text:
        return ""
    return _SPECIAL_CHARS_RE.sub(lambda m: _CHAR_MAP[m.group(0)], text)


# ── pdflatex availability ─────────────────────────────────────────

def pdflatex_available() -> bool:
    """Return ``True`` if ``pdflatex`` is on the system PATH."""
    return shutil.which("pdflatex") is not None


# ── PDF compilation ───────────────────────────────────────────────

def compile_pdf(tex_path: Path, *, runs: int = 2) -> Path:
    """
    Compile *tex_path* to a PDF using ``pdflatex``.

    Parameters
    ----------
    tex_path : Path
        Absolute path to the .tex source file.
    runs : int
        Number of pdflatex passes (default 2 — resolves cross-references).

    Returns
    -------
    Path
        Path to the generated .pdf file (same directory/stem as tex_path).

    Raises
    ------
    LatexError
        If ``pdflatex`` is not on PATH, or if any compilation pass fails.
    """
    if not pdflatex_available():
        raise LatexError("pdflatex is not installed or not on PATH.")

    output_dir = tex_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = output_dir / tex_path.with_suffix(".pdf").name

    for run_num in range(1, runs + 1):
        logger.info(
            "compile_pdf: run %d/%d — compiling %s",
            run_num,
            runs,
            tex_path,
        )
        try:
            result = subprocess.run(
                [
                    "pdflatex",
                    "-interaction=nonstopmode",       # never pause for input
                    "-halt-on-error",                  # exit non-zero on error
                    f"-output-directory={output_dir}",
                    str(tex_path),
                ],
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                timeout=60,                            # seconds per pass
            )
        except subprocess.TimeoutExpired as exc:
            raise LatexError(
                f"pdflatex timed out on run {run_num} for {tex_path}"
            ) from exc
        except FileNotFoundError as exc:
            raise LatexError(
                "pdflatex executable not found."
            ) from exc

        if result.returncode != 0:
            # Surface the last 20 lines of stdout (pdflatex puts errors there).
            tail = "\n".join(result.stdout.splitlines()[-20:])
            raise LatexError(
                f"pdflatex run {run_num} failed (exit {result.returncode}):\n{tail}"
            )

        logger.debug(
            "compile_pdf: run %d/%d succeeded for %s",
            run_num,
            runs,
            tex_path,
        )

    if not pdf_path.exists():
        raise LatexError(
            f"pdflatex returned exit 0 but no PDF was produced at {pdf_path}"
        )

    logger.info("compile_pdf: PDF written to %s", pdf_path)
    return pdf_path


def write_tex(content: str, output_path: Path) -> Path:
    """
    Write *content* to *output_path*, creating parent directories as needed.

    Returns *output_path* for convenience.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logger.info("write_tex: .tex written to %s", output_path)
    return output_path
