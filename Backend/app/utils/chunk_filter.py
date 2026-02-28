"""
Chunk Filter Utilities

Provides helpers for:
  1. Identifying non-instructional / boilerplate chunks that should be excluded
     from question generation (references sections, problem listings, etc.)
  2. Detecting near-duplicate questions using token-level Jaccard similarity.
  3. Detecting trivial (definition-only) questions that should be regenerated
     when the target difficulty is MEDIUM or HARD.
  4. Bloom–difficulty default mapping used across the generation pipeline.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Chunk exclusion patterns
# ---------------------------------------------------------------------------

# Matches chunk *openings* (first ~300 chars) that strongly indicate
# non-instructional boilerplate content.
_HEADING_EXCLUDE = re.compile(
    r"""
    ^\s*
    (?:
        (?:\d+[\.\d]*\s+)?          # optional section number e.g. "10.12."
        references?\b               # "References" heading
        |
        bibliography\b              # "Bibliography"
        |
        (?:homework|practice|exam|review)\s+problems?\b   # "Homework Problems"
        |
        problems?\s+for\s+(?:section|chapter)\b           # "Problems for Section"
        |
        further\s+reading\b         # "Further Reading"
        |
        acknowledgements?\b         # "Acknowledgements"
        |
        (?:list\s+of\s+)?(?:figures?|tables?|abbreviations?|symbols?)\b  # "List of Figures"
        |
        ^\s*index\s*$               # standalone "Index"
    )
    """,
    re.I | re.X | re.MULTILINE,
)

# Bracket citations like [1], [12], [ABc03], [Smith, 2020]
_CITATION_RE = re.compile(r"\[[A-Za-z0-9,\.\s]{1,30}\]")

# "See [1]", "cf. [2]", "refer to [3]" — chunks that are mostly cross-references
_SEE_REF_RE = re.compile(r"\b(?:see|cf\.?|refer\s+to|as\s+in)\s+\[", re.I)


def is_excluded_for_generation(text: str) -> bool:
    """
    Return True if the chunk is clearly non-instructional content that should
    NOT be used for question generation.

    Heuristics applied:
    ------------------
    1. The chunk's first 300 chars match a known boilerplate heading pattern.
    2. The chunk is short (< 80 words) and is dominated by bracket citations.
    3. Citation density exceeds 15% of all tokens.
    4. More than 40% of sentences are "see/cf." style cross-reference sentences.
    """
    if not text:
        return False

    stripped = text.strip()
    first_300 = stripped[:300]

    # Rule 1: begins with a non-instructional section heading
    if _HEADING_EXCLUDE.search(first_300):
        return True

    words = stripped.split()
    word_count = len(words)

    if word_count == 0:
        return True  # empty chunk — useless

    citation_count = len(_CITATION_RE.findall(stripped))

    # Rule 2: short + citation-heavy = likely a references list
    if word_count < 80 and citation_count >= 4:
        return True

    # Rule 3: high citation density across entire chunk
    if citation_count / word_count > 0.15:
        return True

    # Rule 4: many "See [X]" sentences
    see_ref_count = len(_SEE_REF_RE.findall(stripped))
    sentences = [s for s in re.split(r"[.!?]+", stripped) if s.strip()]
    n_sentences = len(sentences)
    if n_sentences > 0 and see_ref_count / n_sentences > 0.40:
        return True

    return False


# ---------------------------------------------------------------------------
# Duplicate question detection  (Jaccard on tokens)
# ---------------------------------------------------------------------------

# Discard very short tokens that are likely stop words or punctuation
_MIN_TOKEN_LEN = 3


def _tokenize(text: str) -> frozenset[str]:
    """Lower-case, split on non-alphanumerics, return a frozenset of tokens."""
    tokens = re.split(r"\W+", text.lower())
    return frozenset(t for t in tokens if len(t) >= _MIN_TOKEN_LEN)


def jaccard_similarity(a: str, b: str) -> float:
    """Return token-level Jaccard similarity in [0, 1]."""
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_duplicate_question(
    stem: str,
    existing_stems: list[str],
    threshold: float = 0.72,
) -> tuple[bool, float]:
    """
    Return *(is_duplicate, max_similarity)*.

    A question is considered a near-duplicate if its Jaccard similarity with
    any question already in *existing_stems* exceeds *threshold*.

    Parameters
    ----------
    stem           : The newly generated question text to check.
    existing_stems : List of question texts generated so far in this job.
    threshold      : Jaccard threshold above which we declare a duplicate.
                     0.72 is a reasonable default — questions sharing 72% of
                     their informative tokens are almost certainly the same
                     question phrased slightly differently.

    Returns
    -------
    (True, similarity)  if a near-duplicate is found
    (False, max_sim)    otherwise
    """
    if not existing_stems:
        return False, 0.0
    max_sim = max(jaccard_similarity(stem, existing) for existing in existing_stems)
    return max_sim > threshold, max_sim


# ---------------------------------------------------------------------------
# Triviality detection
# ---------------------------------------------------------------------------

# Bloom-level defaults per difficulty.  Used when the caller does not supply
# an explicit target Bloom level.
BLOOM_FOR_DIFFICULTY: dict[str, list[str]] = {
    "easy":   ["remember", "understand"],
    "medium": ["understand", "apply", "analyze"],
    "hard":   ["apply", "analyze", "evaluate"],
}

DEFAULT_BLOOM_FOR_DIFFICULTY: dict[str, str] = {
    "easy":   "understand",
    "medium": "apply",
    "hard":   "analyze",
}

# Regex patterns that strongly indicate a trivial definition/recall question.
# Checked against the lower-cased question stem.
_TRIVIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^what\s+is\s+(?:a|an|the)\s+\w"),            # "What is a proposition?"
    re.compile(r"^what\s+are\s+(?:a|an|the)\s+\w"),           # "What are the elements of…?"
    re.compile(r"^define\s+"),                                  # "Define the term…"
    re.compile(r"^what\s+does\s+.{1,60}\s+(?:mean|assert|represent|denote|stand\s+for)"),
    re.compile(r"^state\s+the\s+definition\s+of\s+"),          # "State the definition of…"
    re.compile(r"^give\s+(?:a|an|the)\s+definition\s+of\s+"),  # "Give a definition of…"
    re.compile(r"^which\s+term\s+refers\s+to\s+"),             # "Which term refers to…?"
    re.compile(r"^what\s+is\s+meant\s+by\s+"),                 # "What is meant by X?"
    re.compile(r"^(?:briefly\s+)?explain\s+what\s+(?:a|an|the)\s+\w+\s+is"),
    re.compile(r"^what\s+symbol\s+"),                          # "What symbol is used for…?"
    re.compile(r"^which\s+notation\s+"),                       # "Which notation represents…?"
]


def is_trivial_question(text: str) -> bool:
    """
    Return True if the question stem matches known trivial recall/definition patterns.

    Triviality is checked regardless of difficulty; the *caller* decides whether
    to act on it based on the target difficulty and Bloom level.
    """
    if not text:
        return False
    lower = text.strip().lower()
    return any(p.search(lower) for p in _TRIVIAL_PATTERNS)


def should_reject_trivial(text: str, difficulty: str, bloom: str) -> bool:
    """
    Return True when a trivial question should be rejected (not persisted)
    because the target cognitive level is above pure recall.

    A question is rejected when ALL of the following hold:
     - The stem matches a trivial pattern.
     - The target difficulty is "medium" or "hard".
     - The target Bloom level is NOT "remember".
    """
    if difficulty.lower() == "easy":
        return False
    if bloom.lower() == "remember":
        return False
    return is_trivial_question(text)
