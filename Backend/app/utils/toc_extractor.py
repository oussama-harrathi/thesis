"""
TOC (Table of Contents) extractor for PDF documents.

Strategy (in order of preference)
──────────────────────────────────
1. **PyMuPDF native outline / bookmarks** — fast and perfectly structured when
   the PDF embeds an outline tree (most modern textbooks do).
2. **Text-heuristic TOC page scanning** — looks at the first 20 pages for a
   page that looks like a table of contents and parses its lines.

Both paths return a list of :class:`TocEntry` objects with:

    title       — cleaned, noise-filtered heading text
    level       — "CHAPTER" | "SECTION" | "SUBSECTION"
    page_number — 1-based page number from the TOC, or None

Pure functions — no DB, no I/O side-effects beyond reading the source file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

from app.utils.pdf import ExtractionResult, PageText

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────────────

TopicLevel = Literal["CHAPTER", "SECTION", "SUBSECTION"]


@dataclass
class TocEntry:
    """A single parsed TOC entry."""
    title: str
    level: TopicLevel
    page_number: int | None = None  # 1-based, may be None


# ── Noise patterns ────────────────────────────────────────────────────────────

# Exact lower-cased titles to always discard
_NOISE_EXACT: frozenset[str] = frozenset({
    "contents",
    "table of contents",
    "index",
    "references",
    "bibliography",
    "acknowledgements",
    "acknowledgments",
    "preface",
    "foreword",
    "about the author",
    "copyright",
    "list of figures",
    "list of tables",
    "list of algorithms",
})

# Regex patterns for noise titles
_NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"homework\s+problems?", re.I),
    re.compile(r"practice\s+problems?", re.I),
    re.compile(r"problems?\s+for\s+section", re.I),
    re.compile(r"section\s+practice\s+problems?", re.I),
    re.compile(r"^mcs\s*page?\b", re.I),
    re.compile(r"\bwwd\b"),
    re.compile(r"^[A-Z\s]{1,5}$"),   # "Z", "N", "Z N", "AN" etc.
]

# Trailing dotted leaders + page number e.g. "Probability ...... 47"
_DOTTED_LEADER_RE = re.compile(r"[.\s]{3,}\d{1,4}\s*$")
# Trailing page number (looser match)
_PAGE_NUM_SUFFIX_RE = re.compile(r"[\s.·*]+(\d{1,4})\s*$")


# ── Shared helpers ────────────────────────────────────────────────────────────

def is_noise_title(title: str) -> bool:
    """Return True if *title* is a boilerplate or degenerate topic name."""
    clean = title.strip()
    if not clean:
        return True
    # Strip everything except letters and check meaningful length
    letters_only = re.sub(r"[^a-zA-Z]", "", clean)
    if len(letters_only) < 3:
        return True   # "Z", "N", "42", symbols
    lower = clean.lower()
    if lower in _NOISE_EXACT:
        return True
    for pat in _NOISE_PATTERNS:
        if pat.search(clean):
            return True
    return False


def _strip_trailing_page_number(title: str) -> tuple[str, int | None]:
    """
    Remove trailing page number / dotted leader from a TOC title string.
    Returns (cleaned_title, page_int_or_None).
    """
    m = _PAGE_NUM_SUFFIX_RE.search(title)
    page: int | None = None
    if m:
        try:
            page = int(m.group(1))
        except ValueError:
            pass
        title = title[: m.start()].strip()

    # Remove remaining dotted leader chars
    title = re.sub(r"[.\s]{2,}$", "", title).strip()
    # Collapse internal whitespace
    title = re.sub(r"\s{2,}", " ", title)
    return title, page


# ── Strategy 1: PyMuPDF native outline ───────────────────────────────────────

_LEVEL_MAP: dict[int, TopicLevel] = {
    1: "CHAPTER",
    2: "SECTION",
    3: "SUBSECTION",
}


def extract_toc_from_outline(source: str | Path) -> list[TocEntry]:
    """
    Extract TOC from the PDF's embedded outline/bookmarks via PyMuPDF.

    Returns an empty list if the PDF has no outline or if the file cannot
    be opened.
    """
    entries: list[TocEntry] = []
    try:
        doc = fitz.open(str(source))
        raw_toc = doc.get_toc(simple=True)   # [[level, title, page], ...]
        doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PyMuPDF outline extraction failed (%s): %s", source, exc)
        return entries

    if not raw_toc:
        logger.debug("No bookmarks/outline found in %s", source)
        return entries

    seen_keys: set[str] = set()

    for item in raw_toc:
        if len(item) < 2:
            continue
        level_int: int = int(item[0])
        raw_title: str = str(item[1]).strip()
        page_num: int | None = int(item[2]) if len(item) > 2 and item[2] else None

        cleaned, fallback_page = _strip_trailing_page_number(raw_title)
        if page_num is None:
            page_num = fallback_page

        if is_noise_title(cleaned):
            continue
        if len(cleaned) < 3:
            continue

        level: TopicLevel = _LEVEL_MAP.get(min(level_int, 3), "SUBSECTION")

        key = re.sub(r"\s+", " ", cleaned.lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)

        entries.append(TocEntry(title=cleaned, level=level, page_number=page_num))

    logger.info(
        "TOC outline extraction: %d raw items → %d usable entries",
        len(raw_toc),
        len(entries),
    )
    return entries


# ── Strategy 2: Text-heuristic TOC page scan ──────────────────────────────────

# Lines that signal the beginning of a TOC page
_TOC_HEADER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*(table\s+of\s+)?contents?\s*$", re.I),
    re.compile(r"^\s*list\s+of\s+chapters?\s*$", re.I),
]

# TOC entry line: optional indent, optional section number, title, optional page
_TOC_ENTRY_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?:(?P<num>[\d.]+\.?)\s+)?"
    r"(?P<title>[A-Z][^\n]{2,70}?)"
    r"(?:[\s.·]{2,}(?P<page>\d{1,4}))?\s*$",
)


def _is_toc_page(page: PageText) -> bool:
    """
    Heuristic: does this page look like a Table of Contents page?

    Accepts if:
    - One of the first 5 non-empty lines matches a TOC header, OR
    - ≥ 40 % of non-empty lines carry a dotted-leader + trailing page number
    """
    lines = [ln.strip() for ln in page.text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False

    for line in lines[:5]:
        for pat in _TOC_HEADER_PATTERNS:
            if pat.match(line):
                return True

    # Dotted-leader heuristic
    hit_count = sum(1 for ln in lines if _DOTTED_LEADER_RE.search(ln) or _PAGE_NUM_SUFFIX_RE.search(ln))
    return hit_count / len(lines) >= 0.4


def _parse_toc_page(page: PageText) -> list[TocEntry]:
    """Parse a detected TOC page into TocEntry objects."""
    entries: list[TocEntry] = []
    for raw_line in page.text.splitlines():
        if not raw_line.strip():
            continue

        indent = len(raw_line) - len(raw_line.lstrip())
        line = raw_line.strip()

        m = _TOC_ENTRY_RE.match(line)
        if m is None:
            continue

        raw_title: str = (m.group("title") or "").strip()
        page_str: str | None = m.group("page")

        cleaned, fallback_page = _strip_trailing_page_number(raw_title)
        if is_noise_title(cleaned):
            continue
        if len(cleaned) < 3:
            continue

        page_num: int | None = None
        if page_str:
            try:
                page_num = int(page_str)
            except ValueError:
                pass
        if page_num is None:
            page_num = fallback_page

        # Assign level from indentation depth
        if indent <= 2:
            level: TopicLevel = "CHAPTER"
        elif indent <= 5:
            level = "SECTION"
        else:
            level = "SUBSECTION"

        entries.append(TocEntry(title=cleaned, level=level, page_number=page_num))

    return entries


def extract_toc_from_text(extraction: ExtractionResult) -> list[TocEntry]:
    """
    Scan the first 20 pages of the extraction result for a TOC page, then
    parse its lines into TocEntry objects.

    Returns an empty list if no TOC page is detected.
    """
    entries: list[TocEntry] = []
    candidate_pages = [p for p in extraction.pages[:20] if _is_toc_page(p)]

    for page in candidate_pages:
        page_entries = _parse_toc_page(page)
        if page_entries:
            entries.extend(page_entries)
            # Typically a single TOC spans one or two pages — stop after first hit
            break

    # Deduplicate by normalised title
    seen: set[str] = set()
    deduped: list[TocEntry] = []
    for e in entries:
        key = re.sub(r"\s+", " ", e.title.lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    logger.info(
        "TOC text-heuristic extraction: %d usable entries from %d candidate pages",
        len(deduped),
        len(candidate_pages),
    )
    return deduped


# ── Unified entry point ───────────────────────────────────────────────────────

def extract_toc(source: str | Path, extraction: ExtractionResult) -> list[TocEntry]:
    """
    Try PDF outline extraction first; fall back to text-heuristic if that
    yields no results.

    Parameters
    ----------
    source     : Path to the PDF file.
    extraction : Already-computed ExtractionResult (avoids re-opening the PDF).

    Returns
    -------
    Possibly-empty list of TocEntry objects.
    """
    entries = extract_toc_from_outline(source)
    if entries:
        logger.info("TOC: using %d outline entries", len(entries))
        return entries

    entries = extract_toc_from_text(extraction)
    if entries:
        logger.info("TOC: using %d text-heuristic entries", len(entries))
    else:
        logger.info("TOC: no entries found in outline or text heuristic")
    return entries
