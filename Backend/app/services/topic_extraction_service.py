"""
TopicExtractionService — TOC-first, heuristic-fallback topic extraction.

Strategy
────────
1.  **TOC extraction (primary)**: If the PDF source path and extraction result
    are supplied, the service attempts to read the PDF's built-in outline /
    bookmarks (PyMuPDF), then falls back to text-heuristic TOC page scanning.
    TOC entries are naturally hierarchical (CHAPTER → SECTION → SUBSECTION)
    and are stored with ``source="TOC"`` and a non-null ``level``.

2.  **Heuristic extraction (fallback)**: When TOC extraction yields no results,
    the original heading-detection + n-gram frequency approach is used.
    Extracted topics are stored with ``source="AUTO"`` and ``level=None``.

Noise filtering
───────────────
All candidates pass through ``_is_topic_noise()``, which rejects:
    • Boilerplate titles: "Homework Problems", "Practice Problems",
      "Problems for Section", "Mcs Page", "WWD", "Chapter", "Section", …
    • Degenerate tokens: "Z", "N", "Z N", single symbols, < 3 letters

Coverage scoring
────────────────
After building TopicChunkMap rows, a ``coverage_score`` is computed per topic::

    coverage_score = chunks_with_nonzero_relevance / max(1, total_chunks)

Topic hierarchy (TOC only)
──────────────────────────
    CHAPTER  (parent=None)
      └─ SECTION  (parent=Chapter)
           └─ SUBSECTION  (parent=Section)

``parent_topic_id`` is set on SECTION/SUBSECTION topics after all topic rows
are flushed so their IDs are available.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.topic import Topic, TopicChunkMap
from app.utils.toc_extractor import (
    TocEntry,
    TopicLevel,
    extract_toc,
    is_noise_title,
)

logger = logging.getLogger(__name__)

# ── tuneable constants ────────────────────────────────────────────────────────

MIN_TOPICS: int = 5
MAX_TOPICS: int = 25  # increased — we want fine-grained subtopics

# Heading: 3–80 chars, must not end with these punctuation chars.
_HEADING_MAX_LEN = 80
_HEADING_MIN_LEN = 3
_HEADING_BAD_ENDINGS = re.compile(r"[.,;]\s*$")

# Numbered section e.g. "1.", "1.2.", "1.2.3 "
_NUMBERED_HEADING = re.compile(r"^(\d+\.)+(\d+)?\s+[A-Z]")
# Common structural keywords
_KEYWORD_HEADING = re.compile(
    r"^(Chapter|Section|Unit|Lecture|Topic|Part|Module|Appendix)\s*[\d:–\-]",
    re.IGNORECASE,
)
# ALL-CAPS (at least 3 uppercase letters, optional spaces)
_ALL_CAPS = re.compile(r"^[A-Z][A-Z\s\-/]{2,}$")
# Title-case: first letter capital, mostly letters & spaces (no digit-start)
_TITLE_CASE = re.compile(r"^[A-Z][a-zA-Z\s\-/:()']{2,}$")

# Strip numbering/bullet prefixes before storing a topic name
_STRIP_PREFIX = re.compile(r"^[\d.\-–•*]+\s*")

# Bare structural labels with no subtitle — discard as topics.
# Matches: "Chapter 7", "Section 3.2", "Lecture 10", etc.
_BARE_STRUCTURAL = re.compile(
    r"^(Chapter|Section|Unit|Lecture|Topic|Part|Module|Appendix)\s*[\d.\-–]*\s*$",
    re.IGNORECASE,
)

# Compound heading: extract the subtitle after ":" or "-" / "–"
# e.g. "Chapter 7: Induction Hypothesis"  →  "Induction Hypothesis"
_COMPOUND_SEPARATOR = re.compile(r"[:\-–]\s*(.+)$")

# ── extra service-level noise patterns ───────────────────────────────────────
# (supplements is_noise_title from toc_extractor)

_EXTRA_NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^page\s*\d*$", re.I),
    re.compile(r"^chapter\s*$", re.I),
    re.compile(r"^section\s*$", re.I),
    re.compile(r"^part\s*$", re.I),
    re.compile(r"^mcs\s+page\s+\d", re.I),  # "Mcs Page 42"
]


def _is_topic_noise(name: str) -> bool:
    """
    Return True if *name* is a degenerate / boilerplate topic that should be
    discarded.  Combines the shared ``is_noise_title`` check (from
    ``toc_extractor``) with service-level extra patterns.
    """
    if is_noise_title(name):
        return True
    for pat in _EXTRA_NOISE_PATTERNS:
        if pat.search(name.strip()):
            return True
    return False


# ── structured topic dataclass ────────────────────────────────────────────────

@dataclass
class _StructuredTopic:
    """Intermediate representation before DB persistence."""
    name: str
    level: TopicLevel | None   # "CHAPTER" | "SECTION" | "SUBSECTION" | None
    source: str                # "TOC" | "AUTO"
    parent_key: str | None     # normalised lower-cased name of parent, or None


# ── stopwords ─────────────────────────────────────────────────────────────────

_STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all also am an and any are as at be
    because been before being between both but by can cannot could did do
    does doing down during each few for from further get got had has have
    having he her here him his how i if in into is it its itself let me
    more most my no nor not now of off on once only or other our out over
    own per same she should so some such than that the their them then
    there these they this those through to under until up us was we were
    what when where which while who will with would you your
    """.split()
)

