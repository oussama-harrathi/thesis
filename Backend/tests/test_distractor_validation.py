"""
Unit tests for MCQ distractor validation rules.

Covers the pure helper functions in app.services.validation_service
plus the integrated evaluate_distractor_issues function.

We use a lightweight _Opt dataclass in place of the McqOption ORM model — the
validation functions access only .label, .text and .is_correct so no database
connection is needed.
"""
import uuid
from dataclasses import dataclass

import pytest

from app.services.validation_service import (
    DistractorOutcome,
    check_catch_all_phrases,
    check_correct_count,
    check_length_outlier,
    check_option_count,
    check_uniqueness,
    evaluate_distractor_issues,
)


# ── Minimal option stand-in (no DB required) ──────────────────────────────────

@dataclass
class _Opt:
    """Duck-type substitute for McqOption used in pure-function tests."""
    label: str
    text: str
    is_correct: bool


def _make_options(
    texts: list[str],
    correct_index: int = 0,
) -> list[_Opt]:
    """Build a list of 4 _Opt objects; one at correct_index is correct."""
    labels = ["A", "B", "C", "D"]
    return [
        _Opt(label=labels[i], text=texts[i], is_correct=(i == correct_index))
        for i in range(len(texts))
    ]


def _good_options() -> list[_Opt]:
    """Return a valid set of 4 distinct options with exactly 1 correct."""
    return _make_options(
        ["Paris", "London", "Berlin", "Rome"],
        correct_index=0,
    )


# ── check_option_count ────────────────────────────────────────────────────────

class TestCheckOptionCount:
    def test_exactly_four_returns_none(self):
        opts = _good_options()
        assert check_option_count(opts) is None  # type: ignore[arg-type]

    def test_three_options_returns_fail(self):
        opts = _good_options()[:3]
        issue = check_option_count(opts)  # type: ignore[arg-type]
        assert issue is not None
        assert issue.severity == "fail"
        assert issue.code == "wrong_option_count"

    def test_five_options_returns_fail(self):
        extra = _good_options() + [_Opt(label="E", text="Madrid", is_correct=False)]
        issue = check_option_count(extra)  # type: ignore[arg-type]
        assert issue is not None
        assert issue.severity == "fail"

    def test_zero_options_returns_fail(self):
        issue = check_option_count([])  # type: ignore[arg-type]
        assert issue is not None
        assert issue.severity == "fail"


# ── check_correct_count ───────────────────────────────────────────────────────

class TestCheckCorrectCount:
    def test_exactly_one_correct_returns_none(self):
        opts = _good_options()
        assert check_correct_count(opts) is None  # type: ignore[arg-type]

    def test_zero_correct_returns_fail(self):
        opts = [_Opt(label=l, text=t, is_correct=False)
                for l, t in zip("ABCD", ["Paris", "London", "Berlin", "Rome"])]
        issue = check_correct_count(opts)  # type: ignore[arg-type]
        assert issue is not None
        assert issue.severity == "fail"
        assert issue.code == "no_correct_option"

    def test_two_correct_returns_fail(self):
        opts = [
            _Opt(label="A", text="Paris", is_correct=True),
            _Opt(label="B", text="London", is_correct=True),
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text="Rome", is_correct=False),
        ]
        issue = check_correct_count(opts)  # type: ignore[arg-type]
        assert issue is not None
        assert issue.severity == "fail"
        assert issue.code == "multiple_correct_options"

    def test_all_correct_returns_fail(self):
        opts = [_Opt(label=l, text=t, is_correct=True)
                for l, t in zip("ABCD", ["Paris", "London", "Berlin", "Rome"])]
        issue = check_correct_count(opts)  # type: ignore[arg-type]
        assert issue is not None
        assert issue.severity == "fail"


# ── check_uniqueness ──────────────────────────────────────────────────────────

