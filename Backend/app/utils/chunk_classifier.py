"""
Chunk Content Classifier

Deterministic (no LLM) rule-based classifier that assigns every text chunk
one of four content types:

    INSTRUCTIONAL           — main teaching / explanation content  ← default
    EXERCISE                — primarily problem/exercise statements
    REFERENCES_BOILERPLATE  — references, bibliography, index, repeated headers
    ADMIN_ASSESSMENT        — mark allocations, paper structure, assessment rules

Design principles
─────────────────
- Fully deterministic: same text always produces the same result.
- Returns a score (int) and the list of matched rule names so decisions can
  be audited and explained in the thesis.
- Thresholds are intentionally conservative to minimise false positives on
  legitimate instructional content.

Usage
─────
    from app.utils.chunk_classifier import classify_chunk_type, ChunkType

    chunk_type, score, rules = classify_chunk_type(text)
"""

from __future__ import annotations

import enum
import re
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Enum (mirrors the DB enum defined in app.models.chunk)
# ---------------------------------------------------------------------------

class ChunkType(str, enum.Enum):
    instructional          = "instructional"
    exercise               = "exercise"
    references_boilerplate = "references_boilerplate"
    admin_assessment       = "admin_assessment"


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

class ClassificationResult(NamedTuple):
    chunk_type:    ChunkType
    score:         int
    matched_rules: list[str]


# ---------------------------------------------------------------------------
# ADMIN_ASSESSMENT rules
# ---------------------------------------------------------------------------
# Each entry: (rule_name, compiled_regex, weight)
# Match is searched in the full text (case-insensitive).

_ADMIN_PHRASE_RULES: list[tuple[str, re.Pattern[str], int]] = [
    # Explicit assessment terminology
    ("phrase:internal_assessment",  re.compile(r"\binternal\s+assessment\b",   re.I), 3),
    ("phrase:external_assessment",  re.compile(r"\bexternal\s+assessment\b",   re.I), 3),
    ("phrase:assessment_criteria",  re.compile(r"\bassessment\s+criteria\b",   re.I), 3),
    ("phrase:mark_allocation",      re.compile(r"\bmark\s+allocation\b",       re.I), 3),
    ("phrase:weighting",            re.compile(r"\bweighting\b",               re.I), 2),
    ("phrase:final_assessment",     re.compile(r"\bfinal\s+assessment\b",      re.I), 3),
    ("phrase:assessment_objective", re.compile(r"\bassessment\s+objective",    re.I), 2),
    # Exam / paper structure markers
    ("struct:paper_1_2",            re.compile(r"\bpaper\s+[12]\b",            re.I), 2),
    ("struct:section_A_B",          re.compile(r"\bsection\s+[abcABC]\b",      re.I), 1),
    ("struct:duration",             re.compile(r"\bduration\b",                re.I), 2),
    ("struct:worth_N_marks",        re.compile(r"\bworth\s+\d+\s+marks?\b",    re.I), 3),
    ("struct:compulsory",           re.compile(r"\bcompulsory\b",              re.I), 2),
    ("struct:prescribed_by",        re.compile(r"\bprescribed\s+by\b",         re.I), 2),
    ("struct:syllabus_aims",        re.compile(r"\bsyllabus\s+aims?\b",        re.I), 2),
    ("struct:learning_outcomes",    re.compile(r"\blearning\s+outcomes?\b",    re.I), 1),
    ("struct:ib_diploma",           re.compile(r"\bib\s+diploma\b",            re.I), 3),
    ("struct:grade_boundary",       re.compile(r"\bgrade\s+boundar",           re.I), 3),
    ("struct:markscheme",           re.compile(r"\bmark\s*scheme\b",           re.I), 3),
    ("struct:total_marks",          re.compile(r"\btotal\s+marks?\b",          re.I), 2),
]

_ADMIN_THRESHOLD = 5   # score >= this → ADMIN_ASSESSMENT


# ---------------------------------------------------------------------------
# REFERENCES_BOILERPLATE rules
# ---------------------------------------------------------------------------

