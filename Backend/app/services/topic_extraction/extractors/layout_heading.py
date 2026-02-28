"""
LayoutHeadingExtractor — detects headings from font-size / layout signals.

Works best for slide decks, notes, and PDFs where headings are visually
distinguished (larger font, bold, top-of-page position) but no outline is
embedded.

Uses PyMuPDF's `page.get_text("dict")` which exposes per-span font size.
"""
from __future__ import annotations

import logging
import re
import statistics
from typing import Any

import fitz  # PyMuPDF

from app.services.topic_extraction.base import (
    METHOD_LAYOUT_HEADINGS,
    LEVEL_HEADING,
    LEVEL_CHAPTER,
    LEVEL_SECTION,
    ExtractedTopic,
    TopicExtractionResult,
)

logger = logging.getLogger(__name__)

_HEADING_MAX_LEN = 120
_HEADING_MIN_LEN = 4
_MAX_PAGES_TO_SCAN = 300  # cap for very large documents


def _get_spans(page: fitz.Page) -> list[dict[str, Any]]:
    """Extract all text spans from a page dict."""
    spans: list[dict[str, Any]] = []
    try:
        page_dict: dict[str, Any] = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)  # type: ignore[assignment]
        blocks = page_dict.get("blocks", [])
    except Exception:  # noqa: BLE001
        return spans
    for block in blocks:
        if block.get("type") != 0:  # text block only
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                spans.append(span)
    return spans


def _is_bold(flags: int) -> bool:
    # PyMuPDF font flags: bit 4 = bold (serifed bold), bit 20 = bold (sans)
    return bool(flags & (1 << 4)) or bool(flags & (1 << 20))


class LayoutHeadingExtractor:
    """Heading detector using font-size / bold / position heuristics."""

    name = "layout_headings"

    def extract(
        self,
        file_path: str,
        *,
        chunks: list[Any] | None = None,
    ) -> TopicExtractionResult:
        empty = TopicExtractionResult(
            topics=[],
            method=METHOD_LAYOUT_HEADINGS,
            overall_confidence=0.0,
            debug_info={"reason": "no headings detected"},
        )

        try:
            doc = fitz.open(str(file_path))
            total_pages = len(doc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LayoutHeadingExtractor: open failed (%s)", exc)
            empty.debug_info["error"] = str(exc)
            return empty

        # --- Phase 1: collect all font sizes to establish baseline ----------
        all_font_sizes: list[float] = []
        pages_to_scan = min(total_pages, _MAX_PAGES_TO_SCAN)
        span_cache: list[tuple[int, list[dict[str, Any]]]] = []

        for page_num in range(pages_to_scan):
            page = doc.load_page(page_num)
            spans = _get_spans(page)
            span_cache.append((page_num + 1, spans))
            for sp in spans:
                sz = sp.get("size", 0.0)
                if sz > 0:
                    all_font_sizes.append(sz)

        doc.close()

        if not all_font_sizes:
            return empty

        try:
            median_size = statistics.median(all_font_sizes)
        except Exception:
            median_size = 12.0

        heading_threshold = median_size * 1.20  # 20% larger than median

        # --- Phase 2: detect heading spans ----------------------------------
        heading_texts: list[tuple[int, str, float]] = []  # (page, text, font_size)

        for page_num, spans in span_cache:
            for sp in spans:
                text = (sp.get("text") or "").strip()
                size = float(sp.get("size", 0.0))
                flags = int(sp.get("flags", 0))

                if not text or len(text) < _HEADING_MIN_LEN:
                    continue
                if len(text) > _HEADING_MAX_LEN:
                    continue
                # Must be bigger than threshold OR bold and decently sized
                if size >= heading_threshold or (_is_bold(flags) and size >= median_size * 1.05):
                    heading_texts.append((page_num, text, size))

        if not heading_texts:
            return empty

        # --- Phase 3: deduplicate repeated boilerplate ----------------------
        # If a heading text appears on > 30% of pages it's a boilerplate header
        text_page_count: dict[str, set[int]] = {}
        for pg, txt, _ in heading_texts:
            text_page_count.setdefault(txt.lower(), set()).add(pg)

        boilerplate: set[str] = {
            t for t, pages in text_page_count.items()
            if len(pages) / max(1, pages_to_scan) >= 0.30
        }

        # --- Phase 4: merge consecutive spans on same page ------------------
        merged: list[tuple[int, str, float]] = []
        prev_page, prev_text, prev_size = -1, "", 0.0
        for pg, txt, sz in heading_texts:
            txt_lo = txt.lower()
            if txt_lo in boilerplate:
                continue
            if pg == prev_page and abs(sz - prev_size) < 1.0:
                prev_text = (prev_text + " " + txt).strip()
                prev_size = max(prev_size, sz)
            else:
                if prev_text:
                    merged.append((prev_page, prev_text, prev_size))
                prev_page, prev_text, prev_size = pg, txt, sz
        if prev_text:
            merged.append((prev_page, prev_text, prev_size))

        # --- Phase 5: build topics ------------------------------------------
        # Assign level: largest-font headings → CHAPTER, medium → SECTION
        sizes = [sz for _, _, sz in merged]
        if not sizes:
            return empty

        size_max = max(sizes)
        chapter_threshold = size_max * 0.90

        topics: list[ExtractedTopic] = []
        for i, (pg, txt, sz) in enumerate(merged):
            level = LEVEL_CHAPTER if sz >= chapter_threshold else (
                LEVEL_SECTION if sz >= heading_threshold else LEVEL_HEADING
            )
            # end_page: next heading's page - 1
            end_pg: int | None = merged[i + 1][0] - 1 if i + 1 < len(merged) else None
            topics.append(
                ExtractedTopic(
                    title=txt,
                    level=level,
                    confidence=min(0.85, 0.50 + 0.005 * len(heading_texts)),
                    start_page=pg,
                    end_page=end_pg,
                )
            )

        pages_with_headings = len({pg for pg, _, _ in heading_texts if (pg,) not in
                                    [(pg2,) for pg2, t, _ in heading_texts if t.lower() in boilerplate]})
        confidence = min(0.82, 0.35 + 0.35 * min(pages_with_headings / max(1, pages_to_scan), 1.0) + 0.02 * min(len(topics), 10))

        logger.info(
            "LayoutHeadingExtractor: %d topics from %d heading spans; confidence=%.2f",
            len(topics), len(heading_texts), confidence,
        )
        return TopicExtractionResult(
            topics=topics,
            method=METHOD_LAYOUT_HEADINGS,
            overall_confidence=confidence,
            debug_info={
                "pages_scanned": pages_to_scan,
                "spans_total": sum(len(s) for _, s in span_cache),
                "heading_spans": len(heading_texts),
                "boilerplate_dropped": len(boilerplate),
                "topics_found": len(topics),
                "median_font_size": round(median_size, 2),
                "heading_threshold": round(heading_threshold, 2),
            },
        )
