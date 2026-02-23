"""
TopicExtractionService — heuristic MVP topic extraction.

Strategy
────────
Two complementary signals are combined and then deduplicated:

1.  **Heading detection**
    Lines that look like section/chapter headings are strong topic candidates.
    Heuristics applied (in order):
      • Numbered section headings  e.g. "1.2 Relational Algebra"
      • Keyword-prefixed headings  e.g. "Chapter 3: Database Design"
      • ALL-CAPS short lines        e.g. "NORMALIZATION"
      • Title-case short lines      e.g. "Query Optimization"
    A line qualifies as a heading candidate if it is 3–80 chars long and
    does NOT end with sentence-terminal punctuation (. , ; :).

2.  **High-frequency key-phrases**
    Bi-gram and tri-gram noun-phrase-like sequences are collected across all
    chunk text.  Each candidate is scored by:
        score = frequency × average_word_length²
    This naturally promotes descriptive multi-word concepts over short
    function-word pairs.  Only candidates whose constituent words are NOT in
    a curated English stopword list are kept.

Combination & normalisation
    • Strip leading numbering / bullet characters
    • Title-case
    • Remove duplicates: exact and substring containment (keep the longer one)
    • Trim to the top MIN_TOPICS..MAX_TOPICS range (default 5–15)

Relevance scoring (for topic_chunk_map)
    For each (topic, chunk) pair:
        raw_score = tf_in_chunk / max(1, len(chunk_tokens))
        heading_boost × 2 if the chunk starts with the topic phrase

    Scores are normalised to [0, 1] per topic so that the best chunk always
    scores 1.0.

Limitations & assumptions
    • Plain-text only — works on the ``content`` field of Chunk ORM rows.
    • No stemming / lemmatisation — near-synonyms are treated as different topics.
    • Heading detection is English-centric (capitalisation rules).
    • Frequency counts are over the raw token stream; proper NLP (POS tagging)
      would improve precision significantly.
    • LLM consolidation (Phase 6+) is expected to clean up the list further.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.topic import Topic, TopicChunkMap

logger = logging.getLogger(__name__)

# ── tuneable constants ────────────────────────────────────────────────────────

MIN_TOPICS: int = 5
MAX_TOPICS: int = 15

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
        if (
            _NUMBERED_HEADING.match(line)
            or _KEYWORD_HEADING.match(line)
            or _ALL_CAPS.match(line)
            or _TITLE_CASE.match(line)
        ):
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
    Heuristic topic extractor for course chunks.

    Public API
    ──────────
    extract_topic_names(chunks)          -> list[str]
    compute_chunk_relevance(name, chunk) -> float
    save_topics(db, course_id, chunks)   -> list[Topic]
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
            keyphrase_scores[phrase] = max(
                keyphrase_scores.get(phrase, 0.0),
                _score_ngram(gram, freq),
            )

        for gram, freq in bigram_counter.most_common(80):
            words = list(gram)
            if not _is_meaningful(words):
                continue
            phrase = _normalise(" ".join(words))
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

    # ── persistence ───────────────────────────────────────────────

    def save_topics(
        self,
        db: Session,
        course_id: uuid.UUID,
        chunks: Sequence[Chunk],
        *,
        min_topics: int = MIN_TOPICS,
        max_topics: int = MAX_TOPICS,
        relevance_threshold: float = 0.0,
    ) -> list[Topic]:
        """
        Extract topics from *chunks*, persist them as Topic rows, and build
        TopicChunkMap entries with normalised relevance scores.

        Parameters
        ----------
        db                    : Synchronous SQLAlchemy session (Celery worker).
        course_id             : UUID of the owning Course.
        chunks                : Persisted Chunk rows for the course/document.
        min_topics            : Passed through to extract_topic_names.
        max_topics            : Passed through to extract_topic_names.
        relevance_threshold   : Skip TopicChunkMap rows whose normalised score
                                is at or below this value (default: keep all
                                non-zero mappings).

        Returns
        -------
        List of persisted Topic ORM objects.
        """
        topic_names = self.extract_topic_names(
            chunks, min_topics=min_topics, max_topics=max_topics
        )
        if not topic_names:
            logger.warning("save_topics: no topics extracted for course %s", course_id)
            return []

        saved_topics: list[Topic] = []

        for name in topic_names:
            topic = Topic(
                course_id=course_id,
                name=name,
                is_auto_extracted=True,
            )
            db.add(topic)
            db.flush()  # obtain topic.id without committing

            # ── compute raw relevance scores for every chunk ───────
            raw_scores = [
                self.compute_chunk_relevance(name, chunk) for chunk in chunks
            ]
            normalised = self._normalise_scores(raw_scores)

            mappings_added = 0
            for chunk, norm_score in zip(chunks, normalised):
                if norm_score <= relevance_threshold:
                    continue
                mapping = TopicChunkMap(
                    topic_id=topic.id,
                    chunk_id=chunk.id,
                    relevance_score=round(norm_score, 6),
                )
                db.add(mapping)
                mappings_added += 1

            logger.debug(
                "save_topics: topic=%r  mappings=%d  (threshold=%.3f)",
                name,
                mappings_added,
                relevance_threshold,
            )
            saved_topics.append(topic)

        db.flush()
        logger.info(
            "save_topics: persisted %d topics for course %s",
            len(saved_topics),
            course_id,
        )
        return saved_topics
