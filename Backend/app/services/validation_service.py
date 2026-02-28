"""
Validation Service (Phase 8 — Quality Controls)

Runs post-generation quality checks on Question rows and persists results
to the QuestionValidation table.

Implemented validators
──────────────────────
  grounding   – confirmation that every question has at least one source
                chunk reference.  Three outcome levels:
                  PASS  – ≥1 source with a non-null chunk_id
                  WARN  – ≥1 source exists but none carry a chunk_id
                  FAIL  – no QuestionSource rows at all

  distractor  – rule-based MCQ option quality checks (no LLM call needed):
                  FAIL  – structural violation (wrong count, wrong correct count,
                          duplicate option text after normalisation)
                  WARN  – quality issue ("all/none of the above", one outlier length)
                  PASS  – all checks pass

Planned (Phase 8 later)
──────────────────────
  difficulty  – LLM-assisted difficulty tagging
  bloom       – Bloom taxonomy level tagging

Storage convention
──────────────────
Every validation writes exactly one QuestionValidation row:

  validation_type : string constant (e.g. "grounding")
  passed          : True for PASS and WARN, False for FAIL
  score           : 1.0 (PASS) | 0.5 (WARN) | 0.0 (FAIL)
  detail          : JSON string with human-readable specifics

Using passed=True for WARN (partial success) allows upstream callers to
treat WARN as "acceptable but flagged" without failing hard gating.  The
score field differentiates PASS from WARN numerically.
"""

from __future__ import annotations

import enum
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import BloomLevel, Difficulty, McqOption, Question, QuestionSource, QuestionValidation

if TYPE_CHECKING:
    from app.llm.base import BaseLLMProvider

from app.llm.base import GenerationSettings

logger = logging.getLogger(__name__)


# ── Validation type constants ─────────────────────────────────────────────────

VALIDATION_TYPE_GROUNDING = "grounding"
VALIDATION_TYPE_DISTRACTOR = "distractor"
VALIDATION_TYPE_DIFFICULTY = "difficulty"
VALIDATION_TYPE_BLOOM = "bloom"
VALIDATION_TYPE_TRIVIALITY = "triviality"
VALIDATION_TYPE_CORRECTNESS = "correctness"


# ── Result types ──────────────────────────────────────────────────────────────


class GroundingOutcome(str, enum.Enum):
    """Three-level outcome for grounding checks."""

    PASS = "pass"   # ≥1 source with a non-null chunk_id
    WARN = "warn"   # ≥1 source but no chunk_id on any of them
    FAIL = "fail"   # zero QuestionSource rows


# Scores stored in QuestionValidation.score per outcome level.
_GROUNDING_SCORE: dict[GroundingOutcome, float] = {
    GroundingOutcome.PASS: 1.0,
    GroundingOutcome.WARN: 0.5,
    GroundingOutcome.FAIL: 0.0,
}


@dataclass
class GroundingValidationResult:
    """
    Full result of a grounding check on a single question.

    Attributes
    ----------
    question_id  : UUID of the checked question.
    outcome      : PASS / WARN / FAIL.
    passed       : True for PASS and WARN; False for FAIL.
    score        : Numeric score mapped from outcome (1.0 / 0.5 / 0.0).
    source_count : Number of QuestionSource rows found.
    sources_with_chunk_id : How many of those have a non-null chunk_id.
    detail       : Human-readable message for display / logging.
    """

    question_id: uuid.UUID
    outcome: GroundingOutcome
    passed: bool
    score: float
    source_count: int
    sources_with_chunk_id: int
    detail: str
    extra: dict = field(default_factory=dict)


# ── Distractor validation types ─────────────────────────────────────────────


class DistractorOutcome(str, enum.Enum):
    """Outcome levels for MCQ distractor checks."""

    PASS = "pass"  # all rule-based checks pass
    WARN = "warn"  # structural OK; one or more quality issues
    FAIL = "fail"  # structural violation (count, uniqueness, correct-count)


_DISTRACTOR_SCORE: dict[DistractorOutcome, float] = {
    DistractorOutcome.PASS: 1.0,
    DistractorOutcome.WARN: 0.5,
    DistractorOutcome.FAIL: 0.0,
}

# Phrases that indicate a catch-all option — always a WARN.
_ALL_OF_ABOVE_PATTERNS = {
    "all of the above",
    "all of the above.",
    "none of the above",
    "none of the above.",
    "all of these",
    "none of these",
    "both a and b",
    "both of the above",
}

# Options are flagged as a length outlier when the longest option text is
# more than this multiple of the mean option length.
_LENGTH_OUTLIER_RATIO = 3.0


@dataclass
class DistractorIssue:
    """A single issue found during distractor validation."""

    severity: str              # "fail" or "warn"
    code: str                  # short machine-readable key
    message: str               # human-readable description
    option_label: str | None = None  # "A"–"D" when the issue is option-specific


@dataclass
class DistractorValidationResult:
    """
    Full result of a distractor quality check on a single MCQ question.

    Attributes
    ----------
    question_id : UUID of the checked question.
    outcome     : PASS / WARN / FAIL.
    passed      : True for PASS and WARN; False for FAIL.
    score       : 1.0 / 0.5 / 0.0.
    issues      : List of individual issues found (empty for PASS).
    option_count: Number of McqOption rows found.
    correct_count: Number of options with is_correct=True.
    """

    question_id: uuid.UUID
    outcome: DistractorOutcome
    passed: bool
    score: float
    issues: list[DistractorIssue]
    option_count: int
    correct_count: int


# ── Triviality validation types ──────────────────────────────────────────────


class TrivialityOutcome(str, enum.Enum):
    """Outcome levels for triviality checks."""
    PASS = "pass"   # question is non-trivial (requires reasoning)
    WARN = "warn"   # trivial stem but difficulty=EASY or bloom=REMEMBER (acceptable)
    FAIL = "fail"   # trivial stem AND difficulty is MEDIUM or HARD


_TRIVIALITY_SCORE: dict[TrivialityOutcome, float] = {
    TrivialityOutcome.PASS: 1.0,
    TrivialityOutcome.WARN: 0.5,
    TrivialityOutcome.FAIL: 0.0,
}


@dataclass
class TrivialityValidationResult:
    """Full result of a triviality check on a single question."""
    question_id: uuid.UUID
    outcome: TrivialityOutcome
    passed: bool
    score: float
    is_trivial: bool
    target_difficulty: str
    target_bloom: str
    detail: str


def check_trivial_stem(stem: str) -> bool:
    """Return True if *stem* matches known trivial definition/recall patterns."""
    from app.utils.chunk_filter import is_trivial_question  # local import avoids cycle
    return is_trivial_question(stem)


