"""
PdfOutlineTocExtractor — reads the PDF's embedded outline/bookmarks.

This is the highest-confidence extractor and should always be tried first.
Most properly authored textbooks (and many lecture notes) embed an outline
tree that maps section titles to page numbers.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from app.services.topic_extraction.base import (
    METHOD_PDF_OUTLINE,
    LEVEL_CHAPTER,
    LEVEL_SECTION,
    LEVEL_SUBSECTION,
    LEVEL_PART,
    ExtractedTopic,
    TopicExtractionResult,
)

logger = logging.getLogger(__name__)

_LEVEL_MAP: dict[int, str] = {
    1: LEVEL_CHAPTER,
    2: LEVEL_SECTION,
    3: LEVEL_SUBSECTION,
}

# Strip leading "1.", "1.2", "Chapter 3", "Section 3.2", "Slide 10:" prefixes
_PREFIX_RE = re.compile(
    r"^(?:(?:chapter|section|part|unit|lecture|module|appendix|slide)\s*[\d.]*\s*[:\-–]?\s*"
    r"|[\d]+(?:\.[\d]+)*\.?\s+)",
    re.IGNORECASE,
)


def _clean_title(raw: str) -> str:
    raw = raw.strip()
    raw = _PREFIX_RE.sub("", raw).strip()
    raw = re.sub(r"\s{2,}", " ", raw)
    return raw


class PdfOutlineTocExtractor:
    """Reads the embedded PDF outline (bookmarks/TOC) via PyMuPDF."""

    name = "pdf_outline"

    def extract(
        self,
        file_path: str,
        *,
        chunks: list[Any] | None = None,
    ) -> TopicExtractionResult:
        empty = TopicExtractionResult(
            topics=[],
            method=METHOD_PDF_OUTLINE,
            overall_confidence=0.0,
            debug_info={"reason": "no outline"},
        )

        try:
            doc = fitz.open(str(file_path))
            raw_toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
            total_pages = len(doc)
            doc.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("PdfOutlineTocExtractor: open failed (%s)", exc)
            empty.debug_info["error"] = str(exc)
            return empty

        if not raw_toc:
            return empty

        # Build topics; compute end_page from next sibling's start_page
        topics: list[ExtractedTopic] = []
        # We store (entry, level_int, start_page) so we can fill end_page
        raw_levels: list[tuple[str, int, int | None]] = []

        for item in raw_toc:
            if len(item) < 2:
                continue
            level_int = max(1, min(int(item[0]), 3))
            raw_title = str(item[1] or "").strip()
            # PyMuPDF page numbers are 1-based; 0 means "unknown destination"
            # Use int(item[2]) directly (even if 0) then treat 0 as None below
            raw_page = int(item[2]) if len(item) > 2 and item[2] is not None else None
            page = raw_page if (raw_page is not None and raw_page > 0) else None
            raw_levels.append((raw_title, level_int, page))

        # Fill end_page: end = next entry's start_page - 1 (for same/higher level)
        for i, (title, level_int, start_page) in enumerate(raw_levels):
            cleaned = _clean_title(title)
            if not cleaned or len(cleaned) < 3:
                continue

            # end_page: look ahead for next entry at same or higher level
            end_page: int | None = None
            for j in range(i + 1, len(raw_levels)):
                nxt_page = raw_levels[j][2]
                if nxt_page is not None:
                    end_page = max(nxt_page - 1, start_page or 1)
                    break
            if end_page is None and total_pages:
                end_page = total_pages

            level_str = _LEVEL_MAP.get(level_int, LEVEL_SUBSECTION)
            # PART is inferred for level-1 entries that look like "Part I"
            if level_int == 1 and re.match(r"^part\b", title, re.IGNORECASE):
                level_str = LEVEL_PART

            topics.append(
                ExtractedTopic(
                    title=cleaned,
                    level=level_str,
                    confidence=0.95,
                    start_page=start_page,
                    end_page=end_page,
                )
            )

        # Wire parent_ref: each SECTION → preceding CHAPTER, etc.
        last_at: dict[int, str] = {}
        for t, (_raw, level_int, _pg) in zip(topics, raw_levels):
            level_int = _LEVEL_MAP_REV.get(t.level, 2)
            if level_int > 1:
                t.parent_ref = last_at.get(level_int - 1)
            last_at[level_int] = t.title

        chapter_count = sum(1 for t in topics if t.level == LEVEL_CHAPTER)
        section_count = sum(1 for t in topics if t.level == LEVEL_SECTION)
        confidence = min(0.98, 0.60 + 0.04 * min(chapter_count, 8) + 0.01 * min(section_count, 20))

        logger.info(
            "PdfOutlineTocExtractor: %d topics (%d chapters, %d sections); confidence=%.2f",
            len(topics), chapter_count, section_count, confidence,
        )
        return TopicExtractionResult(
            topics=topics,
            method=METHOD_PDF_OUTLINE,
            overall_confidence=confidence,
            debug_info={
                "raw_outline_entries": len(raw_toc),
                "topics_after_clean": len(topics),
                "chapter_count": chapter_count,
                "section_count": section_count,
            },
        )


# reverse map for wiring parent_ref
_LEVEL_MAP_REV: dict[str, int] = {
    LEVEL_PART: 0,
    LEVEL_CHAPTER: 1,
    LEVEL_SECTION: 2,
    LEVEL_SUBSECTION: 3,
}