_TOKENISE = re.compile(r"[a-zA-Z]{3,}")  # words of >= 3 letters


# ── helpers ───────────────────────────────────────────────────────────────────


def _normalise(name: str) -> str:
    """Strip numeric prefix, collapse whitespace, title-case."""
    name = _STRIP_PREFIX.sub("", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name.title()


def _extract_subtitle(line: str) -> str | None:
    """
    For structural keyword headings (Chapter/Section/…), return only the
    descriptive subtitle, or None if the line is a bare structural label.

    Examples:
      "Chapter 7"                         → None  (bare — discard)
      "Chapter 7: Induction Hypothesis"   → "Induction Hypothesis"
      "Section 3.2 – Bayes' Theorem"      → "Bayes' Theorem"
      "Probability Theory"                → "Probability Theory"  (not structural)
    """
    stripped = line.strip()
    # Pure structural label with no subtitle — discard
    if _BARE_STRUCTURAL.match(stripped):
        return None
    # Structural keyword followed by a subtitle after ":" / "-" / "–"
    if _KEYWORD_HEADING.match(stripped):
        m = _COMPOUND_SEPARATOR.search(stripped)
        if m:
            subtitle = m.group(1).strip()
            if len(subtitle) >= _HEADING_MIN_LEN:
                return subtitle
        # Has the keyword prefix but no recognisable subtitle
        return None
    # Not a structural keyword line — keep as-is
    return line


def _is_meaningful(tokens: list[str]) -> bool:
    """Return True if at least one token is not a stopword."""
    return any(t.lower() not in _STOPWORDS for t in tokens)


def _collect_headings(text: str) -> list[str]:
    """Return all heading-like lines from a block of text."""
    candidates: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not (_HEADING_MIN_LEN <= len(line) <= _HEADING_MAX_LEN):
            continue
        if _HEADING_BAD_ENDINGS.search(line):
            continue

        if _KEYWORD_HEADING.match(line):
            # Extract subtitle from "Chapter 7: Induction Hypothesis" style headings.
            # Bare labels like "Chapter 7" are discarded (returns None).
            subtitle = _extract_subtitle(line)
            if subtitle:
                candidates.append(subtitle)
        elif _NUMBERED_HEADING.match(line):
            # Strip the numeric prefix and keep the title portion
            stripped = _STRIP_PREFIX.sub("", line).strip()
            if len(stripped) >= _HEADING_MIN_LEN:
                candidates.append(stripped)
        elif _ALL_CAPS.match(line) or _TITLE_CASE.match(line):
            candidates.append(line)

    return candidates


def _collect_ngrams(text: str, n: int) -> list[tuple[str, ...]]:
    """Return all lowercase n-grams (no stopword boundaries)."""
    tokens = _TOKENISE.findall(text.lower())
    ngrams: list[tuple[str, ...]] = []
    for i in range(len(tokens) - n + 1):
        gram = tuple(tokens[i : i + n])
        # Reject if first or last token is a stopword
        if gram[0] in _STOPWORDS or gram[-1] in _STOPWORDS:
            continue
        ngrams.append(gram)
    return ngrams


def _deduplicate(topics: list[str]) -> list[str]:
    """
    Remove exact duplicates and substring-contained duplicates.
    When two topics where one contains the other, keep the longer one
    (more specific is usually better).
    """
    seen: list[str] = []
    lowered = [t.lower() for t in topics]
    for i, topic in enumerate(topics):
        low = lowered[i]
        dominated = any(
            low != lowered[j] and low in lowered[j]
            for j in range(len(topics))
        )
        if dominated:
            continue  # a longer more-specific version exists
        if not any(low == lowered[j] for j in range(i)):  # no exact dup
            seen.append(topic)
    return seen


# ── main service ──────────────────────────────────────────────────────────────


class TopicExtractionService:
    """
    TOC-first, heuristic-fallback topic extractor for course chunks.

    Public API
    ──────────
    extract_topic_names(chunks)                        -> list[str]
    compute_chunk_relevance(name, chunk)               -> float
    save_topics(db, course_id, chunks, *, source_path, extraction) -> list[Topic]
    """

    # ── extraction ────────────────────────────────────────────────

    def extract_topic_names(
        self,
        chunks: Sequence[Chunk],
        *,
        min_topics: int = MIN_TOPICS,
        max_topics: int = MAX_TOPICS,
    ) -> list[str]:
        """
        Run heuristic extraction and return a deduplicated, normalised list
        of topic name strings (between *min_topics* and *max_topics* items).

        Parameters
        ----------
        chunks      : Sequence of persisted Chunk ORM objects.
        min_topics  : Minimum number of results to return (soft lower bound —
                      may return fewer if the material has very little text).
        max_topics  : Hard upper bound.
        """
        if not chunks:
            logger.warning("extract_topic_names called with no chunks")
            return []

        heading_candidates: list[str] = []
        bigram_counter: Counter[tuple[str, ...]] = Counter()
        trigram_counter: Counter[tuple[str, ...]] = Counter()

        for chunk in chunks:
            text = chunk.content or ""
            heading_candidates.extend(_collect_headings(text))
            bigram_counter.update(_collect_ngrams(text, 2))
            trigram_counter.update(_collect_ngrams(text, 3))

        # ── score headings ─────────────────────────────────────────
        heading_scores: Counter[str] = Counter()
        for h in heading_candidates:
            norm = _normalise(h)
            if not norm or len(norm) < _HEADING_MIN_LEN:
                continue
            if _is_topic_noise(norm):
                continue
            heading_scores[norm] += 1  # count repetitions across chunks

        # ── score key-phrases ──────────────────────────────────────
        keyphrase_scores: dict[str, float] = {}

        def _score_ngram(gram: tuple[str, ...], freq: int) -> float:
            avg_len = sum(len(w) for w in gram) / len(gram)
            return freq * (avg_len ** 2)

        for gram, freq in trigram_counter.most_common(60):
            words = list(gram)
            if not _is_meaningful(words):
                continue
            phrase = _normalise(" ".join(words))
            if _is_topic_noise(phrase):
                continue
            keyphrase_scores[phrase] = max(
                keyphrase_scores.get(phrase, 0.0),
                _score_ngram(gram, freq),
            )

        for gram, freq in bigram_counter.most_common(80):
            words = list(gram)
            if not _is_meaningful(words):
                continue
            phrase = _normalise(" ".join(words))
            if _is_topic_noise(phrase):
                continue
            # Only use bigram if no trigram already covered it
            already_covered = any(phrase.lower() in k.lower() for k in keyphrase_scores)
            if not already_covered:
                keyphrase_scores[phrase] = max(
                    keyphrase_scores.get(phrase, 0.0),
                    _score_ngram(gram, freq),
                )

        # ── merge: headings first (higher trust), then keyphrases ──
        # Headings sorted by repetition count descending
        ordered: list[str] = [
            name for name, _ in heading_scores.most_common(max_topics)
        ]

        # Fill remaining slots with highest-scoring key-phrases
        keyphrase_ranked = sorted(
            keyphrase_scores.items(), key=lambda kv: kv[1], reverse=True
        )
        for phrase, _ in keyphrase_ranked:
            if len(ordered) >= max_topics * 2:  # gather extras before dedup
                break
            if phrase not in ordered:
                ordered.append(phrase)

        # ── deduplicate ────────────────────────────────────────────
        deduped = _deduplicate(ordered)

        # ── trim to range ──────────────────────────────────────────
        result = deduped[:max_topics]
        logger.info(
            "extract_topic_names: %d candidates → %d deduplicated → returning %d",
            len(ordered),
            len(deduped),
            len(result),
        )
        return result

    # ── TOC → _StructuredTopic conversion ────────────────────────

    def _structured_topics_from_toc(
        self,
        entries: list[TocEntry],
        max_topics: int = MAX_TOPICS,
    ) -> list[_StructuredTopic]:
        """
        Convert a list of TocEntry objects into _StructuredTopic objects with
        parent linkage resolved by level.

        Level hierarchy:
            CHAPTER  → parent = None
            SECTION  → parent = most recent CHAPTER
            SUBSECTION → parent = most recent SECTION (or CHAPTER if no SECTION)
        """
        results: list[_StructuredTopic] = []
        last_key_at: dict[str, str | None] = {
            "CHAPTER": None,
            "SECTION": None,
            "SUBSECTION": None,
        }
        seen_keys: set[str] = set()

        for entry in entries:
            name = entry.title.strip()
            norm = _normalise(name)
            if _is_topic_noise(norm):
                continue
            key = re.sub(r"\s+", " ", norm.lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)

            level = entry.level  # "CHAPTER" | "SECTION" | "SUBSECTION"

            if level == "CHAPTER":
                parent_key = None
                last_key_at["CHAPTER"] = key
                last_key_at["SECTION"] = None
                last_key_at["SUBSECTION"] = None
            elif level == "SECTION":
                parent_key = last_key_at["CHAPTER"]
                last_key_at["SECTION"] = key
                last_key_at["SUBSECTION"] = None
            else:  # SUBSECTION
                parent_key = last_key_at["SECTION"] or last_key_at["CHAPTER"]
                last_key_at["SUBSECTION"] = key

            results.append(
                _StructuredTopic(
                    name=norm,
                    level=level,
                    source="TOC",
                    parent_key=parent_key,
                )
            )
            if len(results) >= max_topics:
                break

        logger.info(
            "_structured_topics_from_toc: %d TOC entries → %d structured topics",
            len(entries),
            len(results),
        )
        return results

    def _structured_topics_from_heuristic(
        self,
        chunks: Sequence[Chunk],
        min_topics: int = MIN_TOPICS,
        max_topics: int = MAX_TOPICS,
    ) -> list[_StructuredTopic]:
        """Wrap heuristic extraction result in _StructuredTopic objects (no hierarchy)."""
        names = self.extract_topic_names(
            chunks, min_topics=min_topics, max_topics=max_topics
        )
        return [
            _StructuredTopic(name=n, level=None, source="AUTO", parent_key=None)
            for n in names
        ]

    # ── relevance scoring ─────────────────────────────────────────

    def compute_chunk_relevance(self, topic_name: str, chunk: Chunk) -> float:
        """
        Compute a raw relevance score for a (topic, chunk) pair.

        Algorithm
        ─────────
        1. Count case-insensitive occurrences of the topic phrase in the
           chunk text (term frequency).
        2. Normalise by chunk token count to avoid length bias.
        3. Apply a 2× heading boost if the first non-empty line of the chunk
           contains the topic phrase.

        Returns a float ≥ 0.  Scores across chunks for the same topic are
        normalised to [0, 1] by the caller (save_topics).
        """
        text = chunk.content or ""
        if not text.strip():
            return 0.0

        needle = topic_name.lower()
        haystack = text.lower()

        # Term frequency (non-overlapping)
        tf = len(re.findall(re.escape(needle), haystack))
        if tf == 0:
            return 0.0

        token_count = max(1, len(_TOKENISE.findall(text)))
        score = tf / token_count

        # Heading boost: topic phrase appears within the first 120 chars
        if needle in haystack[:120]:
            score *= 2.0

        return score

    def _normalise_scores(self, scores: list[float]) -> list[float]:
        """Min-max normalise a list of scores to [0, 1]."""
        max_score = max(scores) if scores else 0.0
        if max_score == 0.0:
            return [0.0] * len(scores)
        return [s / max_score for s in scores]

    def _compute_coverage_score(
        self, mapped_chunk_count: int, total_chunks: int
    ) -> float:
        """
        coverage_score = chunks_with_nonzero_relevance / max(1, total_chunks).
        Stored as a value in [0, 1].
        """
        if total_chunks == 0:
            return 0.0
        return round(mapped_chunk_count / total_chunks, 6)

    # ── persistence ───────────────────────────────────────────────

    def save_topics(
        self,
        db: Session,
        course_id: uuid.UUID,
        chunks: Sequence[Chunk],
        *,
        source_path: str | None = None,
        extraction: object | None = None,  # ExtractionResult from pdf.py
        min_topics: int = MIN_TOPICS,
        max_topics: int = MAX_TOPICS,
        relevance_threshold: float = 0.0,
    ) -> list[Topic]:
        """
        Extract topics from *chunks* (and optionally the PDF), persist them
        as Topic rows with hierarchy, and build TopicChunkMap entries with
        normalised relevance scores and coverage scores.

        Strategy
        ────────
        1. If *source_path* and *extraction* are given, attempt TOC extraction
           (PDF outline → text-heuristic TOC page scan).
        2. If TOC extraction yields results, use them (``source="TOC"``).
        3. Otherwise fall back to the heuristic n-gram / heading approach
           (``source="AUTO"``).

        Parameters
        ----------
        db                  : Synchronous SQLAlchemy session (Celery worker).
        course_id           : UUID of the owning Course.
        chunks              : Persisted Chunk rows for the document.
        source_path         : Path to the PDF — enables TOC extraction.
        extraction          : ExtractionResult — enables text-heuristic TOC.
        min_topics          : Soft lower bound (heuristic fallback only).
        max_topics          : Hard upper bound.
        relevance_threshold : Skip TopicChunkMap rows at or below this score.

        Returns
        -------
        List of persisted Topic ORM objects.
        """
        # ── Step 1: choose extraction strategy ───────────────────
        structured: list[_StructuredTopic] = []

        if source_path and extraction is not None:
            try:
                toc_entries = extract_toc(Path(source_path), extraction)  # type: ignore[arg-type]
                if toc_entries:
                    structured = self._structured_topics_from_toc(
                        toc_entries, max_topics=max_topics
                    )
                    logger.info(
                        "save_topics: TOC strategy yielded %d topics for course %s",
                        len(structured),
                        course_id,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "save_topics: TOC extraction raised %s — falling back to heuristic",
                    exc,
                )

        if not structured:
            logger.info(
                "save_topics: heuristic strategy for course %s", course_id
            )
            structured = self._structured_topics_from_heuristic(
                chunks, min_topics=min_topics, max_topics=max_topics
            )

        if not structured:
            logger.warning(
                "save_topics: no topics extracted for course %s", course_id
            )
            return []

        # ── Step 2: first pass — create Topic rows ────────────────
        # Build all rows before wiring parent_topic_id (needs IDs).
        key_to_topic: dict[str, Topic] = {}
        saved_topics: list[Topic] = []

        for st in structured:
            name_key = re.sub(r"\s+", " ", st.name.lower())
            topic = Topic(
                course_id=course_id,
                name=st.name,
                is_auto_extracted=True,
                level=st.level,
                source=st.source,
                parent_topic_id=None,  # filled in step 3
                coverage_score=None,   # filled after chunk mapping
            )
            db.add(topic)
            db.flush()  # obtain topic.id
            key_to_topic[name_key] = topic
            saved_topics.append(topic)

        # ── Step 3: wire parent_topic_id ─────────────────────────
        for st, topic in zip(structured, saved_topics):
            if st.parent_key and st.parent_key in key_to_topic:
                parent = key_to_topic[st.parent_key]
                topic.parent_topic_id = parent.id
        db.flush()

        # ── Step 4: build chunk mappings + coverage scores ─────────
        total_chunks = len(chunks)

        for st, topic in zip(structured, saved_topics):
            raw_scores = [
                self.compute_chunk_relevance(st.name, chunk) for chunk in chunks
            ]
            normalised = self._normalise_scores(raw_scores)

            mappings_added = 0
            for chunk, norm_score in zip(chunks, normalised):
                if norm_score <= relevance_threshold:
                    continue
                db.add(
                    TopicChunkMap(
                        topic_id=topic.id,
                        chunk_id=chunk.id,
                        relevance_score=round(norm_score, 6),
                    )
                )
                mappings_added += 1

            topic.coverage_score = self._compute_coverage_score(
                mappings_added, total_chunks
            )
            logger.debug(
                "save_topics: topic=%r source=%s level=%s mappings=%d coverage=%.4f",
                st.name,
                st.source,
                st.level,
                mappings_added,
                topic.coverage_score,
            )

        db.flush()
        logger.info(
            "save_topics: persisted %d topics (strategy=%s) for course %s",
            len(saved_topics),
            saved_topics[0].source if saved_topics else "N/A",
            course_id,
        )
        return saved_topics

    # ── pluggable orchestrator path ───────────────────────────────

    def save_topics_v2(
        self,
        db: Session,
        course_id: uuid.UUID,
        chunks: Sequence[Chunk],
        *,
        source_path: str | None = None,
        embedding_service: object | None = None,
        **_kwargs: object,  # absorb unused legacy kwargs
    ) -> list[Topic]:
        """
        New extraction pipeline using the pluggable TopicExtractionOrchestrator.

        Replaces save_topics() with a better multi-strategy approach that handles:
          - PDFs with embedded outlines (PdfOutlineTocExtractor)
          - PDFs with font-based headings (LayoutHeadingExtractor)
          - Any text document with pattern-based headings (RegexHeadingExtractor)
          - Documents with none of the above (EmbeddingClusterExtractor)
        """
        from app.services.topic_extraction.orchestrator import TopicExtractionOrchestrator

        orch = TopicExtractionOrchestrator(embedding_service)
        topics, _meta = orch.extract_and_save(
            db=db,
            course_id=course_id,
            chunks=list(chunks),
            file_path=source_path or "",
        )
        return topics