# ── Correctness verification types ────────────────────────────────────────────


class CorrectnessVerdict(str, enum.Enum):
    """Possible outcomes from the LLM correctness verifier."""
    CORRECT           = "correct"            # label / marked option is definitively right
    WRONG_LABEL       = "wrong_label"        # TF: truth label is inverted
    WRONG_CORRECT     = "wrong_correct"      # MCQ: a different option is clearly best
    MULTIPLE_CORRECT  = "multiple_correct"   # MCQ: two+ options are defensibly correct
    AMBIGUOUS         = "ambiguous"          # context does not resolve the question
    ERROR             = "error"              # verifier LLM call failed


_CORRECTNESS_SCORE: dict[CorrectnessVerdict, float] = {
    CorrectnessVerdict.CORRECT:          1.0,
    CorrectnessVerdict.AMBIGUOUS:        0.5,
    CorrectnessVerdict.WRONG_LABEL:      0.0,
    CorrectnessVerdict.WRONG_CORRECT:    0.0,
    CorrectnessVerdict.MULTIPLE_CORRECT: 0.0,
    CorrectnessVerdict.ERROR:            0.5,  # fail-open
}


@dataclass
class CorrectnessResult:
    """
    Result of a pre-persist correctness verification pass.

    Shared by TF and MCQ verification; type-specific fields are nullable.

    Attributes
    ----------
    verdict         : Classification outcome.
    confidence      : 0.0–1.0 from the verifier LLM.
    reason          : One-sentence explanation referencing context.
    should_reject   : True → caller must NOT persist this question.
    should_flip     : True → TF answer label was wrong; flip before persisting.
    correct_is_true : New truth value when should_flip=True (TF only).
    correct_key     : Best option key per verifier (MCQ only).
    question_type   : "tf" | "mcq" — discriminator for downstream handling.
    """

    verdict:         CorrectnessVerdict
    confidence:      float
    reason:          str
    should_reject:   bool
    should_flip:     bool = False
    correct_is_true: bool | None = None
    correct_key:     str | None  = None
    question_type:   str         = "unknown"


# ── LLM output schemas (parsed from verifier responses) ──────────────────────


class _LLMTFCorrectnessOutput(BaseModel):
    """Pydantic schema for TF correctness verifier LLM response."""

    verdict:       str   = Field(default="ambiguous")
    confidence:    float = Field(default=0.5, ge=0.0, le=1.0)
    reason:        str   = Field(default="")
    should_be_true: bool = Field(default=True)


class _LLMMCQCorrectnessOutput(BaseModel):
    """Pydantic schema for MCQ correctness verifier LLM response."""

    verdict:     str   = Field(default="ambiguous")
    confidence:  float = Field(default=0.5, ge=0.0, le=1.0)
    reason:      str   = Field(default="")
    correct_key: str   = Field(default="A")


# ── Pure helper functions (testable without DB) ───────────────────────────────


def _normalize(text: str) -> str:
    """Lower-case, strip punctuation extremes, collapse whitespace."""
    return " ".join(text.lower().strip().strip(".").split())


def check_option_count(options: list[McqOption]) -> DistractorIssue | None:
    """Exactly 4 options required — anything else is a FAIL."""
    n = len(options)
    if n != 4:
        return DistractorIssue(
            severity="fail",
            code="wrong_option_count",
            message=f"Expected exactly 4 options, found {n}.",
        )
    return None


def check_correct_count(options: list[McqOption]) -> DistractorIssue | None:
    """Exactly 1 correct answer required — anything else is a FAIL."""
    correct = [o for o in options if o.is_correct]
    n = len(correct)
    if n == 0:
        return DistractorIssue(
            severity="fail",
            code="no_correct_option",
            message="No option is marked as correct (is_correct=True).",
        )
    if n > 1:
        labels = ", ".join(o.label for o in correct)
        return DistractorIssue(
            severity="fail",
            code="multiple_correct_options",
            message=f"{n} options are marked correct (labels: {labels}); exactly 1 is required.",
        )
    return None


def check_uniqueness(options: list[McqOption]) -> list[DistractorIssue]:
    """
    Normalised duplicate detection.

    Pairs of options whose normalised text is identical are a FAIL —
    a student can trivially eliminate one without reading the material.
    """
    seen: dict[str, str] = {}  # normalised_text → first label
    issues: list[DistractorIssue] = []
    for opt in options:
        key = _normalize(opt.text)
        if key in seen:
            issues.append(
                DistractorIssue(
                    severity="fail",
                    code="duplicate_option_text",
                    message=(
                        f"Option {opt.label} has the same normalised text as "
                        f"option {seen[key]}: {opt.text!r}."
                    ),
                    option_label=opt.label,
                )
            )
        else:
            seen[key] = opt.label
    return issues


def check_catch_all_phrases(options: list[McqOption]) -> list[DistractorIssue]:
    """
    Warn when an option is a catch-all phrase such as "all of the above".

    These phrases signal lazy distractor design and can allow test-wise
    students to guess correctly without understanding the material.
    """
    issues: list[DistractorIssue] = []
    for opt in options:
        if _normalize(opt.text) in _ALL_OF_ABOVE_PATTERNS:
            issues.append(
                DistractorIssue(
                    severity="warn",
                    code="catch_all_phrase",
                    message=(
                        f"Option {opt.label} uses a catch-all phrase: {opt.text!r}. "
                        "This reduces question validity."
                    ),
                    option_label=opt.label,
                )
            )
    return issues


def check_length_outlier(options: list[McqOption]) -> DistractorIssue | None:
    """
    Warn when one option is disproportionately longer than the others.

    A very long option is often the correct answer (students learn to pick
    the most detailed option), which undermines the question's validity.
    Triggers when max_length > mean_length * _LENGTH_OUTLIER_RATIO.
    """
    if not options:
        return None
    lengths = [len(o.text) for o in options]
    mean_len = sum(lengths) / len(lengths)
    if mean_len == 0:
        return None
    max_len = max(lengths)
    if max_len > mean_len * _LENGTH_OUTLIER_RATIO:
        outlier = options[lengths.index(max_len)]
        return DistractorIssue(
            severity="warn",
            code="length_outlier",
            message=(
                f"Option {outlier.label} is {max_len} chars, "
                f"{max_len / mean_len:.1f}× the mean ({mean_len:.0f} chars). "
                "Overly long options may inadvertently signal the correct answer."
            ),
            option_label=outlier.label,
        )
    return None