_REF_PHRASE_RULES: list[tuple[str, re.Pattern[str], int]] = [
    # Section headings that introduce reference/boilerplate blocks.
    # Anchored to start-of-line or start-of-text so they catch real headings.
    # Weight = 5 so that a single heading match hits the threshold on its own.
    ("heading:references",   re.compile(r"(?:^|\n)\s*\d*\.?\s*references?\s*$",    re.I | re.M), 5),
    ("heading:bibliography", re.compile(r"(?:^|\n)\s*\d*\.?\s*bibliography\s*$",   re.I | re.M), 5),
    ("heading:index",        re.compile(r"(?:^|\n)\s*index\s*$",                   re.I | re.M), 5),
    ("heading:glossary",     re.compile(r"(?:^|\n)\s*\d*\.?\s*glossary\s*$",       re.I | re.M), 5),
    ("heading:further_reading", re.compile(r"(?:^|\n)\s*further\s+reading\s*$",    re.I | re.M), 5),
    # Repeated header/footer artifacts common in scanned textbooks
    # e.g. "MCS — Discrete Mathematics — Page 47"
    ("artifact:mcs_page_header", re.compile(
        r"\bmcs\s*[—\-]\s*.{2,60}\s*[—\-]\s*page\s*\d+",
        re.I,
    ), 5),
    # Generic "Page N" watermarks that repeat across chunks
    ("artifact:page_watermark", re.compile(
        r"(?:^|\n)\s*(?:page|p\.)\s*\d+\s*(?:of\s*\d+)?\s*$",
        re.I | re.M,
    ), 2),
    # Pure reference-list patterns: "[N] Author, Title..."
    ("pattern:numbered_ref",    re.compile(r"^\s*\[\d+\]\s+\w",   re.I | re.M), 3),
    # "Problems for Section X" / "Class Problems" / "Review Problems" etc.
    # Weight = 5 so a single heading match hits the threshold.
    ("heading:problems_for",        re.compile(r"\bproblems?\s+for\s+(?:section|chapter)\b", re.I), 5),
    ("heading:class_problems",      re.compile(r"\bclass\s+problems?\b",                     re.I), 5),
    ("heading:practice_problems",   re.compile(r"\bpractice\s+problems?\b",                  re.I), 5),
    ("heading:homework_problems",   re.compile(r"\bhomework\s+problems?\b",                  re.I), 5),
    ("heading:exercises_section",   re.compile(r"\bexercises\s+for\s+(?:section|chapter)\b", re.I), 5),
    ("heading:review_problems",     re.compile(r"(?:^|\n)\s*review\s+problems?\s*$",         re.I | re.M), 5),
    ("heading:answers",             re.compile(r"(?:^|\n)\s*\d*\.?\s*answers?\s*$",           re.I | re.M), 5),
]

_REF_THRESHOLD = 5   # score >= this → REFERENCES_BOILERPLATE


# ---------------------------------------------------------------------------
# EXERCISE rules
# ---------------------------------------------------------------------------

# Considers chunk EXERCISE when it's primarily a problem statement and not
# already classified as REFERENCES_BOILERPLATE or ADMIN_ASSESSMENT.

_EXERCISE_RULES: list[tuple[str, re.Pattern[str], int]] = [
    # Starts with "Problem N" or "Exercise N"
    ("starts:problem_N",  re.compile(r"^\s*(?:problem|exercise)\s+\d+",    re.I | re.M), 4),
    # Many sub-part labels (a), (b), (c) — typical in exercise sheets
    ("pattern:sub_parts", re.compile(r"\([a-e]\)\s+\w",                   re.I), 2),  # score added per match (up to 3 matches counted)
    # "Find …", "Show that …", "Prove that …" imperatives in short context
    ("imperative:find_show_prove", re.compile(
        r"\b(?:find|show|prove|determine|evaluate|calculate|solve|verify|simplify)\b",
        re.I,
    ), 1),
]

_EXERCISE_THRESHOLD = 4  # score >= this → EXERCISE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_chunk_type(text: str) -> tuple[ChunkType, int, list[str]]:
    """
    Classify a text chunk into one of the four ChunkTypes.

    Parameters
    ----------
    text : Raw chunk text (any length).

    Returns
    -------
    (chunk_type, score, matched_rules)
        chunk_type    — the determined ChunkType enum value
        score         — integer accumulation of matched rule weights
                        (can be used for debugging / audit)
        matched_rules — list of rule name strings that fired
    """
    if not text or not text.strip():
        return ChunkType.instructional, 0, []

    matched: list[str] = []

    # ── 1. Check ADMIN_ASSESSMENT ──────────────────────────────────────────
    admin_score = 0
    for rule_name, pattern, weight in _ADMIN_PHRASE_RULES:
        if pattern.search(text):
            admin_score += weight
            matched.append(rule_name)

    if admin_score >= _ADMIN_THRESHOLD:
        return ChunkType.admin_assessment, admin_score, matched

    # ── 2. Check REFERENCES_BOILERPLATE ───────────────────────────────────
    ref_score = 0
    ref_matched: list[str] = []
    for rule_name, pattern, weight in _REF_PHRASE_RULES:
        hits = pattern.findall(text)
        if hits:
            # For patterns that repeat (e.g. numbered refs, sub-parts),
            # cap contribution to 2× weight so a single repeated artifact
            # does not dominate the score.
            capped = min(len(hits), 2)
            ref_score += weight * capped
            ref_matched.append(f"{rule_name}(×{capped})")

    if ref_score >= _REF_THRESHOLD:
        matched.extend(ref_matched)
        return ChunkType.references_boilerplate, ref_score, matched

    # ── 3. Check EXERCISE ─────────────────────────────────────────────────
    ex_score = 0
    ex_matched: list[str] = []
    for rule_name, pattern, weight in _EXERCISE_RULES:
        hits = pattern.findall(text)
        if hits:
            capped = min(len(hits), 3)
            ex_score += weight * capped
            ex_matched.append(f"{rule_name}(×{capped})")

    if ex_score >= _EXERCISE_THRESHOLD:
        matched.extend(ex_matched)
        return ChunkType.exercise, ex_score, matched

    # ── 4. Default: INSTRUCTIONAL ─────────────────────────────────────────
    return ChunkType.instructional, 0, []
