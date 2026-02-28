"""
Text Normalization Utilities
============================

Provides ``normalize_logic_symbols(text)`` — a lightweight, side-effect-free
function that repairs common math/logic symbol encoding artifacts produced by
PyMuPDF PDF extraction of discrete-math / formal-logic textbooks.

Known artifact classes handled
-------------------------------
1. **Membership operator** – the ∈ character (U+2208, ELEMENT OF) is sometimes
   extracted as the ASCII digit ``"2"`` when the PDF was authored with a custom
   font encoding.  The replacement is applied only in clearly variable-vs-set
   contexts (single lowercase letter on the left, uppercase letter or ``{`` on
   the right) to minimise false positives.

2. **Definition operator** – ``:=`` occasionally appears as ``"WWD"`` (or
   ``"W:="`` as a partial artifact) in certain textbook PDFs.

3. **ASCII inequality arrows** – ``<=`` / ``>=`` are normalised to ``≤`` / ``≥``
   when not already followed by a second ``=`` (to avoid broken ``<==`` patterns).

4. **Redundant whitespace** – collapsed to a single space after all substitutions.

Usage
-----
Call ``normalize_logic_symbols(text)`` on:
  • Retrieved chunk text before building the LLM prompt context.
  • LLM-generated question bodies / option texts before persisting to the DB.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Direct (literal) substitutions — safe, no context needed
# ---------------------------------------------------------------------------

_DIRECT_SUBSTITUTIONS: list[tuple[str, str]] = [
    # Definition operator PDF artifacts
    ("WWD",  ":="),
    ("W:=",  ":="),
    (":=:=", ":="),   # doubled artifact
    # HTML-entity remnants that some PDF extractors leave behind
    ("&isin;",  "∈"),
    ("&sub;",   "⊂"),
    ("&sube;",  "⊆"),
    ("&supe;",  "⊇"),
    ("&rArr;",  "⇒"),
    ("&hArr;",  "⇔"),
    ("&rarr;",  "→"),
    ("&larr;",  "←"),
    ("&lArr;",  "⇐"),
    ("&equiv;", "≡"),
    ("&not;",   "¬"),
    ("&and;",   "∧"),
    ("&or;",    "∨"),
    ("&forall;","∀"),
    ("&exist;", "∃"),
    ("&empty;", "∅"),
    ("&cap;",   "∩"),
    ("&cup;",   "∪"),
]

# ---------------------------------------------------------------------------
# Regex substitutions — contextual, applied after direct ones
# ---------------------------------------------------------------------------

_REGEX_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [
    # ── ∈ artifact ───────────────────────────────────────────────────────────
    # "2" used as membership symbol: only when preceded by a single-char variable
    # (one lower-case letter that is NOT itself preceded by another letter, to
    # exclude partial words) and followed by an upper-case set name or ``{``.
    #
    # Matches: "x 2 A", "a 2 B", "n2N", "x 2 {1,2,3}"
    # No match: "step 2 Is", "Chapter 2 In", "Algorithm 2 Analyses"
    (
        re.compile(r"(?<![A-Za-z])([a-z])\s+2\s+([A-Z\{])"),
        r"\1∈\2",
    ),
    # Also handle run-on "n2N" style (no spaces)
    (
        re.compile(r"(?<![A-Za-z])([a-z])2([A-Z\{])"),
        r"\1∈\2",
    ),
    # ── Inequality arrows (only when not already Unicode and not "<==" / ">==" )
    (re.compile(r"<\s*=(?![=<>])"),  "≤"),
    (re.compile(r">\s*=(?![=<>])"),  "≥"),
    # ── Redundant whitespace ─────────────────────────────────────────────────
    (re.compile(r" {2,}"), " "),
]


def normalize_logic_symbols(text: str) -> str:
    """
    Normalize common math/logic symbol encoding artifacts in *text*.

    The function is safe to call on any string — if no patterns match the input
    is returned unchanged.  It neither raises on empty input nor performs any
    external calls.

    Parameters
    ----------
    text : str
        Raw text that may contain PDF extraction artifacts.

    Returns
    -------
    str
        Cleaned text with known artifact patterns replaced by their intended
        Unicode symbols.
    """
    if not text:
        return text

    # Stage 1: direct literal substitutions (string.replace — O(n) each)
    for bad, good in _DIRECT_SUBSTITUTIONS:
        if bad in text:
            text = text.replace(bad, good)

    # Stage 2: contextual regex substitutions
    for pattern, replacement in _REGEX_SUBSTITUTIONS:
        text = pattern.sub(replacement, text)

    return text
