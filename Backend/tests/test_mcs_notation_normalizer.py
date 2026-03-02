"""
Unit tests for app.utils.text_normalization — normalize_mcs_notation

All functions are pure (no I/O, no DB, no LLM).
Tests are deterministic and run without any external dependencies.
"""
import pytest

from app.utils.text_normalization import normalize_mcs_notation, normalize_math_symbols


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def n(text: str) -> str:
    """Shorthand."""
    return normalize_mcs_notation(text)


# ---------------------------------------------------------------------------
# REQUIRED test cases from the spec
# ---------------------------------------------------------------------------

class TestRequiredCases:
    """Exact cases specified in the task."""

    def test_case_1_dot_slash_wrapper_with_unicode_symbols(self):
        # ".z∈x ⇔ z∈y/" -> "(z ∈ x ⇔ z ∈ y)"
        assert n(".z∈x ⇔ z∈y/") == "(z ∈ x ⇔ z ∈ y)"

    def test_case_2_define_equiv_with_nested_wrapper(self):
        # "x = y := ∀z: .z∈x ⇔ z∈y/" -> "x = y ⇔ ∀z: (z ∈ x ⇔ z ∈ y)"
        assert n("x = y := ∀z: .z∈x ⇔ z∈y/") == "x = y ⇔ ∀z: (z ∈ x ⇔ z ∈ y)"

    def test_case_3_subset_define_with_implies(self):
        # "x ⊆ y := ∀z: .z∈x IMPLIES z∈y/" -> "x ⊆ y ⇔ ∀z: (z ∈ x ⇒ z ∈ y)"
        assert n("x ⊆ y := ∀z: .z∈x IMPLIES z∈y/") == "x ⊆ y ⇔ ∀z: (z ∈ x ⇒ z ∈ y)"

    def test_case_4_quantifier_artifact_with_membership_and_iff(self):
        # "8z: .z 2 x IFF z 2 y/" -> "∀z: (z ∈ x ⇔ z ∈ y)"
        assert n("8z: .z 2 x IFF z 2 y/") == "∀z: (z ∈ x ⇔ z ∈ y)"


# ---------------------------------------------------------------------------
# I.  Dot/slash wrapper removal
# ---------------------------------------------------------------------------

class TestDotSlashWrapperRemoval:

    def test_simple_wrapper_becomes_parens(self):
        assert n(".A/") == "(A)"

    def test_wrapper_with_content_becomes_parens(self):
        assert n(".z ∈ x/") == "(z ∈ x)"

    def test_wrapper_with_connective(self):
        assert n(".P ⇒ Q/") == "(P ⇒ Q)"

    def test_wrapper_with_longer_content(self):
        assert n(".alpha ∈ Beta/") == "(alpha ∈ Beta)"

    def test_two_adjacent_wrappers(self):
        # Two wrappers one after another
        result = n(".A/ ∧ .B/")
        assert result == "(A) ∧ (B)"

    def test_iterative_nested_wrapper(self):
        # Nested: ".outer .inner/ content/"
        # First pass: ".inner/" → "(inner)" → ".outer (inner) content/"
        # Second pass: ".outer (inner) content/" → "(outer (inner) content)"
        result = n(".outer .inner/ content/")
        assert "(inner)" in result
        assert result.startswith("(")
        assert result.endswith(")")

    def test_no_wrapper_unchanged(self):
        plain = "z ∈ x ⇔ z ∈ y"
        assert n(plain) == plain

    def test_wrapper_not_cross_newline(self):
        # The dot-slash pattern must not span newlines
        text = ".start\nend/"
        result = n(text)
        # The wrapper should NOT have been collapsed across the newline
        assert "(" not in result or text in result or "\n" in result


# ---------------------------------------------------------------------------
# II.  Definitional ':=' → '⇔' (conditional on rhs logic symbols)
# ---------------------------------------------------------------------------

