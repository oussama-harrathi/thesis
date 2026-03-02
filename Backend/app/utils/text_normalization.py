"""
Text / Math Symbol Normalization Utilities
==========================================

Provides two public entry-points (both refer to the same function):

    normalize_math_symbols(text: str) -> str   ← preferred name
    normalize_logic_symbols(text: str) -> str  ← legacy alias (kept for
                                                  backward compatibility)

Call on **any question text, option text, answer text, or explanation** before
persisting to the database so that both the UI and PDF/LaTeX export receive
clean, Unicode-correct symbols.

---

Artifact classes handled
------------------------

A. QUANTIFIER ARTIFACTS
   PDF textbooks sometimes encode ∀ as the digit ``8`` and ∃ as the letter
   ``E`` (or ``3`` depending on font mapping).

   Pattern              Replacement
   ───────────────────  ───────────
   8z:  /  8 z :        ∀z:
   Ez:  /  E z :        ∃z:  (only lowercase single-letter variables)
   3z:  /  3 z :        ∃z:

B. LOGICAL CONNECTIVE KEYWORDS (all-caps, word-boundary-matched)
   These appear when an LLM echoes raw PDF source or when a PDF encodes
   logical operators as ASCII text rather than Unicode symbols.

   IMPLIES   →  ⇒
   IFF       →  ⇔
   AND       →  ∧
   OR        →  ∨
   NOT       →  ¬
   FORALL    →  ∀
   EXISTS    →  ∃
   NEQ       →  ≠
   SUBSETEQ  →  ⊆
   SUBSET    →  ⊂
   UNION     →  ∪
   INTERSECT →  ∩
   EMPTYSET  →  ∅

C. PLACEHOLDER / BRACKET ARTIFACTS
   Some PDFs render mathematical expressions with a leading ``.`` and
   trailing ``/`` as bracket surrogates.

   .x D y/  →  x = y   (``D`` inside the placeholder encodes equality)
   .x y/    →  x ⊆ y   (two adjacent single-letter variables = subset)

D. MEMBERSHIP OPERATOR ARTIFACT
   ``∈`` (U+2208) sometimes extracted as ASCII ``2`` when preceded by a
   single-letter variable and followed by an uppercase set name or ``{``.

   x 2 A  →  x∈A
   x2A    →  x∈A

E. DEFINITION OPERATOR ARTIFACT
   ``WWD`` and ``W:=`` are encoding artifacts for ``:=``.

F. HTML-ENTITY REMNANTS
   Entities such as ``&isin;``, ``&rArr;``, ``&forall;`` etc. are replaced
   by their Unicode counterparts.

G. INEQUALITY ARROWS
   ``<=`` / ``>=`` replaced by ``≤`` / ``≥`` unless part of ``<==`` / ``>==``.

H. REDUNDANT WHITESPACE
   Collapsed to a single space after all other substitutions.

---

Usage
-----
from app.utils.text_normalization import normalize_math_symbols

text = normalize_math_symbols(raw_text)
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# A.  Direct (literal) substitutions — applied first; order matters for
#     overlapping strings (e.g. ":=:=" before ":=").
# ---------------------------------------------------------------------------

_DIRECT_SUBSTITUTIONS: list[tuple[str, str]] = [
    # ── Definition operator PDF artifacts ───────────────────────────────────
    (":=:=", ":="),    # doubled artifact — resolve first
    ("W:=",  ":="),
    ("WWD",  ":="),
    # ── HTML-entity remnants ─────────────────────────────────────────────────
    ("&forall;", "∀"),
    ("&exist;",  "∃"),
    ("&isin;",   "∈"),
    ("&notin;",  "∉"),
    ("&sub;",    "⊂"),
    ("&sube;",   "⊆"),
    ("&supe;",   "⊇"),
    ("&cap;",    "∩"),
    ("&cup;",    "∪"),
    ("&rArr;",   "⇒"),
    ("&lArr;",   "⇐"),
    ("&hArr;",   "⇔"),
    ("&rarr;",   "→"),
    ("&larr;",   "←"),
    ("&equiv;",  "≡"),
    ("&not;",    "¬"),
    ("&and;",    "∧"),
    ("&or;",     "∨"),
    ("&empty;",  "∅"),
    ("&ne;",     "≠"),
    ("&le;",     "≤"),
    ("&ge;",     "≥"),
]

# ---------------------------------------------------------------------------
# B.  Regex substitutions — applied in the listed order after direct ones.
#     Patterns that are more specific come before more general patterns.
# ---------------------------------------------------------------------------

_REGEX_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [

    # ── C. Placeholder / bracket artifacts ──────────────────────────────────
    # Must come before membership/inequality patterns.
    #
    # ".x D y/" encodes "x = y" — dot+slash are bracket surrogates, "D" = "=".
    # Variables may be 1–10 alphanumeric chars.
    (
        re.compile(r"\.\s*([A-Za-z]\w{0,9})\s+D\s+([A-Za-z]\w{0,9})\s*/"),
        r"\1 = \2",
    ),
    # ".x y/" encodes "x ⊆ y" — two adjacent single-letter variables inside
    # dot/slash.  Kept to single chars to avoid matching footnote-style text.
    (
        re.compile(r"\.\s*([A-Za-z])\s+([A-Za-z])\s*/"),
        r"\1 ⊆ \2",
    ),

    # ── A. Quantifier artifacts ───────────────────────────────────────────────
    # Universal quantifier: standalone digit 8 (not preceded by another digit or
    # letter) followed by optional space, a letter, optional space, then colon.
    #   Matches:  "8z:"  "8 z :"  "8x:"
    #   No match: "F8x:" "18z:"
    (
        re.compile(r"(?<![A-Za-z\d])8\s*([A-Za-z])\s*:"),
        r"∀\1:",
    ),
    # Existential quantifier: standalone "E" before a single LOWERCASE letter
    # and colon.  Limited to lowercase to avoid over-matching set names ("El:").
    (
        re.compile(r"(?<![A-Za-z])E\s*([a-z])\s*:"),
        r"∃\1:",
    ),
    # Existential quantifier: "3" artifact (present in some font encodings).
    (
        re.compile(r"(?<![A-Za-z\d])3\s*([a-z])\s*:"),
        r"∃\1:",
    ),

    # ── B. Logical connective keywords (all-caps, word-boundary) ────────────
    # IFF before IF (should IF ever be added) to prevent partial matching.
    # SUBSETEQ before SUBSET for the same reason.
    (re.compile(r"\bIFF\b"),       "⇔"),
    (re.compile(r"\bIMPLIES\b"),   "⇒"),
    (re.compile(r"\bAND\b"),       "∧"),
    (re.compile(r"\bOR\b"),        "∨"),
    (re.compile(r"\bNOT\b"),       "¬"),
    (re.compile(r"\bFORALL\b"),    "∀"),
    (re.compile(r"\bEXISTS\b"),    "∃"),
    (re.compile(r"\bNEQ\b"),       "≠"),
    (re.compile(r"\bSUBSETEQ\b"),  "⊆"),
    (re.compile(r"\bSUBSET\b"),    "⊂"),
    (re.compile(r"\bUNION\b"),     "∪"),
    (re.compile(r"\bINTERSECT\b"), "∩"),
    (re.compile(r"\bEMPTYSET\b"),  "∅"),

    # ── D. Membership operator artifact ─────────────────────────────────────
    # "2" as ∈: single-char variable left, uppercase set name or "{" right.
    #   Matches:  "x 2 A"  "a 2 B"  "n2N"  "x 2 {1,2,3}"
    #   No match: "step 2 Is"  "Chapter 2 In"  "Algorithm 2 Analyses"
    (
        re.compile(r"(?<![A-Za-z])([a-z])\s+2\s+([A-Z\{])"),
        r"\1∈\2",
    ),
    # Run-on variant without spaces: "n2N".
    (
        re.compile(r"(?<![A-Za-z])([a-z])2([A-Z\{])"),
        r"\1∈\2",
    ),
    # Lowercase-on-both-sides variant: "z 2 x" in set-theory contexts where
    # both variable and set name are single lowercase letters.  The right-side
    # variable must be word-bounded (not followed by another letter) to prevent
    # false positives like "a 2 be done" where "be" is an English word.
    (
        re.compile(r"(?<![A-Za-z])([a-z])\s+2\s+([a-z])(?![A-Za-z])"),
        r"\1∈\2",
    ),

    # ── G. Inequality arrows ─────────────────────────────────────────────────
    # Replace "<=" / ">=" with ≤/≥ only when not part of "<==" or ">==".
    (re.compile(r"<\s*=(?!=)"),    "≤"),
    (re.compile(r">\s*=(?!=)"),    "≥"),

    # ── H. Redundant whitespace ──────────────────────────────────────────────
    (re.compile(r" {2,}"), " "),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_math_symbols(text: str) -> str:
    """
    Normalize math/logic symbol encoding artifacts in *text*.

    Safe to call on any string — returns the input unchanged if no patterns
    match.  Does not raise on empty input and performs no I/O.

    Parameters
    ----------
    text : str
        Raw text that may contain PDF extraction artifacts.

    Returns
    -------
    str
        Cleaned text with known artifact patterns replaced by their intended
        Unicode characters.

    Examples
    --------
    >>> normalize_math_symbols("8z: (z 2 x IMPLIES z 2 y)")
    '∀z: (z∈x ⇒ z∈y)'
    >>> normalize_math_symbols("a IFF b AND NOT c")
    'a ⇔ b ∧ ¬ c'
    >>> normalize_math_symbols(".A D B/")
    'A = B'
    >>> normalize_math_symbols(".x y/")
    'x ⊆ y'
    """
    if not text:
        return text

    # Stage 1: direct literal substitutions (O(n) string.replace each)
    for bad, good in _DIRECT_SUBSTITUTIONS:
        if bad in text:
            text = text.replace(bad, good)

    # Stage 2: contextual regex substitutions (applied in listed order)
    for pattern, replacement in _REGEX_SUBSTITUTIONS:
        text = pattern.sub(replacement, text)

    return text


# ---------------------------------------------------------------------------
# Legacy alias — existing imports of ``normalize_logic_symbols`` continue to
# work without any changes at call sites.
# ---------------------------------------------------------------------------

normalize_logic_symbols = normalize_math_symbols


# ===========================================================================
# MCS Notation Normalizer
# ===========================================================================
#
# ``normalize_mcs_notation(text)`` is a **superset** of ``normalize_math_symbols``.
# It calls that function first, then applies a second layer of fixes that target
# the specific way LLMs sometimes echo MCS (Mathematical Course Source) notation:
#
#   I.  DOT/SLASH WRAPPERS  ".content/" → "(content)"
#       LLMs reproduce the PDF's custom bracket encoding.  Up to 5 iterative
#       passes are applied so nested instances are all resolved.
#
#   II. DEFINITIONAL ':=' → '⇔'
#       When ':=' appears in an MCQ option/stem and the RHS contains a
#       quantifier (∀ ∃) or connective (⇒ ⇔ ∧ ∨), the intent is logical
#       equivalence, not variable definition.
#
#   III. SPACING AROUND ∈
#       'z∈x' → 'z ∈ x'  (readability; consistent with typeset math)
#
#   IV. QUANTIFIER COLON SPACING
#       '∀z:(phi)' →  '∀z: (phi)'  (missing space after colon)
#
#   V.  PARENTHESIS INTERIOR SPACING
#       '( content )' → '(content)'
#
#   VI. FINAL WHITESPACE COLLAPSE

# ── Compiled patterns used only by normalize_mcs_notation ──────────────────

# I.  Dot/slash wrappers — matches . <anything except newline up to 4000 chars> /
#     A newline boundary prevents greedy cross-line matches.
_DOT_SLASH_WRAPPER = re.compile(r"\.([^/\n]{1,4000})/")

# III. Spacing around ∈ — catches run-on like "z∈x"
_MEMBERSHIP_RUN_ON = re.compile(r"([A-Za-z0-9\}])∈([A-Za-z0-9\{])")

# IV. Missing space after quantifier colon: ∀z:( or ∃x:a
_QUANTIFIER_COLON = re.compile(r"([∀∃][A-Za-z]):([^\s])")


def _replace_definitional_equiv(text: str) -> str:
    """
    Replace ``:=`` with ``⇔`` on each line where the RHS contains at least
    one quantifier or logical connective symbol.

    Lines without ``:=`` are returned unchanged.
    Lines where the RHS is a plain numeric/string definition (no logic symbols)
    keep their ``:=``.
    """
    _RHS_LOGIC = re.compile(r"[∀∃⇒⇔∧∨]")

    result: list[str] = []
    for line in text.split("\n"):
        # Locate the FIRST := on this line.
        idx = line.find(":=")
        if idx != -1:
            rhs = line[idx + 2:]
            if _RHS_LOGIC.search(rhs):
                # Replace the first := only (conservative — one per line)
                line = line[:idx] + " ⇔ " + rhs.lstrip()
                # Collapse any double-spaces introduced around operator
                line = re.sub(r" {2,}", " ", line)
        result.append(line)
    return "\n".join(result)


def normalize_mcs_notation(text: str) -> str:
    """
    Full MCS-notation normalizer.

    Applies ``normalize_math_symbols`` first (quantifier/connective keyword
    replacement, membership artifact, HTML entities, etc.), then a second
    layer that targets LLM-emitted artifacts specific to discrete-math /
    set-theory course material:

    * dot/slash wrappers  →  normal parentheses  (iterative, ≤5 passes)
    * definitional ``:=`` →  ``⇔``  when context is logical equivalence
    * run-on ``∈``        →  spaced  ``∈``
    * missing space after quantifier colon
    * over-spaced parenthesis interiors

    Safe on any string; returns the input unchanged if no patterns match.

    Examples
    --------
    >>> normalize_mcs_notation(".z∈x ⇔ z∈y/")
    '(z ∈ x ⇔ z ∈ y)'
    >>> normalize_mcs_notation("x = y := ∀z: .z∈x ⇔ z∈y/")
    'x = y ⇔ ∀z: (z ∈ x ⇔ z ∈ y)'
    >>> normalize_mcs_notation("8z: .z 2 x IFF z 2 y/")
    '∀z: (z ∈ x ⇔ z ∈ y)'
    """
    if not text:
        return text

    # ── Stage 1: base symbol normalization ─────────────────────────────────
    text = normalize_math_symbols(text)

    # ── Stage 2: definitional ':=' → '⇔' when rhs is logical ──────────────
    if ":=" in text:
        text = _replace_definitional_equiv(text)

    # ── Stage 3: dot/slash wrappers → parentheses (up to 5 passes) ─────────
    for _ in range(5):
        new = _DOT_SLASH_WRAPPER.sub(r"(\1)", text)
        if new == text:
            break
        text = new

    # ── Stage 4: spacing around ∈  (z∈x → z ∈ x) ──────────────────────────
    if "∈" in text:
        text = _MEMBERSHIP_RUN_ON.sub(r"\1 ∈ \2", text)

    # ── Stage 5: missing space after quantifier colon  ∀z:( → ∀z: ( ────────
    text = _QUANTIFIER_COLON.sub(r"\1: \2", text)

    # ── Stage 6: parenthesis interior over-spacing  ( x ) → (x) ───────────
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)

    # ── Stage 7: final whitespace collapse ──────────────────────────────────
    text = re.sub(r" {2,}", " ", text).strip()

    return text
