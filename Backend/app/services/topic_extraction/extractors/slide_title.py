"""
SlideTitleExtractor - detects slide/page titles from the top region of a PDF.

This extractor is designed for slide-style PDFs where each page has a prominent
title near the top, but the embedded outline is too coarse or absent.
"""
from __future__ import annotations

import difflib
import logging
import re
import statistics
from typing import Any

import fitz  # PyMuPDF

from app.services.topic_extraction.base import (
    LEVEL_SECTION,
    METHOD_SLIDE_TITLES,
    ExtractedTopic,
    TopicExtractionResult,
)

logger = logging.getLogger(__name__)

_MIN_PAGES = 5
_MAX_PAGES = 120
_TOP_PAGE_PORTION = 0.25
_MAX_TITLE_WORDS = 12
_MIN_CANDIDATE_COVERAGE = 0.60
_MAX_AVG_WORDS_PER_PAGE = 140.0
_TITLE_SIMILARITY = 0.90
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_COLLAPSE_WS = re.compile(r"\s+")


def _normalize_title(text: str) -> str:
    text = _COLLAPSE_WS.sub(" ", text.strip())
    return text.strip(" .,:;!?-_/\\|()[]{}\"'")


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _has_alpha(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def _looks_like_prose(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.endswith("."):
        return True
    if stripped.endswith("?") and _word_count(stripped) > 8:
        return True
    if "," in stripped and _word_count(stripped) > 7:
        return True
    return False


def _similar_titles(left: str, right: str) -> bool:
    left_norm = _normalize_title(left).lower()
    right_norm = _normalize_title(right).lower()
    if left_norm == right_norm:
        return True
    if not left_norm or not right_norm:
        return False
    return (
        difflib.SequenceMatcher(None, left_norm, right_norm).ratio()
        >= _TITLE_SIMILARITY
    )


def _extract_line_candidates(
    page: fitz.Page,
    *,
    min_size: float,
) -> list[tuple[str, float, float, float]]:
    """
    Return candidate title lines from the top quarter of the page.

    Each tuple is: (text, font_size, y0, y1).
    """
    candidates: list[tuple[str, float, float, float]] = []
    top_cutoff = float(page.rect.height) * _TOP_PAGE_PORTION

    try:
        page_dict: dict[str, Any] = page.get_text(
            "dict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE,
        )
    except Exception:  # noqa: BLE001
        return candidates

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue

            raw_text = " ".join(
                (str(span.get("text") or "")).strip()
                for span in spans
                if str(span.get("text") or "").strip()
            )
            text = _normalize_title(raw_text)
            if not text or not _has_alpha(text):
                continue

            bbox = line.get("bbox") or block.get("bbox") or (0.0, 0.0, 0.0, 0.0)
            y0 = float(bbox[1])
            y1 = float(bbox[3])
            if y0 > top_cutoff:
                continue

            font_size = max(float(span.get("size", 0.0)) for span in spans)
            if font_size < min_size:
                continue

            words = _word_count(text)
            if words == 0 or words > _MAX_TITLE_WORDS:
                continue
            if _looks_like_prose(text):
                continue

            candidates.append((text, font_size, y0, y1))

    return candidates


def _choose_page_title(
    page: fitz.Page,
    *,
    median_font_size: float,
) -> tuple[str, float] | None:
    """Choose the strongest top-of-page title candidate for one page."""
    min_size = max(11.0, median_font_size * 1.15)
    candidates = _extract_line_candidates(page, min_size=min_size)
    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[1], item[2], _word_count(item[0])))

    best_text, best_size, best_y0, best_y1 = candidates[0]
    if len(candidates) > 1:
        nxt_text, nxt_size, nxt_y0, _nxt_y1 = candidates[1]
        combined_words = _word_count(best_text) + _word_count(nxt_text)
        close_in_size = abs(best_size - nxt_size) <= 1.0
        close_in_space = 0.0 <= (nxt_y0 - best_y1) <= max(6.0, best_size * 0.8)
        if close_in_size and close_in_space and combined_words <= _MAX_TITLE_WORDS:
            best_text = _normalize_title(f"{best_text} {nxt_text}")

    return best_text, best_size