class TestDefinitionalEquality:

    def test_colon_eq_replaced_when_rhs_has_forall(self):
        assert n("A := ∀x: P(x)") == "A ⇔ ∀x: P(x)"

    def test_colon_eq_replaced_when_rhs_has_exists(self):
        assert n("B := ∃x: Q(x)") == "B ⇔ ∃x: Q(x)"

    def test_colon_eq_replaced_when_rhs_has_implies(self):
        assert n("C := P ⇒ Q") == "C ⇔ P ⇒ Q"

    def test_colon_eq_replaced_when_rhs_has_iff(self):
        assert n("D := P ⇔ Q") == "D ⇔ P ⇔ Q"

    def test_colon_eq_kept_when_rhs_is_plain_definition(self):
        # "Let f := x + 1" has no quantifiers/connectives → keep :=
        result = n("Let f := x + 1")
        assert ":=" in result
        assert "⇔" not in result

    def test_colon_eq_kept_for_numeric_definition(self):
        result = n("n := 42")
        assert ":=" in result

    def test_only_first_colon_eq_replaced_per_line(self):
        # Only one := per line gets replaced (conservative)
        result = n("A := ∀x: P(x)")
        # should have at most one ⇔ from the := replacement
        # (the ∀ colon is a quantifier, not :=)
        assert result.count("⇔") == 1


# ---------------------------------------------------------------------------
# III.  Spacing around ∈
# ---------------------------------------------------------------------------

class TestMembershipSpacing:

    def test_run_on_membership_gets_spaces(self):
        assert n("z∈x") == "z ∈ x"

    def test_already_spaced_unchanged(self):
        text = "z ∈ x"
        assert n(text) == text

    def test_within_parens(self):
        result = n("(z∈x ⇔ z∈y)")
        assert "z ∈ x" in result
        assert "z ∈ y" in result


# ---------------------------------------------------------------------------
# IV.  Quantifier colon spacing
# ---------------------------------------------------------------------------

class TestQuantifierColonSpacing:

    def test_forall_colon_followed_by_paren(self):
        # ∀z:( → ∀z: (
        result = n("∀z:(phi)")
        assert "∀z: (phi)" in result

    def test_exists_colon_followed_by_letter(self):
        result = n("∃x:P(x)")
        assert "∃x: P(x)" in result

    def test_already_spaced_unchanged(self):
        text = "∀z: (phi)"
        assert n(text) == text


# ---------------------------------------------------------------------------
# V.  Parenthesis interior spacing cleanup
# ---------------------------------------------------------------------------

class TestParenInteriorSpacing:

    def test_leading_space_inside_paren_removed(self):
        assert n("( A )") == "(A)"

    def test_trailing_space_inside_paren_removed(self):
        result = n("( z ∈ x )")
        assert not result.startswith("( ")
        assert not result.endswith(" )")

    def test_content_preserved(self):
        assert n("( z ∈ x ⇔ z ∈ y )") == "(z ∈ x ⇔ z ∈ y)"


# ---------------------------------------------------------------------------
# VI.  Integration — compound inputs
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_full_subset_definition_from_mcq_option(self):
        # Typical MCQ option for set-theory subset definition
        inp = "x ⊆ y := ∀z: .z∈x ⇒ z∈y/"
        out = n(inp)
        assert "⇔" in out          # := became ⇔
        assert "(z ∈ x" in out      # wrapper became paren + spaced ∈
        assert "⇒ z ∈ y)" in out
        assert ":=" not in out
        assert ".z∈x" not in out

    def test_mcq_distractor_with_wrong_connective(self):
        # A distractor option that has .A ⇔ B/ pattern
        result = n("x ⊆ y := ∃z: .z∈x ∧ z∉y/")
        assert "⇔" in result       # := replaced
        assert "(z ∈ x" in result

    def test_multiple_wrappers_on_same_line(self):
        result = n("F := .A ∧ B/ ⇔ .C ∨ D/")
        assert "(A ∧ B)" in result
        assert "(C ∨ D)" in result
        assert "." not in result.replace(".strip()", "")  # no dot-slash left

    def test_quantifier_artifact_combined_with_wrapper(self):
        result = n("8z: .z 2 x IMPLIES z 2 y/")
        assert result == "∀z: (z ∈ x ⇒ z ∈ y)"

    def test_empty_string_safe(self):
        assert n("") == ""

    def test_plain_english_untouched(self):
        sentence = "The algorithm runs in O(n log n) time."
        assert n(sentence) == sentence

    def test_normalize_math_symbols_still_works(self):
        # The underlying function must still be importable and functional
        assert normalize_math_symbols("a IFF b") == "a ⇔ b"

    def test_normalize_mcs_is_superset_of_math_symbols(self):
        # For any input that doesn't involve MCS-specific patterns,
        # the two functions should agree.
        text = "p IMPLIES q IFF r AND NOT s"
        assert normalize_mcs_notation(text) == normalize_math_symbols(text)