class TestCheckUniqueness:
    def test_all_distinct_returns_empty(self):
        opts = _good_options()
        assert check_uniqueness(opts) == []  # type: ignore[arg-type]

    def test_exact_duplicate_returns_fail(self):
        opts = [
            _Opt(label="A", text="Paris", is_correct=True),
            _Opt(label="B", text="Paris", is_correct=False),
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text="Rome", is_correct=False),
        ]
        issues = check_uniqueness(opts)  # type: ignore[arg-type]
        assert len(issues) == 1
        assert issues[0].severity == "fail"
        assert issues[0].code == "duplicate_option_text"

    def test_case_insensitive_duplicate_detected(self):
        opts = [
            _Opt(label="A", text="paris", is_correct=True),
            _Opt(label="B", text="PARIS", is_correct=False),
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text="Rome", is_correct=False),
        ]
        issues = check_uniqueness(opts)  # type: ignore[arg-type]
        assert len(issues) == 1

    def test_trailing_period_ignored(self):
        opts = [
            _Opt(label="A", text="Paris.", is_correct=True),
            _Opt(label="B", text="Paris", is_correct=False),
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text="Rome", is_correct=False),
        ]
        issues = check_uniqueness(opts)  # type: ignore[arg-type]
        assert len(issues) == 1  # normalised text "paris" == "paris"

    def test_two_duplicate_pairs_reported(self):
        opts = [
            _Opt(label="A", text="Paris", is_correct=True),
            _Opt(label="B", text="Paris", is_correct=False),
            _Opt(label="C", text="Rome", is_correct=False),
            _Opt(label="D", text="Rome", is_correct=False),
        ]
        issues = check_uniqueness(opts)  # type: ignore[arg-type]
        assert len(issues) == 2


# ── check_catch_all_phrases ───────────────────────────────────────────────────

class TestCheckCatchAllPhrases:
    def test_no_catch_all_returns_empty(self):
        opts = _good_options()
        assert check_catch_all_phrases(opts) == []  # type: ignore[arg-type]

    @pytest.mark.parametrize("phrase", [
        "all of the above",
        "all of the above.",
        "none of the above",
        "none of the above.",
        "all of these",
        "none of these",
        "both a and b",
        "both of the above",
    ])
    def test_catch_all_phrase_produces_warn(self, phrase: str):
        opts = [
            _Opt(label="A", text="Paris", is_correct=True),
            _Opt(label="B", text="London", is_correct=False),
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text=phrase, is_correct=False),
        ]
        issues = check_catch_all_phrases(opts)  # type: ignore[arg-type]
        assert len(issues) == 1
        assert issues[0].severity == "warn"
        assert issues[0].code == "catch_all_phrase"
        assert issues[0].option_label == "D"

    def test_catch_all_case_insensitive(self):
        opts = [
            _Opt(label="A", text="Paris", is_correct=True),
            _Opt(label="B", text="London", is_correct=False),
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text="ALL OF THE ABOVE", is_correct=False),
        ]
        issues = check_catch_all_phrases(opts)  # type: ignore[arg-type]
        assert len(issues) == 1


# ── check_length_outlier ──────────────────────────────────────────────────────

class TestCheckLengthOutlier:
    def test_balanced_lengths_returns_none(self):
        opts = _make_options(["Paris", "London", "Berlin", "Tokyo"])
        assert check_length_outlier(opts) is None  # type: ignore[arg-type]

    def test_one_very_long_option_triggers_warn(self):
        short = "Yes"           # 3 chars
        very_long = "A" * 100  # 100 chars — far above mean
        opts = [
            _Opt(label="A", text=short, is_correct=True),
            _Opt(label="B", text=short, is_correct=False),
            _Opt(label="C", text=short, is_correct=False),
            _Opt(label="D", text=very_long, is_correct=False),
        ]
        issue = check_length_outlier(opts)  # type: ignore[arg-type]
        assert issue is not None
        assert issue.severity == "warn"
        assert issue.code == "length_outlier"
        assert issue.option_label == "D"

    def test_empty_options_returns_none(self):
        assert check_length_outlier([]) is None  # type: ignore[arg-type]

    def test_just_under_ratio_returns_none(self):
        """Ratio is 3.0×; 2.9× the mean should not trigger."""
        base = "ab"            # 2 chars
        opts = [
            _Opt(label="A", text=base, is_correct=True),
            _Opt(label="B", text=base, is_correct=False),
            _Opt(label="C", text=base, is_correct=False),
            _Opt(label="D", text="a" * 5, is_correct=False),  # 2.375× mean (2+2+2+5)/4=2.75; max/mean=5/2.75<3
        ]
        issue = check_length_outlier(opts)  # type: ignore[arg-type]
        # 5 / ((2+2+2+5)/4) = 5 / 2.75 ≈ 1.82 < 3.0 → no issue
        assert issue is None