def evaluate_distractor_issues(
    question_id: uuid.UUID,
    options: list[McqOption],
) -> DistractorValidationResult:
    """
    Run all distractor checks against *options* and return a result.

    This is a **pure function** — it does not touch the database.
    Call it from validate_mcq_distractors or directly in unit tests.
    """
    issues: list[DistractorIssue] = []

    # Structural checks (potential FAIL)
    if (issue := check_option_count(options)) is not None:
        issues.append(issue)
    if (issue := check_correct_count(options)) is not None:
        issues.append(issue)
    issues.extend(check_uniqueness(options))

    # Quality checks (potential WARN — only run when structure is valid)
    has_fail = any(i.severity == "fail" for i in issues)
    if not has_fail:
        issues.extend(check_catch_all_phrases(options))
        if (issue := check_length_outlier(options)) is not None:
            issues.append(issue)

    # Determine outcome
    if has_fail or any(i.severity == "fail" for i in issues):
        outcome = DistractorOutcome.FAIL
    elif issues:  # only WARNs remain
        outcome = DistractorOutcome.WARN
    else:
        outcome = DistractorOutcome.PASS

    correct_count = sum(1 for o in options if o.is_correct)

    return DistractorValidationResult(
        question_id=question_id,
        outcome=outcome,
        passed=(outcome != DistractorOutcome.FAIL),
        score=_DISTRACTOR_SCORE[outcome],
        issues=issues,
        option_count=len(options),
        correct_count=correct_count,
    )


# ── Difficulty tagging helpers (pure — no DB) ─────────────────────────────────


# ── Keyword/verb lists for heuristic classification ───────────────────────────

# Verbs / phrases that strongly suggest higher cognitive demand (hard → medium).
_HARD_VERBS = re.compile(
    r"\b(evaluat|analys|analyz|synthesiz|design|justify|critiqu|compar|contrast"
    r"|differentiat|assess|argue|formulat|construct|develop|creat)\w*\b",
    re.IGNORECASE,
)
_MEDIUM_VERBS = re.compile(
    r"\b(explain|describ|illustrat|classif|summariz|interpret|appl|demonstrat"
    r"|calculat|solv|show|outline|discuss|predict|relate)\w*\b",
    re.IGNORECASE,
)
# Indicators of direct recall (easy).
_EASY_VERBS = re.compile(
    r"\b(identif|list|name|state|defin|recall|recogniz|what is|which|who|when|where)\w*\b",
    re.IGNORECASE,
)

# Compound sentences (many commas / conjunctions) hint at complexity.
_COMPLEXITY_RE = re.compile(r"(,|\band\b|\bor\b|\bbut\b|\bhowever\b|\btherefore\b)", re.IGNORECASE)


@dataclass
class _HeuristicResult:
    difficulty: Difficulty
    confidence: float
    reasoning: str


