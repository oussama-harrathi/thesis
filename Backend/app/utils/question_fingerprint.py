"""
Question fingerprint utilities.

A question fingerprint is a stable, normalized hash of the question stem text
used to detect exact (or near-exact textual) duplicates across generation runs
and against the blacklist.

Normalization steps:
  1. Lowercase.
  2. Remove MCQ option labels: "A) ", "B. ", "(c) " etc.
  3. Strip all punctuation and special characters.
  4. Collapse whitespace.
  5. SHA-256 hex digest.
"""

from __future__ import annotations

import hashlib
import re


# Option-label pattern: A) B. C: (D)  at word boundaries
_OPTION_LABEL_PATTERN = re.compile(
    r"(?<!\w)(?:[(\[]*)[a-dA-D](?:[)\].:\s]+)", re.UNICODE
)
# Strip anything that is not word chars or whitespace
_NON_WORD_PATTERN = re.compile(r"[^\w\s]", re.UNICODE)
# Multiple spaces → single space
_MULTI_SPACE_PATTERN = re.compile(r"\s+")


def compute_question_fingerprint(text: str) -> str:
    """
    Return a 64-character hex fingerprint for *text*.

    Two questions produce the same fingerprint if and only if their
    normalised texts are identical (after lowercasing, removing MCQ labels,
    stripping punctuation, and collapsing whitespace).

    Suitable for exact-duplicate detection; for semantic near-duplicate
    detection use embedding similarity instead.
    """
    t = text.lower()
    t = _OPTION_LABEL_PATTERN.sub(" ", t)
    t = _NON_WORD_PATTERN.sub(" ", t)
    t = _MULTI_SPACE_PATTERN.sub(" ", t).strip()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()
