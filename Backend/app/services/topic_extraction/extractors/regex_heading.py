"""
RegexHeadingExtractor - heading detection from line-level pattern matching.

Works across many PDFs by scanning plain text for structural patterns:
  * numbered sections
  * labeled sections
  * ALL-CAPS headings
  * short title-case headings with whitespace around them
"""
from __future__ import annotations

import logging
import re
from typing import Any

import fitz  # PyMuPDF

from app.services.topic_extraction.base import (
    LEVEL_CHAPTER,
    LEVEL_HEADING,
    LEVEL_SECTION,
    LEVEL_SUBSECTION,
    METHOD_REGEX_HEADINGS,
    ExtractedTopic,
    TopicExtractionResult,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 300
_MIN_TITLE_LEN = 4
_MAX_TITLE_LEN = 120
_MAX_TITLE_WORDS = 12
_TITLE_CASE_RATIO = 0.60

# "1.2.3  Long Title Goes Here"
_RE_NUMBERED = re.compile(
    r"^(?P<num>\d+(?:\.\d+){0,3})\s{1,4}(?P<title>[A-Z][\w ,\-:()/'\"]+)$",
    re.UNICODE,
)
# "Chapter 3 - Title" / "Section 2: Title" / "Part IV: Title"
_RE_LABELED = re.compile(
    r"^(?P<label>Chapter|Section|Part|Unit|Module|Topic|Lecture)\s+"
    r"(?P<num>[\dIVXivx]+)\s*[:\-.]?\s+(?P<title>.+)$",
    re.IGNORECASE,
)
_RE_ALL_CAPS = re.compile(r"^[A-Z0-9][A-Z0-9 ,:;\-/&()]{8,}$")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'/-]*")


def _count_dots(num_str: str) -> int:
    return num_str.count(".")


def _level_from_depth(depth: int) -> str:
    return {0: LEVEL_CHAPTER, 1: LEVEL_SECTION, 2: LEVEL_SUBSECTION}.get(depth, LEVEL_HEADING)


def _has_blank_context(raw_lines: list[str], idx: int) -> bool:
    prev_blank = idx == 0 or not raw_lines[idx - 1].strip()
    next_blank = idx == len(raw_lines) - 1 or not raw_lines[idx + 1].strip()
    return prev_blank or next_blank


def _looks_like_title_case_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) < _MIN_TITLE_LEN or len(stripped) > _MAX_TITLE_LEN:
        return False
    if stripped.endswith(".") or stripped.endswith(","):
        return False

    words = _WORD_RE.findall(stripped)
    if len(words) < 2 or len(words) > _MAX_TITLE_WORDS:
        return False

    titled = 0
    for word in words:
        if word.isupper() or (word[0].isupper() and (len(word) == 1 or word[1:].islower())):
            titled += 1

    ratio = titled / max(1, len(words))
    return ratio >= _TITLE_CASE_RATIO


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
            raw_text: str = page.get_text("text")  # type: ignore[assignment]
            page_num = page_idx + 1
            raw_lines = raw_text.splitlines()

            for idx, raw_line in enumerate(raw_lines):
                line = raw_line.strip()
                if not line or len(line) < _MIN_TITLE_LEN or len(line) > _MAX_TITLE_LEN:
                    continue

                m = _RE_NUMBERED.match(line)
                if m:
                    hits.append((page_num, "numbered", m.group("num"), m.group("title").strip()))
                    continue

                m = _RE_LABELED.match(line)
                if m:
                    label = m.group("label").capitalize()
                    num = m.group("num")
                    title = m.group("title").strip()
                    hits.append((page_num, "labeled", f"{label} {num}", title))
                    continue

                if _RE_ALL_CAPS.match(line):
                    if re.search(r"https?://|^\d+$|www\.", line, re.I):
                        continue
                    hits.append((page_num, "allcaps", "", line.title()))
                    continue

                if _has_blank_context(raw_lines, idx) and _looks_like_title_case_heading(line):
                    hits.append((page_num, "titlecase", "", line))

        doc.close()

        if not hits:
            return empty

        lotext_pages: dict[str, set[int]] = {}
        for pg, _ptype, _num, title in hits:
            lotext_pages.setdefault(title.lower(), set()).add(pg)
        boilerplate = {
            title
            for title, pgset in lotext_pages.items()
            if len(pgset) >= 3 and len(pgset) / max(1, pages_to_scan) >= 0.28
        }
        hits = [
            (pg, ptype, num, title)
            for pg, ptype, num, title in hits
            if title.lower() not in boilerplate
        ]

        if not hits:
            return empty

        topics: list[ExtractedTopic] = []
        type_counts: dict[str, int] = {
            "numbered": 0,
            "labeled": 0,
            "allcaps": 0,
            "titlecase": 0,
        }

        for i, (pg, ptype, num, title) in enumerate(hits):
            end_page = hits[i + 1][0] - 1 if i + 1 < len(hits) else None

            if ptype == "numbered":
                level = _level_from_depth(_count_dots(num))
            elif ptype == "labeled":
                level = LEVEL_CHAPTER
            elif ptype == "titlecase":
                level = LEVEL_SECTION
            else:
                level = LEVEL_HEADING

            topics.append(
                ExtractedTopic(
                    title=title,
                    level=level,
                    confidence=0.50,
                    start_page=pg,
                    end_page=end_page,
                )
            )
            type_counts[ptype] += 1

        numbered_ratio = type_counts["numbered"] / max(1, len(hits))
        labeled_ratio = type_counts["labeled"] / max(1, len(hits))
        titlecase_ratio = type_counts["titlecase"] / max(1, len(hits))
        base_conf = 0.28
        base_conf += 0.22 * numbered_ratio
        base_conf += 0.15 * labeled_ratio
        base_conf += 0.12 * titlecase_ratio
        base_conf = min(base_conf, 0.74)

        for topic in topics:
            topic.confidence = base_conf

        logger.info(
            "RegexHeadingExtractor: %d topics (numbered=%d labeled=%d allcaps=%d titlecase=%d); conf=%.2f",
            len(topics),
            type_counts["numbered"],
            type_counts["labeled"],
            type_counts["allcaps"],
            type_counts["titlecase"],
            base_conf,
        )
        return TopicExtractionResult(
            topics=topics,
            method=METHOD_REGEX_HEADINGS,
            overall_confidence=base_conf,
            debug_info={
                "pages_scanned": pages_to_scan,
                "boilerplate_dropped": len(boilerplate),
                "topics_found": len(topics),
                **{f"type_{key}": value for key, value in type_counts.items()},
            },
        )