# ── evaluate_distractor_issues ────────────────────────────────────────────────

class TestEvaluateDistractorIssues:
    _qid = uuid.uuid4()

    def test_perfect_options_returns_pass(self):
        opts = _good_options()
        result = evaluate_distractor_issues(self._qid, opts)  # type: ignore[arg-type]
        assert result.outcome == DistractorOutcome.PASS
        assert result.passed is True
        assert result.score == 1.0
        assert result.issues == []
        assert result.option_count == 4
        assert result.correct_count == 1

    def test_wrong_count_returns_fail(self):
        opts = _good_options()[:3]
        result = evaluate_distractor_issues(self._qid, opts)  # type: ignore[arg-type]
        assert result.outcome == DistractorOutcome.FAIL
        assert result.passed is False
        assert result.score == 0.0
        assert any(i.code == "wrong_option_count" for i in result.issues)

    def test_no_correct_option_returns_fail(self):
        opts = [_Opt(label=l, text=t, is_correct=False)
                for l, t in zip("ABCD", ["Paris", "London", "Berlin", "Rome"])]
        result = evaluate_distractor_issues(self._qid, opts)  # type: ignore[arg-type]
        assert result.outcome == DistractorOutcome.FAIL
        assert result.passed is False

    def test_duplicate_option_text_returns_fail(self):
        opts = [
            _Opt(label="A", text="Paris", is_correct=True),
            _Opt(label="B", text="paris", is_correct=False),   # duplicate
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text="Rome", is_correct=False),
        ]
        result = evaluate_distractor_issues(self._qid, opts)  # type: ignore[arg-type]
        assert result.outcome == DistractorOutcome.FAIL

    def test_catch_all_phrase_returns_warn(self):
        opts = [
            _Opt(label="A", text="Paris", is_correct=True),
            _Opt(label="B", text="London", is_correct=False),
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text="all of the above", is_correct=False),
        ]
        result = evaluate_distractor_issues(self._qid, opts)  # type: ignore[arg-type]
        assert result.outcome == DistractorOutcome.WARN
        assert result.passed is True  # WARN is still passed=True
        assert result.score == 0.5

    def test_length_outlier_returns_warn(self):
        opts = [
            _Opt(label="A", text="Yes", is_correct=True),
            _Opt(label="B", text="No", is_correct=False),
            _Opt(label="C", text="Maybe", is_correct=False),
            _Opt(label="D", text="A" * 200, is_correct=False),
        ]
        result = evaluate_distractor_issues(self._qid, opts)  # type: ignore[arg-type]
        assert result.outcome == DistractorOutcome.WARN
        assert result.passed is True

    def test_fail_blocks_quality_checks(self):
        """
        When there are structural FAILs, quality checks (WARN) should not be
        run — catches the case where duplicate options also have catch-all text.
        """
        opts = [
            _Opt(label="A", text="all of the above", is_correct=True),
            _Opt(label="B", text="all of the above", is_correct=False),  # dup
            _Opt(label="C", text="Berlin", is_correct=False),
            _Opt(label="D", text="Rome", is_correct=False),
        ]
        result = evaluate_distractor_issues(self._qid, opts)  # type: ignore[arg-type]
        # With duplicate, structural FAIL is present → WARN checks not run
        assert result.outcome == DistractorOutcome.FAIL
        warn_issues = [i for i in result.issues if i.severity == "warn"]
        assert warn_issues == [], "WARN checks should be skipped when FAIL exists"
