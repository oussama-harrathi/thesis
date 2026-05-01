"""
LayoutHeadingExtractor - detects headings from font-size and layout signals.

This extractor is for PDFs where headings are visually distinct but no usable
outline is embedded. It prefers short lines near the top of the page or lines
separated by clear whitespace, and intentionally rejects sentence-like prose.
"""
from __future__ import annotations

import logging
import re
import statistics
from typing import Any

import fitz  # PyMuPDF

from app.services.topic_extraction.base import (
    LEVEL_CHAPTER,
    LEVEL_HEADING,
    LEVEL_SECTION,
    METHOD_LAYOUT_HEADINGS,
    ExtractedTopic,
    TopicExtractionResult,
)

logger = logging.getLogger(__name__)

_HEADING_MAX_CHARS = 120
_HEADING_MIN_CHARS = 4
_MAX_HEADING_WORDS = 12
_MAX_PAGES_TO_SCAN = 300
_TOP_PAGE_PORTION = 0.32
_QUESTION_WORD_LIMIT = 8
_ALPHA_RE = re.compile(r"[A-Za-z]")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_COLLAPSE_WS = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return _COLLAPSE_WS.sub(" ", text.strip())


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _get_page_lines(page: fitz.Page) -> tuple[list[dict[str, Any]], list[float]]:
    """Return page lines plus all observed span font sizes."""
    lines: list[dict[str, Any]] = []
    font_sizes: list[float] = []
    try:
        page_dict: dict[str, Any] = page.get_text(
            "dict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE,
        )
    except Exception:  # noqa: BLE001
        return lines, font_sizes

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            bbox = line.get("bbox") or block.get("bbox") or (0.0, 0.0, 0.0, 0.0)
            text = _normalize_text(
                " ".join(
                    str(span.get("text") or "").strip()
                    for span in spans
                    if str(span.get("text") or "").strip()
                )
            )
            max_size = 0.0
            bold = False
            for span in spans:
                size = float(span.get("size", 0.0))
                if size > 0:
                    font_sizes.append(size)
                    max_size = max(max_size, size)
                flags = int(span.get("flags", 0))
                bold = bold or _is_bold(flags)
            lines.append(
                {
                    "text": text,
                    "size": max_size,
                    "bold": bold,
                    "y0": float(bbox[1]),
                    "y1": float(bbox[3]),
                }
            )

    lines.sort(key=lambda item: (item["y0"], item["y1"]))
    return lines, font_sizes


def _is_bold(flags: int) -> bool:
    # PyMuPDF font flags: bit 4 = bold (serifed bold), bit 20 = bold (sans)
    return bool(flags & (1 << 4)) or bool(flags & (1 << 20))