class SlideTitleExtractor:
    """Detect slide-like documents and use page titles as topics."""

    name = "slide_titles"

    def extract(
        self,
        file_path: str,
        *,
        chunks: list[Any] | None = None,
    ) -> TopicExtractionResult:
        empty = TopicExtractionResult(
            topics=[],
            method=METHOD_SLIDE_TITLES,
            overall_confidence=0.0,
            debug_info={"reason": "not slide-like"},
        )

        try:
            doc = fitz.open(str(file_path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("SlideTitleExtractor: open failed (%s)", exc)
            empty.debug_info["error"] = str(exc)
            return empty

        total_pages = len(doc)
        if total_pages < _MIN_PAGES or total_pages > _MAX_PAGES:
            doc.close()
            empty.debug_info["reason"] = "page count outside slide range"
            empty.debug_info["total_pages"] = total_pages
            return empty

        all_font_sizes: list[float] = []
        page_word_counts: list[int] = []
        for page_idx in range(total_pages):
            page = doc.load_page(page_idx)
            page_text = str(page.get_text("text") or "")
            page_word_counts.append(_word_count(page_text))
            try:
                page_dict: dict[str, Any] = page.get_text(
                    "dict",
                    flags=fitz.TEXT_PRESERVE_WHITESPACE,
                )
            except Exception:  # noqa: BLE001
                continue
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = float(span.get("size", 0.0))
                        if size > 0:
                            all_font_sizes.append(size)

        if not all_font_sizes:
            doc.close()
            empty.debug_info["reason"] = "no font size data"
            return empty

        median_font_size = statistics.median(all_font_sizes)
        avg_words_per_page = sum(page_word_counts) / max(1, len(page_word_counts))

        page_titles: list[tuple[int, str, float]] = []
        for page_idx in range(total_pages):
            page = doc.load_page(page_idx)
            chosen = _choose_page_title(page, median_font_size=median_font_size)
            if chosen is None:
                continue
            title, font_size = chosen
            page_titles.append((page_idx + 1, title, font_size))

        doc.close()

        candidate_coverage = len(page_titles) / max(1, total_pages)
        avg_title_font = (
            sum(font_size for _, _, font_size in page_titles) / max(1, len(page_titles))
        )
        looks_slide_like = (
            avg_words_per_page <= _MAX_AVG_WORDS_PER_PAGE
            and candidate_coverage >= _MIN_CANDIDATE_COVERAGE
            and avg_title_font >= median_font_size * 1.18
        )
        if not looks_slide_like:
            empty.debug_info.update(
                {
                    "total_pages": total_pages,
                    "avg_words_per_page": round(avg_words_per_page, 2),
                    "candidate_coverage": round(candidate_coverage, 4),
                    "median_font_size": round(median_font_size, 2),
                    "avg_title_font": round(avg_title_font, 2),
                }
            )
            return empty

        filtered_titles = list(page_titles)
        if (
            len(filtered_titles) >= 2
            and filtered_titles[0][0] == 1
            and _word_count(filtered_titles[0][1]) >= 6
            and _normalize_title(filtered_titles[1][1]).lower() == "outline"
        ):
            filtered_titles = filtered_titles[1:]

        filtered_titles = [
            (page_num, title, font_size)
            for page_num, title, font_size in filtered_titles
            if _normalize_title(title).lower() not in {"outline"}
        ]

        topics: list[ExtractedTopic] = []
        current_title: str | None = None
        current_start: int | None = None
        current_end: int | None = None

        for page_num, title, _font_size in filtered_titles:
            if current_title is None:
                current_title = title
                current_start = page_num
                current_end = page_num
                continue

            if page_num == (current_end or page_num) + 1 and _similar_titles(current_title, title):
                current_end = page_num
                continue

            topics.append(
                ExtractedTopic(
                    title=current_title,
                    level=LEVEL_SECTION,
                    confidence=0.82,
                    start_page=current_start,
                    end_page=current_end,
                )
            )
            current_title = title
            current_start = page_num
            current_end = page_num

        if current_title is not None:
            topics.append(
                ExtractedTopic(
                    title=current_title,
                    level=LEVEL_SECTION,
                    confidence=0.82,
                    start_page=current_start,
                    end_page=current_end,
                )
            )

        if not topics:
            empty.debug_info["reason"] = "no slide titles after dedup"
            return empty

        overall_confidence = min(
            0.88,
            0.48
            + 0.22 * candidate_coverage
            + 0.10 * min(1.0, avg_title_font / max(median_font_size, 1.0))
            + 0.08 * min(1.0, len(topics) / max(8, total_pages // 2)),
        )

        logger.info(
            "SlideTitleExtractor: %d topics from %d/%d titled pages; confidence=%.2f",
            len(topics),
            len(page_titles),
            total_pages,
            overall_confidence,
        )
        return TopicExtractionResult(
            topics=topics,
            method=METHOD_SLIDE_TITLES,
            overall_confidence=overall_confidence,
            debug_info={
                "total_pages": total_pages,
                "avg_words_per_page": round(avg_words_per_page, 2),
                "candidate_coverage": round(candidate_coverage, 4),
                "topics_found": len(topics),
                "median_font_size": round(median_font_size, 2),
                "avg_title_font": round(avg_title_font, 2),
            },
        )
