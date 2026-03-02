"""
Unit tests for app.utils.text_normalization — normalize_math_symbols

All functions under test are pure (no I/O, no DB, no LLM),
so tests run fast and deterministically with no fixtures required.

Both public names are tested to confirm the legacy alias still works.
"""
import pytest

from app.utils.text_normalization import (
    normalize_math_symbols,
    normalize_logic_symbols,  # legacy alias — must remain importable
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def norm(text: str) -> str:
    """Shorthand used throughout the test module."""
    return normalize_math_symbols(text)


# ---------------------------------------------------------------------------
# A.  Quantifier artifacts
# ---------------------------------------------------------------------------

class TestQuantifierArtifacts:

    def test_forall_no_space(self):
        assert norm("8z:") == "∀z:"

    def test_forall_with_spaces(self):
        assert norm("8 z :") == "∀z:"

    def test_forall_uppercase_variable(self):
        assert norm("8X:") == "∀X:"

    def test_forall_not_matched_inside_number(self):
        # "18z:" must NOT become "1∀z:" — the digit must be standalone
        result = norm("18z: something")
        assert "∀" not in result

    def test_exists_lowercase_var(self):
        assert norm("Ex:") == "∃x:"

    def test_exists_with_space(self):
        assert norm("E x :") == "∃x:"

    def test_exists_not_matched_for_uppercase_var(self):
        # "EX:" — X is uppercase; should NOT be treated as ∃ (too risky)
        result = norm("EX:")
        assert result == "EX:"

    def test_exists_3_artifact(self):
        assert norm("3x:") == "∃x:"

    def test_3_artifact_not_matched_inside_word(self):
        # "A3x:" should not become "A∃x:"
        result = norm("A3x:")
        assert "∃" not in result


# ---------------------------------------------------------------------------
# B.  Logical connective keywords
# ---------------------------------------------------------------------------

class TestLogicalKeywords:

    def test_implies(self):
        assert norm("A IMPLIES B") == "A ⇒ B"

    def test_iff(self):
        assert norm("P IFF Q") == "P ⇔ Q"

    def test_and(self):
        assert norm("A AND B") == "A ∧ B"

    def test_or(self):
        assert norm("A OR B") == "A ∨ B"

    def test_not(self):
        assert norm("NOT A") == "¬ A"

    def test_forall_keyword(self):
        assert norm("FORALL x") == "∀ x"

    def test_exists_keyword(self):
        assert norm("EXISTS x") == "∃ x"

    def test_neq(self):
        assert norm("a NEQ b") == "a ≠ b"

    def test_subseteq(self):
        assert norm("A SUBSETEQ B") == "A ⊆ B"

    def test_subset(self):
        assert norm("A SUBSET B") == "A ⊂ B"

    def test_subseteq_not_confused_with_subset(self):
        # SUBSETEQ must produce ⊆, not ⊂= (i.e. SUBSETEQ must be matched first)
        result = norm("A SUBSETEQ B")
        assert result == "A ⊆ B"
        assert "⊂" not in result

    def test_union(self):
        assert norm("A UNION B") == "A ∪ B"

    def test_intersect(self):
        assert norm("A INTERSECT B") == "A ∩ B"

    def test_emptyset(self):
        assert norm("EMPTYSET") == "∅"

    def test_combined_connectives(self):
        assert norm("a IFF b AND NOT c") == "a ⇔ b ∧ ¬ c"

    def test_case_sensitive_no_change_for_lowercase(self):
        # "implies" in normal prose must NOT be changed
        result = norm("this implies that")
        assert "⇒" not in result

    def test_case_sensitive_no_change_for_mixed_case(self):
        result = norm("Implies")
        assert "⇒" not in result


# ---------------------------------------------------------------------------
# C.  Placeholder / bracket artifacts
# ---------------------------------------------------------------------------

class TestPlaceholderArtifacts:

    def test_dot_var_D_var_slash_becomes_equality(self):
        assert norm(".A D B/") == "A = B"

    def test_dot_var_D_var_slash_with_spaces(self):
        assert norm(". A  D  B /") == "A = B"

    def test_dot_var_D_var_slash_multichar(self):
        assert norm(".alpha D beta/") == "alpha = beta"

    def test_dot_var_var_slash_becomes_subset(self):
        assert norm(".x y/") == "x ⊆ y"

    def test_dot_var_var_slash_with_spaces(self):
        assert norm(". x  y /") == "x ⊆ y"

    def test_equality_placeholder_preferred_over_subset(self):
        # ".A D B/" must produce "A = B", not "A ⊆ D B" (order of patterns)
        result = norm(".A D B/")
        assert result == "A = B"
        assert "⊆" not in result


# ---------------------------------------------------------------------------
# D.  Membership operator artifact
# ---------------------------------------------------------------------------

class TestMembershipArtifact:

    def test_spaced_membership(self):
        assert norm("x 2 A") == "x∈A"

    def test_runon_membership(self):
        assert norm("x2A") == "x∈A"

    def test_membership_with_brace(self):
        assert norm("x 2 {1,2,3}") == "x∈{1,2,3}"

    def test_membership_lowercase_set_variable(self):
        # In set-theory proofs both variable and set may be lowercase single chars.
        assert norm("z 2 x") == "z∈x"

    def test_no_false_positive_chapter_reference(self):
        result = norm("Step 2 In the algorithm")
        assert "∈" not in result

    def test_no_false_positive_word_boundary(self):
        # "max2A" — 'x' is part of "max", not a standalone variable
        result = norm("max2A")
        assert "∈" not in result

    def test_no_false_positive_lowercase_set_followed_by_word(self):
        # "a 2 be done" — "be" is a multi-char word, lookahead must prevent match
        result = norm("a 2 be done")
        assert "∈" not in result


# ---------------------------------------------------------------------------
# E.  Definition operator artifact
# ---------------------------------------------------------------------------

class TestDefinitionOperatorArtifact:

    def test_WWD_replaced(self):
        assert norm("f WWD x + 1") == "f := x + 1"

    def test_W_colon_eq_replaced(self):
        assert norm("g W:= 0") == "g := 0"

    def test_doubled_artifact(self):
        assert norm(":=:= 0") == ":= 0"


# ---------------------------------------------------------------------------
# F.  HTML entity remnants
# ---------------------------------------------------------------------------

class TestHtmlEntityRemnants:

    def test_isin_entity(self):
        assert norm("x &isin; A") == "x ∈ A"

    def test_rArr_entity(self):
        assert norm("p &rArr; q") == "p ⇒ q"

    def test_forall_entity(self):
        assert norm("&forall; x") == "∀ x"

    def test_not_entity(self):
        assert norm("&not; p") == "¬ p"


# ---------------------------------------------------------------------------
# G.  Inequality arrows
# ---------------------------------------------------------------------------

class TestInequalityArrows:

    def test_less_or_equal(self):
        assert norm("x <= y") == "x ≤ y"

    def test_greater_or_equal(self):
        assert norm("x >= y") == "x ≥ y"

    def test_no_change_for_double_equals(self):
        # "<==" can appear in Haskell/algorithm pseudocode; must NOT become "≤="
        result = norm("x <== y")
        assert result == "x <== y"


# ---------------------------------------------------------------------------
# H.  Redundant whitespace
# ---------------------------------------------------------------------------

class TestWhitespaceCollapse:

    def test_double_space_collapsed(self):
        assert norm("a  b") == "a b"

    def test_multiple_spaces_collapsed(self):
        assert norm("a     b") == "a b"

    def test_single_space_unchanged(self):
        assert norm("a b") == "a b"


# ---------------------------------------------------------------------------
# Integration scenarios — multi-artifact inputs
# ---------------------------------------------------------------------------

class TestIntegrationScenarios:

    def test_full_subset_proof_sentence(self):
        # "8z: (z 2 x IMPLIES z 2 y)" → "∀z: (z∈x ⇒ z∈y)"
        result = norm("8z: (z 2 x IMPLIES z 2 y)")
        assert result == "∀z: (z∈x ⇒ z∈y)"

    def test_set_equality_with_placeholder(self):
        # ".A D B/" AND "A SUBSETEQ B"
        result = norm(".A D B/ AND A SUBSETEQ B")
        assert result == "A = B ∧ A ⊆ B"

    def test_definition_with_forall(self):
        result = norm("f WWD 8x: x 2 N")
        assert result == "f := ∀x: x∈N"

    def test_implies_iff_chain(self):
        result = norm("P IMPLIES Q IFF R IMPLIES P")
        assert result == "P ⇒ Q ⇔ R ⇒ P"

    def test_not_implies(self):
        result = norm("NOT P IMPLIES Q")
        assert result == "¬ P ⇒ Q"

    def test_empty_string_unchanged(self):
        assert norm("") == ""

    def test_none_safe(self):
        # normalize_math_symbols(None) would fail; callers guard with `if text`
        # but we verify the function contract: empty string → empty string
        assert norm("") == ""

    def test_plain_english_untouched(self):
        # A sentence with no artifacts should pass through unchanged
        sentence = "The set contains exactly three elements."
        assert norm(sentence) == sentence

    def test_legacy_alias_matches(self):
        # normalize_logic_symbols must produce the same output as normalize_math_symbols
        text = "8z: z 2 A IMPLIES z 2 B"
        assert normalize_logic_symbols(text) == normalize_math_symbols(text)
