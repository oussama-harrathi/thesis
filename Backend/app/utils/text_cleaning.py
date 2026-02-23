"""
Text cleaning utilities.

All functions are pure (no I/O, no side-effects) so they are trivially
unit-testable.

Pipeline order (applied by ``clean_text``)
──────────────────────────────────────────
1. Decode / normalise unicode (NFKC)
2. Expand ligatures (ﬁ → fi, etc.)
3. Remove null bytes and control characters (keep \\t and \\n)
4. Replace non-breaking / exotic spaces with a regular space
5. Collapse runs of spaces/tabs on a single line to one space
6. Strip leading/trailing whitespace on every line
7. Collapse runs of 3+ consecutive blank lines to 2
8. Strip leading/trailing whitespace from the whole document

Typical usage
─────────────
    from app.utils.text_cleaning import clean_text

    cleaned = clean_text(raw_text)
"""

from __future__ import annotations

import re
import unicodedata


# ── Ligature map ─────────────────────────────────────────────────

_LIGATURES: dict[str, str] = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}
_LIGATURE_RE = re.compile("|".join(re.escape(k) for k in _LIGATURES))

# Exotic / non-breaking space code points that should become a regular space
_EXOTIC_SPACES_RE = re.compile(
    r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]"
)

# Control characters except \\t (\\x09) and \\n (\\x0a)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")

# Multiple spaces or tabs on the same line
_INLINE_SPACES_RE = re.compile(r"[ \t]{2,}")

# Three or more consecutive blank lines → two blank lines
_MANY_BLANK_LINES_RE = re.compile(r"\n{3,}")


# ── Public API ────────────────────────────────────────────────────


def normalise_unicode(text: str) -> str:
    """Apply NFKC normalisation (resolves compatibility equivalences)."""
    return unicodedata.normalize("NFKC", text)


def expand_ligatures(text: str) -> str:
    """Replace typographic ligatures with their ASCII equivalents."""
    return _LIGATURE_RE.sub(lambda m: _LIGATURES[m.group()], text)


def remove_control_chars(text: str) -> str:
    """Strip null bytes and control characters (keeps \\t and \\n)."""
    return _CONTROL_CHARS_RE.sub("", text)


def normalise_spaces(text: str) -> str:
    """
    Replace exotic/non-breaking spaces, then collapse inline runs of
    whitespace (spaces/tabs) to a single space, and strip each line.
    """
    text = _EXOTIC_SPACES_RE.sub(" ", text)
    lines = [_INLINE_SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(lines)


def collapse_blank_lines(text: str) -> str:
    """Reduce runs of 3+ consecutive blank lines to exactly 2."""
    return _MANY_BLANK_LINES_RE.sub("\n\n", text)


def clean_text(text: str) -> str:
    """
    Apply the full cleaning pipeline in order:

    1. NFKC unicode normalisation
    2. Ligature expansion
    3. Control character removal
    4. Space normalisation (exotic spaces → ASCII, inline collapse, strip lines)
    5. Blank-line collapsing
    6. Final strip
    """
    text = normalise_unicode(text)
    text = expand_ligatures(text)
    text = remove_control_chars(text)
    text = normalise_spaces(text)
    text = collapse_blank_lines(text)
    return text.strip()
