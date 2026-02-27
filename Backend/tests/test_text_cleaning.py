"""
Unit tests for app.utils.text_cleaning

All functions under test are pure (no I/O), so tests run fast and
deterministically with no fixtures required.
"""
import pytest

from app.utils.text_cleaning import (
    clean_text,
    collapse_blank_lines,
    expand_ligatures,
    normalise_spaces,
    normalise_unicode,
    remove_control_chars,
)


# ── normalise_unicode ─────────────────────────────────────────────────────────

class TestNormaliseUnicode:
    def test_nfkc_compatibility_fraction(self):
        # NFKC converts compatibility characters like ½ → 1⁄2 (normalised form)
        # more robustly test with circled digits: ① → 1
        assert normalise_unicode("\u2460") == "1"  # ① → 1

    def test_nfkc_fullwidth_letter(self):
        # Fullwidth Latin A (U+FF21) → ASCII A
        assert normalise_unicode("\uff21") == "A"

    def test_already_nfc_unchanged(self):
        text = "Hello World"
        assert normalise_unicode(text) == text

    def test_empty_string(self):
        assert normalise_unicode("") == ""


# ── expand_ligatures ─────────────────────────────────────────────────────────

class TestExpandLigatures:
    def test_fi_ligature(self):
        assert expand_ligatures("\ufb01rst") == "first"

    def test_fl_ligature(self):
        assert expand_ligatures("\ufb02oor") == "floor"

    def test_ff_ligature(self):
        assert expand_ligatures("\ufb00") == "ff"

    def test_ffi_ligature(self):
        assert expand_ligatures("\ufb03cial") == "fficial"

    def test_ffl_ligature(self):
        assert expand_ligatures("\ufb04uent") == "ffluent"

    def test_st_ligature_1(self):
        assert expand_ligatures("be\ufb05") == "best"

    def test_st_ligature_2(self):
        assert expand_ligatures("be\ufb06") == "best"

    def test_multiple_ligatures_in_one_string(self):
        assert expand_ligatures("\ufb01ne \ufb02oor") == "fine floor"

    def test_no_ligatures_unchanged(self):
        assert expand_ligatures("hello world") == "hello world"

    def test_empty_string(self):
        assert expand_ligatures("") == ""


# ── remove_control_chars ──────────────────────────────────────────────────────

class TestRemoveControlChars:
    def test_null_byte_removed(self):
        assert remove_control_chars("hel\x00lo") == "hello"

    def test_tab_preserved(self):
        assert remove_control_chars("col1\tcol2") == "col1\tcol2"

    def test_newline_preserved(self):
        assert remove_control_chars("line1\nline2") == "line1\nline2"

    def test_carriage_return_kept(self):
        # \r (0x0d) falls between the two excluded ranges in the control-char
        # regex ([\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]) and is therefore kept.
        assert remove_control_chars("line1\r\nline2") == "line1\r\nline2"

    def test_bell_removed(self):
        assert remove_control_chars("a\x07b") == "ab"

    def test_del_removed(self):
        assert remove_control_chars("a\x7fb") == "ab"

    def test_regular_text_unchanged(self):
        text = "Hello\t\nWorld"
        assert remove_control_chars(text) == text

    def test_empty_string(self):
        assert remove_control_chars("") == ""


# ── normalise_spaces ──────────────────────────────────────────────────────────

class TestNormaliseSpaces:
    def test_non_breaking_space_replaced(self):
        assert normalise_spaces("hello\u00a0world") == "hello world"

    def test_en_quad_replaced(self):
        assert normalise_spaces("a\u2000b") == "a b"

    def test_ideographic_space_replaced(self):
        assert normalise_spaces("a\u3000b") == "a b"

    def test_bom_removed(self):
        # U+FEFF zero-width no-break space / BOM → space → then stripped
        result = normalise_spaces("\ufeffhello")
        assert result == "hello"

    def test_multiple_spaces_collapsed(self):
        assert normalise_spaces("a    b") == "a b"

    def test_leading_trailing_stripped_per_line(self):
        assert normalise_spaces("  hello  ") == "hello"

    def test_tabs_collapsed(self):
        assert normalise_spaces("a\t\t\tb") == "a b"

    def test_multiline_each_line_stripped(self):
        result = normalise_spaces("  foo  \n  bar  ")
        assert result == "foo\nbar"

    def test_empty_string(self):
        assert normalise_spaces("") == ""


# ── collapse_blank_lines ──────────────────────────────────────────────────────

class TestCollapseBlankLines:
    def test_three_blank_lines_become_two(self):
        result = collapse_blank_lines("a\n\n\nb")
        assert result == "a\n\nb"

    def test_four_blank_lines_become_two(self):
        result = collapse_blank_lines("a\n\n\n\nb")
        assert result == "a\n\nb"

    def test_ten_blank_lines_become_two(self):
        result = collapse_blank_lines("a" + "\n" * 10 + "b")
        assert result == "a\n\nb"

    def test_two_blank_lines_unchanged(self):
        assert collapse_blank_lines("a\n\nb") == "a\n\nb"

    def test_single_newline_unchanged(self):
        assert collapse_blank_lines("a\nb") == "a\nb"

    def test_empty_string(self):
        assert collapse_blank_lines("") == ""


# ── clean_text (full pipeline) ────────────────────────────────────────────────

class TestCleanText:
    def test_ligature_and_nbsp_cleaned(self):
        result = clean_text("\ufb01ne\u00a0weather")
        assert result == "fine weather"

    def test_control_chars_removed(self):
        result = clean_text("hel\x00lo")
        assert result == "hello"

    def test_preserves_newlines(self):
        result = clean_text("line1\nline2")
        assert result == "line1\nline2"

    def test_leading_trailing_stripped(self):
        result = clean_text("   hello world   ")
        assert result == "hello world"

    def test_inline_spaces_collapsed(self):
        result = clean_text("word1   word2")
        assert result == "word1 word2"

    def test_excess_blank_lines_collapsed(self):
        result = clean_text("para1\n\n\n\npara2")
        assert result == "para1\n\npara2"

    def test_full_pipeline_combined(self):
        raw = (
            "\ufb03cial\x00 document\u00a0version\n"
            "    \n"
            "\n"
            "\n"
            "Section 2"
        )
        result = clean_text(raw)
        # ligature expanded, null removed, nbsp → space, excess blank lines → 2,
        # leading/trailing stripped
        assert "fficial" in result
        assert "\x00" not in result
        assert "\u00a0" not in result
        # No triple blank lines
        assert "\n\n\n" not in result

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_already_clean_text_unchanged(self):
        text = "This is already clean text.\nSecond paragraph."
        assert clean_text(text) == text
