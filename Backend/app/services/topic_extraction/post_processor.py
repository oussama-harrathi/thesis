"""
TopicPostProcessor — cleans, deduplicates, and filters extracted topics.

Chained steps:
 1. normalize_title      — strip noise chars, trailing page numbers, collapse whitespace
 2. filter_noise         — remove boilerplate / structural noise
 3. filter_too_short     — < 4 meaningful chars after normalization
 4. deduplicate          — exact match first, then near-dedup (sequence similarity)
 5. enforce_count        — if > MAX_TOPICS keep by confidence;
                            if remaining < MIN_TOPICS signal failure
"""
from __future__ import annotations

import difflib
import logging
import re
import unicodedata

from app.services.topic_extraction.base import ExtractedTopic

logger = logging.getLogger(__name__)

_MIN_TOPICS = 2
_MAX_TOPICS = 25
_NEAR_DEDUP_RATIO = 0.82  # difflib SequenceMatcher threshold

# ----------------------------------------------------------------
# Noise patterns — case-insensitive, full-match
# ----------------------------------------------------------------
_NOISE_EXACT: frozenset[str] = frozenset({
    "introduction", "conclusions", "summary", "preface",
    "acknowledgements", "acknowledgments", "contents", "table of contents",
    "bibliography", "references", "index", "appendix", "glossary",
    "list of figures", "list of tables", "abstract", "foreword",
    "further reading", "answers", "solutions", "footnotes",
    "copyright", "license", "all rights reserved",
    "page", "slide", "figure", "table", "equation",
    # Note: "conclusion", "overview", "exercises", "problems", "review questions",
    # "notes" removed — they can be legitimate section headings in some documents.
})

_NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^ch(apter)?\s*\d+\s*$", re.I),          # "Chapter 7"
    re.compile(r"^section\s*\d+(\.\d+)*\s*$", re.I),      # "Section 3.2"
    re.compile(r"^part\s+(i{1,3}v?|vi{0,3}|\d+)\s*$", re.I),
    re.compile(r"^\d+(\.\d+)*\s*$"),                       # bare number "3.2"
    re.compile(r"^[^a-z]{0,2}[a-z]?[^a-z]{0,2}$", re.I), # 1-3 non-alpha chars
    re.compile(r"^[\W_]+$"),                                # symbols only
    re.compile(r"^\d{1,4}\s*$"),                           # standalone numbers
    re.compile(r"^https?://", re.I),
    re.compile(r"^www\.", re.I),
    re.compile(r"^slide\s*\d+", re.I),
    re.compile(r"^page\s*\d+", re.I),
    re.compile(r"copyright|©|\(c\)\s*\d{4}", re.I),
]

_TRAILING_PAGE_NUM = re.compile(r"\s+\d{1,4}$")
_LEADING_NUMBERING = re.compile(r"^(\d+(\.\d+)*|[IVXLC]+\.?)\s+", re.I)
_SLIDE_PREFIX = re.compile(r"^slide\s*\d+\s*[:\-–]?\s*", re.I)
_COLLAPSE_WS = re.compile(r"\s{2,}")


# ----------------------------------------------------------------
# Functions
# ----------------------------------------------------------------

def _normalize(title: str) -> str:
    # Unicode normalize
    title = unicodedata.normalize("NFKC", title)
    # Remove trailing page number
    title = _TRAILING_PAGE_NUM.sub("", title)
    # Strip leading numbering ("1.2 " or "IV ")
    title = _LEADING_NUMBERING.sub("", title).strip()
    # Strip "Slide 10:" prefix common in slide-deck PDFs
    title = _SLIDE_PREFIX.sub("", title).strip()
    # Collapse internal whitespace
    title = _COLLAPSE_WS.sub(" ", title).strip()
    # Strip surrounding punctuation/symbols
    title = title.strip(".-–—:;,!?\"'()[]{}")
    return title


def _is_noise(title: str) -> bool:
    lo = title.lower().strip()
    if lo in _NOISE_EXACT:
        return True
    for pat in _NOISE_PATTERNS:
        if pat.search(lo):
            return True
    return False


def _near_dedup(
    topics: list[ExtractedTopic],
    ratio: float = _NEAR_DEDUP_RATIO,
) -> list[ExtractedTopic]:
    """Remove near-duplicate topics; keep the higher-confidence one."""
    kept: list[ExtractedTopic] = []
    for candidate in sorted(topics, key=lambda t: t.confidence, reverse=True):
        is_dup = False
        for existing in kept:
            r = difflib.SequenceMatcher(None, candidate.title.lower(), existing.title.lower()).ratio()
            if r >= ratio:
                is_dup = True
                break
        if not is_dup:
            kept.append(candidate)
    # Restore original ordering by start_page
    kept.sort(key=lambda t: (t.start_page or 999999, t.title))
    return kept


class TopicPostProcessor:
    """Applies a deterministic cleaning pipeline to extracted topics."""

    def process(self, topics: list[ExtractedTopic]) -> list[ExtractedTopic]:
        if not topics:
            return topics

        result: list[ExtractedTopic] = []

        for t in topics:
            norm = _normalize(t.title)
            if not norm or len(norm) < 3:   # allow 3-char titles (e.g. "ANN", "MLP")
                continue
            if _is_noise(norm):
                continue
            # Return a copy with the normalized title
            result.append(
                ExtractedTopic(
                    title=norm,
                    level=t.level,
                    confidence=t.confidence,
                    start_page=t.start_page,
                    end_page=t.end_page,
                    parent_ref=t.parent_ref,
                    meta=t.meta,
                )
            )

        # Near-dedup
        result = _near_dedup(result)

        # Cap at max
        if len(result) > _MAX_TOPICS:
            result = sorted(result, key=lambda t: t.confidence, reverse=True)[:_MAX_TOPICS]
            result.sort(key=lambda t: (t.start_page or 999999, t.title))

        # ── Escape hatch ──────────────────────────────────────────────────────
        # If ALL candidates were filtered (overly aggressive noise matched the
        # whole PDF outline), fall back to applying only the absolute minimum
        # checks: nonempty string with at least 3 chars that isn't purely
        # symbolic / numeric.  This ensures we always return *something* for
        # PDFs that have a valid outline but generic-sounding section names.
        if not result and topics:
            logger.warning(
                "TopicPostProcessor: full filter removed all %d topics — "
                "applying minimal fallback filter",
                len(topics),
            )
            _MINIMAL_BAD = re.compile(
                r"^[\W\d_]+$"          # purely non-alphabetic
                r"|^https?://"         # URLs
                r"|copyright|©",
                re.IGNORECASE,
            )
            fallback: list[ExtractedTopic] = []
            for t in topics:
                norm = _normalize(t.title)
                if not norm or len(norm) < 3:
                    continue
                if _MINIMAL_BAD.search(norm):
                    continue
                fallback.append(
                    ExtractedTopic(
                        title=norm,
                        level=t.level,
                        confidence=t.confidence,
                        start_page=t.start_page,
                        end_page=t.end_page,
                        parent_ref=t.parent_ref,
                        meta=t.meta,
                    )
                )
            result = _near_dedup(fallback)
            if result:
                logger.info(
                    "TopicPostProcessor: fallback filter retained %d topics",
                    len(result),
                )

        return result