def _heuristic_difficulty(question_text: str) -> _HeuristicResult:
    """
    Fast keyword-based difficulty estimation.  No external calls.

    Scoring:
      • Count hard-verb matches  → add +2 each (cap at 4 matches considered)
      • Count medium-verb matches → add +1 each (cap at 4)
      • Count easy-verb matches  → subtract -1 each
      • Sentence complexity (# conjunctions / commas) → add +0.5 per 2 found
      • Very short question (<= 8 words) → easy bias -1

    Score mapping:
      < 0    → easy    confidence 0.6
      0–2    → medium  confidence 0.55
      > 2    → hard    confidence 0.65
    """
    text = question_text.strip()
    words = text.split()
    word_count = len(words)

    hard_hits = min(len(_HARD_VERBS.findall(text)), 4)
    medium_hits = min(len(_MEDIUM_VERBS.findall(text)), 4)
    easy_hits = len(_EASY_VERBS.findall(text))
    complexity_hits = len(_COMPLEXITY_RE.findall(text))

    score: float = (hard_hits * 2.0) + (medium_hits * 1.0) - (easy_hits * 1.0)
    score += (complexity_hits // 2) * 0.5
    if word_count <= 8:
        score -= 1.0

    if score > 2:
        difficulty = Difficulty.hard
        confidence = min(0.5 + hard_hits * 0.08, 0.75)
        reason = (
            f"Hard-level verbs detected ({hard_hits}x); "
            f"sentence complexity score={score:.1f}."
        )
    elif score > 0:
        difficulty = Difficulty.medium
        confidence = 0.55
        reason = (
            f"Medium-level reasoning verbs detected ({medium_hits}x); "
            f"no strong hard indicators. Score={score:.1f}."
        )
    else:
        difficulty = Difficulty.easy
        confidence = min(0.5 + easy_hits * 0.08, 0.70)
        reason = (
            f"Recall / identification verbs dominate ({easy_hits}x easy); "
            f"score={score:.1f}."
        )

    return _HeuristicResult(difficulty=difficulty, confidence=confidence, reasoning=reason)


# ── LLM difficulty via provider ───────────────────────────────────────────────


class _LLMDifficultyOutput(BaseModel):
    """Pydantic schema for parsing the LLM difficulty-classifier response."""

    difficulty: str = Field(..., description="easy | medium | hard")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = Field(default="")


@dataclass
class _LLMDifficultyResult:
    difficulty: Difficulty
    confidence: float
    reasoning: str


async def _llm_difficulty(
    provider: "BaseLLMProvider",
    *,
    question_text: str,
    answer_hint: str | None,
) -> _LLMDifficultyResult:
    """
    Ask the LLM provider to classify difficulty.
    Raises on provider or parse errors (caller must handle).
    """
    from app.llm.prompts.difficulty_classifier import (
        DIFFICULTY_CLASSIFIER_SYSTEM,
        DIFFICULTY_CLASSIFIER_USER,
    )

    hint_text = f"Correct answer: {answer_hint}" if answer_hint else ""
    prompt = (
        DIFFICULTY_CLASSIFIER_SYSTEM
        + "\n---\n"
        + DIFFICULTY_CLASSIFIER_USER.format(
            question_text=question_text,
            answer_hint=hint_text,
        )
    )

    # Low temperature for classification — we want determinism.
    settings = GenerationSettings(temperature=0.1, max_tokens=256)
    output: _LLMDifficultyOutput = await provider.generate_json(
        prompt, _LLMDifficultyOutput, settings
    )

    # Map the raw string to the enum; default to medium on unknown values.
    try:
        difficulty_enum = Difficulty(output.difficulty.lower().strip())
    except ValueError:
        difficulty_enum = Difficulty.medium

    return _LLMDifficultyResult(
        difficulty=difficulty_enum,
        confidence=output.confidence,
        reasoning=output.reasoning,
    )


# ── Public result type ────────────────────────────────────────────────────────


@dataclass
class DifficultyTaggingResult:
    """
    Full result of a difficulty tagging operation.

    Attributes
    ----------
    question_id          : UUID of the tagged question.
    difficulty           : Final assigned Difficulty (easy/medium/hard).
    confidence           : 0.0–1.0; LLM confidence when used, heuristic otherwise.
    reasoning            : One-sentence explanation of the classification.
    used_llm             : True when the LLM overrode the heuristic guess.
    heuristic_difficulty : The heuristic pre-classification (for audit trail).
    """

    question_id: uuid.UUID
    difficulty: Difficulty
    confidence: float
    reasoning: str
    used_llm: bool
    heuristic_difficulty: Difficulty


# ── Bloom taxonomy helpers ───────────────────────────────────────────────────

# Verb patterns per Bloom level (higher order first — evaluated in order).
# Using word boundaries so "create" doesn't match "recreate" etc.
_BLOOM_PATTERNS: list[tuple[BloomLevel, re.Pattern[str]]] = [
    (
        BloomLevel.create,
        re.compile(
            r"\b(design|create|construct|develop|formulate|plan|compose|produce"
            r"|invent|build|generate|devise|hypothesize|synthesize|synthesise)\b",
            re.IGNORECASE,
        ),
    ),
    (
        BloomLevel.evaluate,
        re.compile(
            r"\b(evaluate|judge|critique|justify|defend|assess|appraise|argue"
            r"|prioritize|prioritise|recommend|select|decide|conclude)\b",
            re.IGNORECASE,
        ),
    ),
    (
        BloomLevel.analyze,
        re.compile(
            r"\b(analyze|analyse|differentiate|distinguish|examine|compare|contrast"
            r"|categorize|categorise|classify|investigate|break\s+down|outline"
            r"|relate|dissect|infer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        BloomLevel.apply,
        re.compile(
            r"\b(calculate|solve|apply|use|demonstrate|implement|execute"
            r"|carry\s+out|operate|show|illustrate|compute|predict|determine)\b",
            re.IGNORECASE,
        ),
    ),
    (
        BloomLevel.understand,
        re.compile(
            r"\b(explain|summarize|summarise|describe|paraphrase|interpret"
            r"|identify|convert|translate|discuss|review|restate|give\s+an\s+example)\b",
            re.IGNORECASE,
        ),
    ),
    (
        BloomLevel.remember,
        re.compile(
            r"\b(define|list|recall|recognise|recognize|name|state|repeat"
            r"|label|match|arrange|memorize|memorise|locate|quote)\b",
            re.IGNORECASE,
        ),
    ),
]

# Default confidence values for the heuristic.
_BLOOM_HEURISTIC_HIT_CONFIDENCE: float = 0.65
_BLOOM_HEURISTIC_DEFAULT_CONFIDENCE: float = 0.40


@dataclass
class _BloomHeuristicResult:
    bloom_level: BloomLevel
    confidence: float
    matched_verb: str | None


def _heuristic_bloom(question_text: str) -> _BloomHeuristicResult:
    """
    Classify Bloom taxonomy level by scanning for known cognitive-verb patterns.

    Checks patterns from highest to lowest Bloom level so that higher-order
    verbs take precedence. Falls back to ``remember`` when no verb matches.
    """
    # Only scan the first sentence — where the cognitive verb usually lives.
    first_sentence = question_text.split("?")[0].split(".")[0]
    for level, pattern in _BLOOM_PATTERNS:
        m = pattern.search(first_sentence)
        if m:
            return _BloomHeuristicResult(
                bloom_level=level,
                confidence=_BLOOM_HEURISTIC_HIT_CONFIDENCE,
                matched_verb=m.group(0).lower(),
            )
    return _BloomHeuristicResult(
        bloom_level=BloomLevel.remember,
        confidence=_BLOOM_HEURISTIC_DEFAULT_CONFIDENCE,
        matched_verb=None,
    )


# ── LLM Bloom classification ──────────────────────────────────────────────────

# Map British spelling (used in prompt) to the ORM enum value (American).
_BLOOM_BRITISH_TO_AMERICAN: dict[str, str] = {
    "analyse": "analyze",
}


class _LLMBloomOutput(BaseModel):
    """Pydantic schema for parsing the LLM bloom-classifier response."""

    bloom_level: str = Field(..., description="One of the six Bloom levels")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    key_verb: str = Field(default="")


@dataclass
class _LLMBloomResult:
    bloom_level: BloomLevel
    confidence: float
    reasoning: str
    key_verb: str


async def _llm_bloom(
    provider: "BaseLLMProvider",
    *,
    question_text: str,
) -> _LLMBloomResult:
    """
    Ask the LLM provider to classify Bloom taxonomy level.
    Raises on provider or parse errors (caller must handle).
    """
    from app.llm.prompts.bloom_classifier import (
        BLOOM_CLASSIFIER_SYSTEM,
        BLOOM_CLASSIFIER_USER,
    )

    prompt = (
        BLOOM_CLASSIFIER_SYSTEM
        + "\n---\n"
        + BLOOM_CLASSIFIER_USER.format(question_text=question_text)
    )

    settings = GenerationSettings(temperature=0.1, max_tokens=256)
    output: _LLMBloomOutput = await provider.generate_json(
        prompt, _LLMBloomOutput, settings
    )

    # Normalise spelling and look up the enum; fall back to remember.
    raw = output.bloom_level.lower().strip()
    raw = _BLOOM_BRITISH_TO_AMERICAN.get(raw, raw)
    try:
        bloom_enum = BloomLevel(raw)
    except ValueError:
        bloom_enum = BloomLevel.remember

    return _LLMBloomResult(
        bloom_level=bloom_enum,
        confidence=output.confidence,
        reasoning=output.reasoning,
        key_verb=output.key_verb,
    )


# ── Public result type ────────────────────────────────────────────────────────


@dataclass
class BloomTaggingResult:
    """
    Full result of a Bloom taxonomy tagging operation.

    Attributes
    ----------
    question_id         : UUID of the tagged question.
    bloom_level         : Final assigned BloomLevel.
    confidence          : 0.0–1.0.
    reasoning           : Explanation of the classification.
    used_llm            : True when the LLM overrode the heuristic guess.
    heuristic_level     : The heuristic pre-classification (for audit trail).
    key_verb            : Cognitive verb that triggered the classification.
    """

    question_id: uuid.UUID
    bloom_level: BloomLevel
    confidence: float
    reasoning: str
    used_llm: bool
    heuristic_level: BloomLevel
    key_verb: str | None


# ── Validation Service ────────────────────────────────────────────────────────


class ValidationService:
    """
    Runs quality-control checks on generated questions and writes results
    to the question_validations table.

    All public methods are async and accept an open SQLAlchemy AsyncSession.
    The caller is responsible for committing / rolling back.
    """

    # ------------------------------------------------------------------ #
    # Grounding validation                                                 #
    # ------------------------------------------------------------------ #

    async def validate_grounding(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        *,
        persist: bool = True,
    ) -> GroundingValidationResult:
        """
        Check that *question_id* has at least one traceable source chunk.

        Parameters
        ----------
        db         : Open async session.
        question_id: UUID of the question to check.
        persist    : When True (default) a QuestionValidation row is written.
                     Pass False in tests to run the logic without any DB writes.

        Returns
        -------
        GroundingValidationResult with the full check outcome.
        """
        # ── Fetch sources ──────────────────────────────────────────────
        stmt = select(QuestionSource).where(
            QuestionSource.question_id == question_id
        )
        result = await db.execute(stmt)
        sources: list[QuestionSource] = list(result.scalars().all())

        source_count = len(sources)
        sources_with_chunk = [s for s in sources if s.chunk_id is not None]
        sources_with_chunk_id = len(sources_with_chunk)

        # ── Determine outcome ──────────────────────────────────────────
        if source_count == 0:
            outcome = GroundingOutcome.FAIL
            detail = (
                "No QuestionSource rows found. "
                "This question has no traceability to any course material chunk."
            )
        elif sources_with_chunk_id == 0:
            outcome = GroundingOutcome.WARN
            detail = (
                f"{source_count} source row(s) exist but none carry a chunk_id. "
                "Traceability is partial (hint-only, no vector chunk reference)."
            )
        else:
            outcome = GroundingOutcome.PASS
            detail = (
                f"{sources_with_chunk_id}/{source_count} source(s) carry a valid chunk_id. "
                "Grounding is fully traceable."
            )

        score = _GROUNDING_SCORE[outcome]
        passed = outcome != GroundingOutcome.FAIL

        validation_result = GroundingValidationResult(
            question_id=question_id,
            outcome=outcome,
            passed=passed,
            score=score,
            source_count=source_count,
            sources_with_chunk_id=sources_with_chunk_id,
            detail=detail,
            extra={
                "source_ids": [str(s.id) for s in sources],
                "chunk_ids": [str(s.chunk_id) for s in sources_with_chunk],
            },
        )

        logger.debug(
            "grounding_validation: question=%s outcome=%s sources=%d chunk_refs=%d",
            question_id,
            outcome.value,
            source_count,
            sources_with_chunk_id,
        )

        # ── Persist result ─────────────────────────────────────────────
        if persist:
            detail_payload = {
                "outcome": outcome.value,
                "source_count": source_count,
                "sources_with_chunk_id": sources_with_chunk_id,
                "message": detail,
                **validation_result.extra,
            }
            await self._write_validation(
                db,
                question_id=question_id,
                validation_type=VALIDATION_TYPE_GROUNDING,
                passed=passed,
                score=score,
                detail=json.dumps(detail_payload),
            )

        return validation_result

    async def validate_grounding_batch(
        self,
        db: AsyncSession,
        question_ids: list[uuid.UUID],
        *,
        persist: bool = True,
    ) -> list[GroundingValidationResult]:
        """
        Run grounding validation on multiple questions.

        Returns one result per question in the same order as *question_ids*.
        Failures on individual questions are caught and logged; the batch
        continues rather than aborting on one bad question.
        """
        results: list[GroundingValidationResult] = []
        for qid in question_ids:
            try:
                r = await self.validate_grounding(db, qid, persist=persist)
                results.append(r)
            except Exception as exc:
                logger.error(
                    "validate_grounding_batch: failed for question=%s: %s",
                    qid,
                    exc,
                    exc_info=True,
                )
        return results

    # ------------------------------------------------------------------ #
    # Distractor validation                                                #
    # ------------------------------------------------------------------ #

    async def validate_mcq_distractors(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        *,
        persist: bool = True,
    ) -> DistractorValidationResult:
        """
        Run all rule-based MCQ distractor checks for *question_id*.

        Fetches McqOption rows from the DB, delegates to the pure
        ``evaluate_distractor_issues()`` function, then optionally persists
        a QuestionValidation row.

        Parameters
        ----------
        db          : Open async session.
        question_id : UUID of the MCQ question to check.
        persist     : When True (default) a QuestionValidation row is written.

        Returns
        -------
        DistractorValidationResult with outcome, score, and issue list.
        """
        # ── Fetch options ──────────────────────────────────────────────
        stmt = (
            select(McqOption)
            .where(McqOption.question_id == question_id)
            .order_by(McqOption.label)
        )
        result = await db.execute(stmt)
        options: list[McqOption] = list(result.scalars().all())

        # ── Evaluate (pure, no DB) ─────────────────────────────────────
        validation_result = evaluate_distractor_issues(question_id, options)

        logger.debug(
            "distractor_validation: question=%s outcome=%s issues=%d",
            question_id,
            validation_result.outcome.value,
            len(validation_result.issues),
        )

        # ── Persist result ─────────────────────────────────────────────
        if persist:
            detail_payload: dict = {
                "outcome": validation_result.outcome.value,
                "option_count": validation_result.option_count,
                "correct_count": validation_result.correct_count,
                "issues": [
                    {
                        "severity": iss.severity,
                        "code": iss.code,
                        "message": iss.message,
                        "option_label": iss.option_label,
                    }
                    for iss in validation_result.issues
                ],
            }
            await self._write_validation(
                db,
                question_id=question_id,
                validation_type=VALIDATION_TYPE_DISTRACTOR,
                passed=validation_result.passed,
                score=validation_result.score,
                detail=json.dumps(detail_payload),
            )

        return validation_result

    # ------------------------------------------------------------------ #
    # Difficulty tagging                                                   #
    # ------------------------------------------------------------------ #

    async def tag_difficulty(
        self,
        db: AsyncSession,
        question: Question,
        *,
        provider: "BaseLLMProvider | None" = None,
        persist: bool = True,
        update_question: bool = True,
    ) -> "DifficultyTaggingResult":
        """
        Classify the difficulty of *question* using a two-stage hybrid approach:

        Stage 1 — Heuristic pre-classification (always runs, no LLM).
            Fast keyword / structural analysis of the question body.
            Returns an initial guess and a confidence score.

        Stage 2 — LLM refinement (only when *provider* is supplied).
            Calls the provider with the difficulty classifier prompt.
            If the LLM call fails or *provider* is None the heuristic
            result is used as-is.

        Parameters
        ----------
        db              : Open async session.
        question        : ORM Question instance (body + correct_answer used).
        provider        : Optional LLM provider.  Pass None to use heuristics only.
        persist         : Write a QuestionValidation row when True (default).
        update_question : Update Question.difficulty in-place when True (default).

        Returns
        -------
        DifficultyTaggingResult with final difficulty, confidence, reasoning,
        and which stage produced the result.
        """
        # ── Stage 1: heuristic ─────────────────────────────────────────
        heuristic = _heuristic_difficulty(question.body)
        final_difficulty = heuristic.difficulty
        final_confidence = heuristic.confidence
        final_reasoning = heuristic.reasoning
        used_llm = False

        # ── Stage 2: LLM refinement ────────────────────────────────────
        if provider is not None:
            try:
                llm_result = await _llm_difficulty(
                    provider,
                    question_text=question.body,
                    answer_hint=question.correct_answer,
                )
                final_difficulty = llm_result.difficulty
                final_confidence = llm_result.confidence
                final_reasoning = llm_result.reasoning
                used_llm = True
                logger.debug(
                    "tag_difficulty: LLM override question=%s difficulty=%s confidence=%.2f",
                    question.id,
                    final_difficulty.value,
                    final_confidence,
                )
            except Exception as exc:
                logger.warning(
                    "tag_difficulty: LLM call failed for question=%s, "
                    "falling back to heuristic (%s). Error: %s",
                    question.id,
                    heuristic.difficulty.value,
                    exc,
                )

        # Post-check C: trivial definition stems must not be tagged MEDIUM/HARD.
        # If the stem is a direct recall question, cap the difficulty to EASY
        # and store a note in the reasoning for auditability.
        if check_trivial_stem(question.body) and final_difficulty in (
            Difficulty.medium, Difficulty.hard
        ):
            logger.debug(
                "tag_difficulty: overriding %s → easy for trivial stem question=%s",
                final_difficulty.value, question.id,
            )
            final_difficulty = Difficulty.easy
            final_confidence = max(final_confidence, 0.55)
            final_reasoning = (
                final_reasoning
                + "; [overridden→EASY: stem matches trivial definition/recall pattern]"
            )

        result = DifficultyTaggingResult(
            question_id=question.id,
            difficulty=final_difficulty,
            confidence=final_confidence,
            reasoning=final_reasoning,
            used_llm=used_llm,
            heuristic_difficulty=heuristic.difficulty,
        )

        logger.debug(
            "tag_difficulty: question=%s difficulty=%s confidence=%.2f used_llm=%s",
            question.id,
            final_difficulty.value,
            final_confidence,
            used_llm,
        )

        # ── Update Question row ────────────────────────────────────────
        if update_question:
            question.difficulty = final_difficulty
            db.add(question)
            await db.flush()

        # ── Persist validation row ─────────────────────────────────────
        if persist:
            detail_payload = {
                "difficulty": final_difficulty.value,
                "confidence": final_confidence,
                "reasoning": final_reasoning,
                "used_llm": used_llm,
                "heuristic_difficulty": heuristic.difficulty.value,
                "heuristic_confidence": heuristic.confidence,
                "heuristic_reasoning": heuristic.reasoning,
            }
            await self._write_validation(
                db,
                question_id=question.id,
                validation_type=VALIDATION_TYPE_DIFFICULTY,
                passed=True,  # difficulty tagging always "passes" — it is a tag, not a gate
                score=final_confidence,
                detail=json.dumps(detail_payload),
            )

        return result

    # ------------------------------------------------------------------ #
    # Bloom tagging                                                        #
    # ------------------------------------------------------------------ #

    async def tag_bloom(
        self,
        db: AsyncSession,
        question: Question,
        *,
        provider: "BaseLLMProvider | None" = None,
        persist: bool = True,
        update_question: bool = True,
    ) -> "BloomTaggingResult":
        """
        Classify the Bloom taxonomy level of *question* using a two-stage approach.

        Stage 1 — Heuristic pre-classification (always runs, no LLM).
            Scans the question body for known cognitive-verb patterns.

        Stage 2 — LLM refinement (only when *provider* is supplied).
            Calls the provider with the Bloom classifier prompt.
            Falls back to the heuristic result on any error.

        Parameters
        ----------
        db              : Open async session.
        question        : ORM Question instance (body used).
        provider        : Optional LLM provider.  Pass None to use heuristics only.
        persist         : Write a QuestionValidation row when True (default).
        update_question : Update Question.bloom_level in-place when True (default).

        Returns
        -------
        BloomTaggingResult with final bloom level, confidence, and audit info.
        """
        # ── Stage 1: heuristic ─────────────────────────────────────────
        heuristic = _heuristic_bloom(question.body)
        final_level = heuristic.bloom_level
        final_confidence = heuristic.confidence
        final_reasoning = f"Heuristic match on verb: {heuristic.matched_verb!r}" if heuristic.matched_verb else "No cognitive verb detected; defaulting to remember"
        final_key_verb: str | None = heuristic.matched_verb
        used_llm = False

        # ── Stage 2: LLM refinement ────────────────────────────────────
        if provider is not None:
            try:
                llm_result = await _llm_bloom(provider, question_text=question.body)
                final_level = llm_result.bloom_level
                final_confidence = llm_result.confidence
                final_reasoning = llm_result.reasoning
                final_key_verb = llm_result.key_verb or heuristic.matched_verb
                used_llm = True
                logger.debug(
                    "tag_bloom: LLM override question=%s bloom=%s confidence=%.2f",
                    question.id,
                    final_level.value,
                    final_confidence,
                )
            except Exception as exc:
                logger.warning(
                    "tag_bloom: LLM call failed for question=%s, "
                    "falling back to heuristic (%s). Error: %s",
                    question.id,
                    heuristic.bloom_level.value,
                    exc,
                )

        # Post-check C: cap trivial stems to UNDERSTAND (Bloom level 2) at most.
        if check_trivial_stem(question.body) and final_level not in (
            BloomLevel.remember, BloomLevel.understand
        ):
            logger.debug(
                "tag_bloom: overriding %s → understand for trivial stem question=%s",
                final_level.value, question.id,
            )
            final_level = BloomLevel.understand
            final_key_verb = final_key_verb or "define/recall"
            final_confidence = max(final_confidence, 0.55)
            final_reasoning = (
                final_reasoning
                + "; [overridden→UNDERSTAND: stem matches trivial definition/recall pattern]"
            )

        result = BloomTaggingResult(
            question_id=question.id,
            bloom_level=final_level,
            confidence=final_confidence,
            reasoning=final_reasoning,
            used_llm=used_llm,
            heuristic_level=heuristic.bloom_level,
            key_verb=final_key_verb,
        )

        logger.debug(
            "tag_bloom: question=%s bloom=%s confidence=%.2f used_llm=%s",
            question.id,
            final_level.value,
            final_confidence,
            used_llm,
        )

        # ── Update Question row ────────────────────────────────────────
        if update_question:
            question.bloom_level = final_level
            db.add(question)
            await db.flush()

        # ── Persist validation row ─────────────────────────────────────
        if persist:
            detail_payload = {
                "bloom_level": final_level.value,
                "confidence": final_confidence,
                "reasoning": final_reasoning,
                "used_llm": used_llm,
                "key_verb": final_key_verb,
                "heuristic_level": heuristic.bloom_level.value,
                "heuristic_confidence": heuristic.confidence,
                "heuristic_verb": heuristic.matched_verb,
            }
            await self._write_validation(
                db,
                question_id=question.id,
                validation_type=VALIDATION_TYPE_BLOOM,
                passed=True,  # bloom tagging is a tag, not a gate
                score=final_confidence,
                detail=json.dumps(detail_payload),
            )

        return result

    # ------------------------------------------------------------------ #
    # Triviality validator                                                 #
    # ------------------------------------------------------------------ #

    async def validate_triviality(
        self,
        db: AsyncSession,
        question: Question,
        *,
        target_difficulty: str = "medium",
        target_bloom: str = "apply",
        save: bool = True,
    ) -> TrivialityValidationResult:
        """
        Check whether the question stem is a trivial definition/recall question
        and whether that is acceptable given the target difficulty and Bloom level.

        A FAIL is issued when:
          - The stem matches a known trivial pattern (What is X? / Define X / …)
          - AND target difficulty is not EASY
          - AND target Bloom level is not REMEMBER

        A WARN is issued when the stem is trivial but the slot targets easy/remember
        (i.e., recall questions are acceptable for that slot).

        PASS is issued when the stem does not match any trivial pattern.

        Parameters
        ----------
        db                 : Open async session.
        question           : The Question ORM instance to check.
        target_difficulty  : Difficulty string the slot was targeting.
        target_bloom       : Bloom level string the slot was targeting.
        save               : If True, persist a QuestionValidation row.
        """
        stem = question.body or ""
        trivial = check_trivial_stem(stem)

        is_easy = target_difficulty.lower() == "easy"
        is_recall = target_bloom.lower() == "remember"

        if not trivial:
            outcome = TrivialityOutcome.PASS
        elif is_easy or is_recall:
            outcome = TrivialityOutcome.WARN
        else:
            outcome = TrivialityOutcome.FAIL

        score = _TRIVIALITY_SCORE[outcome]
        passed = outcome in (TrivialityOutcome.PASS, TrivialityOutcome.WARN)

        detail = (
            f"Stem appears trivial={trivial}; "
            f"target_difficulty={target_difficulty}, target_bloom={target_bloom}; "
            f"outcome={outcome.value}"
        )

        result = TrivialityValidationResult(
            question_id=question.id,
            outcome=outcome,
            passed=passed,
            score=score,
            is_trivial=trivial,
            target_difficulty=target_difficulty,
            target_bloom=target_bloom,
            detail=detail,
        )

        if save:
            await self._write_validation(
                db,
                question_id=question.id,
                validation_type=VALIDATION_TYPE_TRIVIALITY,
                passed=passed,
                score=score,
                detail=json.dumps({"trivial": trivial, "difficulty": target_difficulty,
                                   "bloom": target_bloom, "outcome": outcome.value}),
            )
            if outcome == TrivialityOutcome.FAIL:
                logger.warning(
                    "validate_triviality: FAIL — trivial stem for %s/%s question=%s stem=%r",
                    target_difficulty, target_bloom, question.id, stem[:80],
                )
            elif outcome == TrivialityOutcome.WARN:
                logger.debug(
                    "validate_triviality: WARN — trivial stem acceptable for %s/%s question=%s",
                    target_difficulty, target_bloom, question.id,
                )

        return result

    # ------------------------------------------------------------------ #
    # Correctness verification (pre-persist, LLM-assisted)                #
    # ------------------------------------------------------------------ #

    async def verify_tf_correctness(
        self,
        *,
        statement: str,
        is_true: bool,
        context_text: str,
        provider: "BaseLLMProvider",
    ) -> CorrectnessResult:
        """
        Ask the LLM verifier whether a True/False statement has the right label.

        Parameters
        ----------
        statement    : The declarative statement shown to the student.
        is_true      : The truth label claimed by the generator.
        context_text : The context string used during generation (source of truth).
        provider     : LLM provider to call.

        Returns
        -------
        CorrectnessResult — always returns (never raises); on provider error
        returns a safe fail-open result (AMBIGUOUS, should_reject=False).
        """
        from app.llm.prompts.correctness_verifier import (
            TF_CORRECTNESS_SYSTEM,
            TF_CORRECTNESS_USER,
        )

        # Truncate context to keep verifier calls cheap (≤ 1 200 chars).
        ctx = context_text[:1200].strip()
        claimed_str = "True" if is_true else "False"

        prompt = (
            TF_CORRECTNESS_SYSTEM
            + "\n---\n"
            + TF_CORRECTNESS_USER.format(
                context=ctx,
                statement=statement,
                claimed_value=claimed_str,
            )
        )

        try:
            settings = GenerationSettings(temperature=0.1, max_tokens=200)
            output: _LLMTFCorrectnessOutput = await provider.generate_json(
                prompt, _LLMTFCorrectnessOutput, settings
            )
        except Exception as exc:
            logger.warning(
                "verify_tf_correctness: LLM call failed — fail-open: %s", exc
            )
            return CorrectnessResult(
                verdict=CorrectnessVerdict.ERROR,
                confidence=0.5,
                reason=f"Verifier LLM call failed: {exc}",
                should_reject=False,
                question_type="tf",
            )

        # Normalise and map verdict string.
        raw_verdict = output.verdict.lower().strip().replace(" ", "_")
        try:
            verdict = CorrectnessVerdict(raw_verdict)
        except ValueError:
            verdict = CorrectnessVerdict.AMBIGUOUS

        # Decision logic:
        #   WRONG_LABEL + high confidence → flip (do not reject)
        #   WRONG_LABEL + low confidence  → reject (uncertain, better to skip)
        #   AMBIGUOUS                     → keep (save as WARN)
        #   CORRECT / ERROR               → keep
        should_flip   = False
        should_reject = False
        correct_is_true: bool | None = None

        if verdict == CorrectnessVerdict.WRONG_LABEL:
            if output.confidence >= 0.80:
                should_flip     = True
                correct_is_true = output.should_be_true
                logger.info(
                    "verify_tf_correctness: FLIP — statement=%r was=%s now=%s "
                    "confidence=%.2f",
                    statement[:60], claimed_str, correct_is_true, output.confidence,
                )
            else:
                should_reject = True
                logger.warning(
                    "verify_tf_correctness: REJECT — wrong label but low confidence "
                    "(%.2f) for statement=%r",
                    output.confidence, statement[:60],
                )

        return CorrectnessResult(
            verdict=verdict,
            confidence=output.confidence,
            reason=output.reason,
            should_reject=should_reject,
            should_flip=should_flip,
            correct_is_true=correct_is_true,
            question_type="tf",
        )

    async def verify_mcq_correctness(
        self,
        *,
        stem: str,
        options_text: str,
        claimed_correct: str,
        context_text: str,
        provider: "BaseLLMProvider",
    ) -> CorrectnessResult:
        """
        Ask the LLM verifier whether the marked correct MCQ option is actually correct.

        Parameters
        ----------
        stem            : The question text.
        options_text    : Pre-formatted options string (one line per option).
        claimed_correct : Key of the option marked as correct (\"A\"–\"D\").
        context_text    : Context string used during generation.
        provider        : LLM provider to call.

        Returns
        -------
        CorrectnessResult — always returns; fail-open on provider error.
        """
        from app.llm.prompts.correctness_verifier import (
            MCQ_CORRECTNESS_SYSTEM,
            MCQ_CORRECTNESS_USER,
        )

        ctx = context_text[:1200].strip()

        prompt = (
            MCQ_CORRECTNESS_SYSTEM
            + "\n---\n"
            + MCQ_CORRECTNESS_USER.format(
                context=ctx,
                stem=stem,
                options_text=options_text,
                claimed_correct=claimed_correct,
            )
        )

        try:
            settings = GenerationSettings(temperature=0.1, max_tokens=200)
            output: _LLMMCQCorrectnessOutput = await provider.generate_json(
                prompt, _LLMMCQCorrectnessOutput, settings
            )
        except Exception as exc:
            logger.warning(
                "verify_mcq_correctness: LLM call failed — fail-open: %s", exc
            )
            return CorrectnessResult(
                verdict=CorrectnessVerdict.ERROR,
                confidence=0.5,
                reason=f"Verifier LLM call failed: {exc}",
                should_reject=False,
                correct_key=claimed_correct,
                question_type="mcq",
            )

        raw_verdict = output.verdict.lower().strip().replace(" ", "_")
        try:
            verdict = CorrectnessVerdict(raw_verdict)
        except ValueError:
            verdict = CorrectnessVerdict.AMBIGUOUS

        # Decision logic:
        #   WRONG_CORRECT + high confidence   → reject (cannot safely fix MCQ label)
        #   MULTIPLE_CORRECT                  → reject (distractor design flaw)
        #   AMBIGUOUS                         → keep (WARN)
        #   CORRECT / ERROR                   → keep
        should_reject = False
        if verdict == CorrectnessVerdict.WRONG_CORRECT and output.confidence >= 0.80:
            should_reject = True
            logger.warning(
                "verify_mcq_correctness: REJECT — wrong correct option "
                "(verifier says %r, was %r, confidence=%.2f) stem=%r",
                output.correct_key, claimed_correct, output.confidence, stem[:60],
            )
        elif verdict == CorrectnessVerdict.MULTIPLE_CORRECT:
            should_reject = True
            logger.warning(
                "verify_mcq_correctness: REJECT — multiple correct options "
                "detected (confidence=%.2f) stem=%r",
                output.confidence, stem[:60],
            )

        # Normalise correct_key: only A–D is valid.
        ck = output.correct_key.upper().strip() if output.correct_key else claimed_correct
        if ck not in {"A", "B", "C", "D"}:
            ck = claimed_correct

        return CorrectnessResult(
            verdict=verdict,
            confidence=output.confidence,
            reason=output.reason,
            should_reject=should_reject,
            correct_key=ck,
            question_type="mcq",
        )

    async def persist_correctness_result(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        result: CorrectnessResult,
    ) -> None:
        """
        Write a QuestionValidation row for a pre-computed CorrectnessResult.

        Called from ``_run_validators`` after the question has been persisted.
        Does NOT raise — logs and returns on write error.
        """
        score  = _CORRECTNESS_SCORE.get(result.verdict, 0.5)
        passed = not result.should_reject

        detail_payload = {
            "verdict":         result.verdict.value,
            "confidence":      result.confidence,
            "reason":          result.reason,
            "should_reject":   result.should_reject,
            "should_flip":     result.should_flip,
            "correct_is_true": result.correct_is_true,
            "correct_key":     result.correct_key,
            "question_type":   result.question_type,
        }

        try:
            await self._write_validation(
                db,
                question_id=question_id,
                validation_type=VALIDATION_TYPE_CORRECTNESS,
                passed=passed,
                score=score,
                detail=json.dumps(detail_payload),
            )
        except Exception as exc:
            logger.error(
                "persist_correctness_result: write failed for question=%s: %s",
                question_id, exc,
            )

    # ------------------------------------------------------------------ #
    # Shared persistence helper                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _write_validation(
        db: AsyncSession,
        *,
        question_id: uuid.UUID,
        validation_type: str,
        passed: bool,
        score: float | None = None,
        detail: str | None = None,
    ) -> QuestionValidation:
        """
        Insert a single QuestionValidation row and flush (no commit).

        This is the shared low-level writer used by all validators.
        The caller (or get_db lifespan) is responsible for committing.

        Parameters
        ----------
        db              : Open async session.
        question_id     : FK to the question being validated.
        validation_type : Short string key, e.g. "grounding".
        passed          : True = check passed or warned; False = hard fail.
        score           : Optional numeric score (0.0–1.0).
        detail          : Optional JSON string with full diagnostic payload.

        Returns
        -------
        The newly-inserted (and flushed) QuestionValidation ORM object.
        """
        row = QuestionValidation(
            id=uuid.uuid4(),
            question_id=question_id,
            validation_type=validation_type,
            passed=passed,
            score=score,
            detail=detail,
        )
        db.add(row)
        await db.flush()

        logger.debug(
            "_write_validation: type=%s question=%s passed=%s score=%s",
            validation_type,
            question_id,
            passed,
            score,
        )
        return row
