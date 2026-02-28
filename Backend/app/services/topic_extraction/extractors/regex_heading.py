"""
RegexHeadingExtractor — heading detection from line-level pattern matching.

Works across nearly any PDF by scanning each page's plain text for
structural patterns:
  • Numbered sections:  "1  Introduction", "1.2 Background", "3.4.1 Details"
  • Labeled sections:   "Chapter 3:", "Section 4:", "Part II:"
  • ALL-CAPS short lines (slide / note headings)
  • Title-cased lines that follow a blank line (less reliable, lower weight)
"""
from __future__ import annotations

import logging
import re
from typing import Any

import fitz  # PyMuPDF

from app.services.topic_extraction.base import (
    METHOD_REGEX_HEADINGS,
    LEVEL_CHAPTER,
    LEVEL_SECTION,
    LEVEL_SUBSECTION,
    LEVEL_HEADING,
    ExtractedTopic,
    TopicExtractionResult,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 300
_MIN_TITLE_LEN = 4
_MAX_TITLE_LEN = 120

# -----------------------------------------------------------------
# Compiled patterns
# -----------------------------------------------------------------
# "1.2.3  Long Title Goes Here" – numbered hierarchical
_RE_NUMBERED = re.compile(
    r"^(?P<num>\d+(?:\.\d+){0,3})\s{1,4}(?P<title>[A-Z][\w ,\-:()/'\"]+)$",
    re.UNICODE,
)
# "Chapter 3 — Title" / "Section 2: Title" / "Part IV: Title"
_RE_LABELED = re.compile(
    r"^(?P<label>Chapter|Section|Part|Unit|Module|Topic|Lecture)\s+"
    r"(?P<num>[\dIVXivx]+)\s*[:\-–—.]?\s+(?P<title>.+)$",
    re.IGNORECASE,
)
# ALL-CAPS line (slide title style): at least 3 words
_RE_ALL_CAPS = re.compile(r"^[A-Z0-9][A-Z0-9 ,:;\-/&()]{8,}$")


def _count_dots(num_str: str) -> int:
    return num_str.count(".")


def _level_from_depth(depth: int) -> str:
    return {0: LEVEL_CHAPTER, 1: LEVEL_SECTION, 2: LEVEL_SUBSECTION}.get(depth, LEVEL_HEADING)


class RegexHeadingExtractor:
    """Regex / pattern-based heading extractor (no font metadata required)."""

    name = "regex_headings"

    def extract(
        self,
        file_path: str,
        *,
        chunks: list[Any] | None = None,
    ) -> TopicExtractionResult:
        empty = TopicExtractionResult(
            topics=[],
            method=METHOD_REGEX_HEADINGS,
            overall_confidence=0.0,
            debug_info={"reason": "no regex headings found"},
        )

        try:
            doc = fitz.open(str(file_path))
            total_pages = len(doc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RegexHeadingExtractor: open failed (%s)", exc)
            empty.debug_info["error"] = str(exc)
            return empty

        pages_to_scan = min(total_pages, _MAX_PAGES)
        hits: list[tuple[int, str, str, str]] = []  # (page, pattern_type, number, title)

        for page_idx in range(pages_to_scan):
            page = doc.load_page(page_idx)
            raw: str = page.get_text("text")  # type: ignore[assignment]
            page_num = page_idx + 1
            for line in raw.splitlines():
                line = line.strip()
                if not line or len(line) < _MIN_TITLE_LEN or len(line) > _MAX_TITLE_LEN:
                    continue

                # --- numbered section ---
                m = _RE_NUMBERED.match(line)
                if m:
                    hits.append((page_num, "numbered", m.group("num"), m.group("title").strip()))
                    continue

                # --- labeled heading ---
                m = _RE_LABELED.match(line)
                if m:
                    label = m.group("label").capitalize()
                    num = m.group("num")
                    title = m.group("title").strip()
                    hits.append((page_num, "labeled", f"{label} {num}", title))
                    continue

                # --- ALL-CAPS ---
                if _RE_ALL_CAPS.match(line):
                    # exclude if it looks like a running footer (page number, URLs…)
                    if re.search(r"https?://|^\d+$|www\.", line, re.I):
                        continue
                    hits.append((page_num, "allcaps", "", line.title()))

        doc.close()

        if not hits:
            return empty

        # -----------------------------------------------------------------
        # Remove boilerplate: text appearing on > 30% of pages
        # -----------------------------------------------------------------
        lotext_pages: dict[str, set[int]] = {}
        for pg, _, _, title in hits:
            lotext_pages.setdefault(title.lower(), set()).add(pg)
        boilerplate = {t for t, pgset in lotext_pages.items() if len(pgset) / pages_to_scan >= 0.28}
        hits = [(pg, pt, num, title) for pg, pt, num, title in hits if title.lower() not in boilerplate]

        if not hits:
            return empty

        # -----------------------------------------------------------------
        # Build ExtractedTopic list
        # -----------------------------------------------------------------
        topics: list[ExtractedTopic] = []
        type_counts: dict[str, int] = {"numbered": 0, "labeled": 0, "allcaps": 0}

        for i, (pg, ptype, num, title) in enumerate(hits):
            end_pg: int | None = hits[i + 1][0] - 1 if i + 1 < len(hits) else None

            if ptype == "numbered":
                depth = _count_dots(num)
                level = _level_from_depth(depth)
            elif ptype == "labeled":
                level = LEVEL_CHAPTER
            else:
                level = LEVEL_HEADING

            topics.append(
                ExtractedTopic(
                    title=title,
                    level=level,
                    confidence=0.50,  # refined below
                    start_page=pg,
                    end_page=end_pg,
                )
            )
            type_counts[ptype] += 1

        # -----------------------------------------------------------------
        # Overall confidence: reward consistent numbering
        # -----------------------------------------------------------------
        numbered_ratio = type_counts["numbered"] / max(1, len(hits))
        labeled_ratio = type_counts["labeled"] / max(1, len(hits))
        base_conf = 0.30
        base_conf += 0.20 * numbered_ratio  # numbered is very reliable
        base_conf += 0.15 * labeled_ratio    # labeled is reliable
        base_conf = min(base_conf, 0.72)

        # update per-topic confidence proportionally
        for t in topics:
            t.confidence = base_conf

        logger.info(
            "RegexHeadingExtractor: %d topics (numbered=%d labeled=%d allcaps=%d); conf=%.2f",
            len(topics), type_counts["numbered"], type_counts["labeled"], type_counts["allcaps"], base_conf,
        )
        return TopicExtractionResult(
            topics=topics,
            method=METHOD_REGEX_HEADINGS,
            overall_confidence=base_conf,
            debug_info={
                "pages_scanned": pages_to_scan,
                "hits_raw": len(hits) + len(boilerplate),
                "boilerplate_dropped": len(boilerplate),
                "topics_found": len(topics),
                **{f"type_{k}": v for k, v in type_counts.items()},
            },
        )
