"""
PDF text extraction utilities using PyMuPDF (fitz).

Design goals
────────────
- Pure functions: no DB, no I/O side-effects beyond reading the file.
- Page-level granularity: every extracted block carries a page number so
  downstream chunking can preserve source position metadata.
- Test-friendly: pass a file path or raw bytes — both are supported.

Typical usage
─────────────
    from app.utils.pdf import extract_pages, extract_full_text

    pages = extract_pages("path/to/file.pdf")
    for p in pages:
        print(p.page_number, p.text[:80])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


# ── Data structures ───────────────────────────────────────────────


@dataclass
class PageText:
    """Text content extracted from a single PDF page."""

    page_number: int          # 1-based
    text: str                 # raw extracted text for this page
    char_start: int           # absolute character offset in concatenated document
    char_end: int             # exclusive end offset


@dataclass
class ExtractionResult:
    """Aggregated result of a full PDF extraction."""

    pages: list[PageText] = field(default_factory=list)
    total_pages: int = 0
    total_chars: int = 0

    @property
    def full_text(self) -> str:
        """Concatenate all pages with a newline separator."""
        return "\n".join(p.text for p in self.pages)


# ── Extraction functions ──────────────────────────────────────────


def extract_pages(source: str | Path | bytes) -> ExtractionResult:
    """
    Extract page-by-page text from a PDF.

    Parameters
    ----------
    source : str | Path | bytes
        File path **or** raw PDF bytes (e.g. from an in-memory upload).

    Returns
    -------
    ExtractionResult
        Ordered list of PageText objects, one per page.

    Notes
    -----
    - Uses fitz.Page.get_text("text") which handles most embedded fonts.
    - Rotated / scanned pages will return an empty string for that page
      (OCR is out of scope for the MVP).
    """
    if isinstance(source, (str, Path)):
        doc = fitz.open(str(source))
    else:
        # open from raw bytes
        doc = fitz.open(stream=source, filetype="pdf")

    result = ExtractionResult(total_pages=len(doc))
    cumulative = 0

    for i in range(len(doc)):
        page = doc.load_page(i)
        raw: str = str(page.get_text("text") or "")
        page_obj = PageText(
            page_number=i + 1,  # 1-based
            text=raw,
            char_start=cumulative,
            char_end=cumulative + len(raw),
        )
        result.pages.append(page_obj)
        cumulative += len(raw) + 1  # +1 for the \n separator added by full_text

    result.total_chars = cumulative
    doc.close()

    logger.debug(
        "Extracted %d pages, ~%d chars from PDF",
        result.total_pages,
        result.total_chars,
    )
    return result


def extract_full_text(source: str | Path | bytes) -> str:
    """
    Convenience wrapper — return the concatenated text of all pages.

    Equivalent to ``extract_pages(source).full_text``.
    """
    return extract_pages(source).full_text