def _looks_like_prose(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if not _ALPHA_RE.search(stripped):
        return True
    words = _word_count(stripped)
    if words == 0 or words > _MAX_HEADING_WORDS:
        return True
    if stripped.endswith("."):
        return True
    if stripped.endswith("?") and words > _QUESTION_WORD_LIMIT:
        return True
    if "," in stripped and words > 6:
        return True
    return False


class LayoutHeadingExtractor:
    """Heading detector using font-size, position, and whitespace heuristics."""

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

        pages_to_scan = min(total_pages, _MAX_PAGES_TO_SCAN)
        page_cache: list[tuple[int, float, list[dict[str, Any]]]] = []
        all_font_sizes: list[float] = []

        for page_num in range(pages_to_scan):
            page = doc.load_page(page_num)
            lines, font_sizes = _get_page_lines(page)
            page_cache.append((page_num + 1, float(page.rect.height), lines))
            all_font_sizes.extend(font_sizes)

        doc.close()

        if not all_font_sizes:
            return empty

        try:
            median_size = statistics.median(all_font_sizes)
        except Exception:  # noqa: BLE001
            median_size = 12.0

        heading_threshold = median_size * 1.20
        heading_lines: list[tuple[int, str, float, float]] = []

        for page_num, page_height, lines in page_cache:
            prev_y1 = 0.0
            for idx, line in enumerate(lines):
                text = line["text"]
                size = float(line["size"])
                y0 = float(line["y0"])
                y1 = float(line["y1"])
                bold = bool(line["bold"])

                if not text or len(text) < _HEADING_MIN_CHARS:
                    prev_y1 = max(prev_y1, y1)
                    continue
                if len(text) > _HEADING_MAX_CHARS or _looks_like_prose(text):
                    prev_y1 = max(prev_y1, y1)
                    continue

                in_top_region = y0 <= page_height * _TOP_PAGE_PORTION
                whitespace_above = idx == 0 or (y0 - prev_y1) >= max(8.0, size * 0.85)
                if not (in_top_region or whitespace_above):
                    prev_y1 = max(prev_y1, y1)
                    continue

                big_enough = size >= heading_threshold or (bold and size >= median_size * 1.08)
                if not big_enough:
                    prev_y1 = max(prev_y1, y1)
                    continue

                heading_lines.append((page_num, text, size, y0))
                prev_y1 = max(prev_y1, y1)

        if not heading_lines:
            return empty

        # Boilerplate: repeated on many pages.
        text_page_count: dict[str, set[int]] = {}
        for pg, txt, _size, _y0 in heading_lines:
            text_page_count.setdefault(txt.lower(), set()).add(pg)
        boilerplate: set[str] = {
            text
            for text, pages in text_page_count.items()
            if len(pages) >= 3 and len(pages) / max(1, pages_to_scan) >= 0.30
        }

        filtered_lines = [
            item
            for item in heading_lines
            if item[1].lower() not in boilerplate
        ]
        if not filtered_lines:
            return empty

        # Merge only short adjacent lines near the top; do not stitch body prose.
        merged: list[tuple[int, str, float, float]] = []
        idx = 0
        while idx < len(filtered_lines):
            page_num, text, size, y0 = filtered_lines[idx]
            merged_text = text
            merged_size = size
            next_idx = idx + 1
            if next_idx < len(filtered_lines):
                nxt_page, nxt_text, nxt_size, nxt_y0 = filtered_lines[next_idx]
                same_page = nxt_page == page_num
                close_in_size = abs(nxt_size - size) <= 1.0
                close_in_space = 0.0 <= (nxt_y0 - y0) <= max(8.0, size * 0.9)
                merged_words = _word_count(text) + _word_count(nxt_text)
                if same_page and close_in_size and close_in_space and merged_words <= _MAX_HEADING_WORDS:
                    merged_text = _normalize_text(f"{text} {nxt_text}")
                    merged_size = max(size, nxt_size)
                    idx += 1
            merged.append((page_num, merged_text, merged_size, y0))
            idx += 1

        if not merged:
            return empty

        size_max = max(size for _, _, size, _ in merged)
        chapter_threshold = size_max * 0.92

        topics: list[ExtractedTopic] = []
        for i, (page_num, text, size, _y0) in enumerate(merged):
            level = LEVEL_CHAPTER if size >= chapter_threshold else (
                LEVEL_SECTION if size >= heading_threshold else LEVEL_HEADING
            )
            end_page = merged[i + 1][0] - 1 if i + 1 < len(merged) else None
            topics.append(
                ExtractedTopic(
                    title=text,
                    level=level,
                    confidence=min(0.78, 0.44 + 0.012 * min(len(merged), 18)),
                    start_page=page_num,
                    end_page=end_page,
                )
            )

        pages_with_headings = len({pg for pg, _, _, _ in filtered_lines})
        confidence = min(
            0.78,
            0.30
            + 0.30 * min(pages_with_headings / max(1, pages_to_scan), 1.0)
            + 0.03 * min(len(topics), 8),
        )

        logger.info(
            "LayoutHeadingExtractor: %d topics from %d heading lines; confidence=%.2f",
            len(topics),
            len(filtered_lines),
            confidence,
        )
        return TopicExtractionResult(
            topics=topics,
            method=METHOD_LAYOUT_HEADINGS,
            overall_confidence=confidence,
            debug_info={
                "pages_scanned": pages_to_scan,
                "heading_lines": len(filtered_lines),
                "boilerplate_dropped": len(boilerplate),
                "topics_found": len(topics),
                "median_font_size": round(median_size, 2),
                "heading_threshold": round(heading_threshold, 2),
            },
        )
