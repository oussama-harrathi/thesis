"""
Unit tests for app.utils.latex

Covers:
  - latex_escape()      — single-pass escaping of all 10 LaTeX special chars
  - _find_pdflatex()    — resolves PATH and common local installs
  - pdflatex_available() — always returns a bool (no assertion on True/False)
  - write_tex()         — writes content to a file, returns the path

No pdflatex binary is required; compile_pdf is not called.
"""
import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.utils.latex import (
    _find_pdflatex,
    compile_pdf,
    latex_escape,
    pdflatex_available,
    write_tex,
)


# ── latex_escape ──────────────────────────────────────────────────────────────

class TestLatexEscape:
    # ── Individual special characters ─────────────────────────────────────────

    def test_ampersand_escaped(self):
        assert latex_escape("a & b") == r"a \& b"

    def test_percent_escaped(self):
        assert latex_escape("50%") == r"50\%"

    def test_dollar_escaped(self):
        assert latex_escape("$100") == r"\$100"

    def test_hash_escaped(self):
        assert latex_escape("#1") == r"\#1"

    def test_underscore_escaped(self):
        assert latex_escape("a_b") == r"a\_b"

    def test_open_brace_escaped(self):
        assert latex_escape("{") == r"\{"

    def test_close_brace_escaped(self):
        assert latex_escape("}") == r"\}"

    def test_tilde_escaped(self):
        assert latex_escape("~") == r"\textasciitilde{}"

    def test_caret_escaped(self):
        assert latex_escape("^") == r"\textasciicircum{}"

    def test_backslash_escaped(self):
        assert latex_escape("\\") == r"\textbackslash{}"

    # ── No double-escaping ────────────────────────────────────────────────────

    def test_backslash_not_double_escaped(self):
        """
        \\  →  \\textbackslash{}
        The { and } in the replacement must NOT be re-escaped to \\{ and \\}.
        """
        result = latex_escape("\\")
        assert result == r"\textbackslash{}"
        # { and } in the replacement should remain literal (not \\{ \\} )
        assert r"\{" not in result
        assert r"\}" not in result

    def test_tilde_replacement_braces_not_re_escaped(self):
        result = latex_escape("~")
        assert result == r"\textasciitilde{}"
        assert r"\{" not in result

    def test_caret_replacement_braces_not_re_escaped(self):
        result = latex_escape("^")
        assert result == r"\textasciicircum{}"
        assert r"\{" not in result

    # ── Multiple characters in a string ───────────────────────────────────────

    def test_text_with_multiple_special_chars(self):
        result = latex_escape("Price: $50 & 100%")
        assert r"\$" in result
        assert r"\&" in result
        assert r"\%" in result

    def test_all_ten_special_chars_in_one_string(self):
        text = r"\&%$#_{}"  + "~^"
        result = latex_escape(text)
        # Must not contain unescaped originals after escaping
        assert "&" not in result.replace(r"\&", "")
        assert "%" not in result.replace(r"\%", "")

    def test_regular_text_unchanged(self):
        text = "Hello World"
        assert latex_escape(text) == text

    def test_empty_string_returns_empty(self):
        assert latex_escape("") == ""

    def test_none_equivalent_empty_string(self):
        # The function guards: if not text: return ""
        assert latex_escape("") == ""

    # ── Idempotency: applying twice should give different (escaped) result ─────

    def test_escaping_once_vs_twice_differ(self):
        """
        Applying latex_escape a second time should escape the backslashes
        introduced by the first pass — i.e. it is NOT idempotent.
        This confirms no double-escaping happens in a single pass.
        """
        once = latex_escape("50%")        # → r"50\%"
        twice = latex_escape(once)        # → r"50\textbackslash{}\%"  (\ is now escaped)
        assert once != twice

    # ── Realistic content examples ─────────────────────────────────────────────

    def test_question_body(self):
        body = "What is the value of x if f(x) = x^2 + 3?"
        result = latex_escape(body)
        assert r"\^" not in result     # ^ → \textasciicircum{}, not \^
        assert r"\textasciicircum{}" in result

    def test_url_like_string(self):
        result = latex_escape("https://example.com/path?q=1&r=2#section")
        assert r"\%" not in result  # % is in the original but there's no % in url... actually no % here
        assert r"\&" in result
        assert r"\#" in result


# ── pdflatex_available ────────────────────────────────────────────────────────

class TestPdflatexAvailable:
    def test_returns_bool(self):
        result = pdflatex_available()
        assert isinstance(result, bool)

    def test_find_pdflatex_uses_path_first(self, monkeypatch: pytest.MonkeyPatch):
        fake = Path(r"C:\tools\pdflatex.exe")
        monkeypatch.setattr("app.utils.latex.shutil.which", lambda _: str(fake))
        assert _find_pdflatex() == fake

    def test_find_pdflatex_uses_local_miktex_install(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        miktex_exe = (
            tmp_path
            / "Programs"
            / "MiKTeX"
            / "miktex"
            / "bin"
            / "x64"
            / "pdflatex.exe"
        )
        miktex_exe.parent.mkdir(parents=True)
        miktex_exe.write_text("", encoding="utf-8")

        monkeypatch.setattr("app.utils.latex.shutil.which", lambda _: None)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "pf"))
        monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "pfx86"))
        monkeypatch.setenv("PATH", "")

        found = _find_pdflatex()

        assert found == miktex_exe
        assert str(miktex_exe.parent) in os.environ["PATH"].split(os.pathsep)


# ── write_tex ─────────────────────────────────────────────────────────────────

class TestWriteTex:
    def test_creates_file_with_content(self, tmp_path: Path):
        content = r"\documentclass{article}\nHello World"
        output_path = tmp_path / "test_exam.tex"
        returned = write_tex(content, output_path)
        assert returned == output_path
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == content

    def test_creates_parent_dirs(self, tmp_path: Path):
        content = "some latex"
        deep_path = tmp_path / "sub" / "dir" / "exam.tex"
        write_tex(content, deep_path)
        assert deep_path.exists()

    def test_returns_path_object(self, tmp_path: Path):
        output_path = tmp_path / "out.tex"
        result = write_tex("content", output_path)
        assert isinstance(result, Path)

    def test_overwrites_existing_file(self, tmp_path: Path):
        path = tmp_path / "exam.tex"
        write_tex("first", path)
        write_tex("second", path)
        assert path.read_text(encoding="utf-8") == "second"

    def test_empty_content_written(self, tmp_path: Path):
        path = tmp_path / "empty.tex"
        write_tex("", path)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""


class TestCompilePdfInvocation:
    def test_compile_pdf_uses_local_filename_from_output_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        fake_pdflatex = tmp_path / "bin" / "pdflatex.exe"
        fake_pdflatex.parent.mkdir(parents=True)
        fake_pdflatex.write_text("", encoding="utf-8")

        workdir = tmp_path / "project"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        tex_path = Path("data/exports/abc123/exam.tex")
        tex_path.parent.mkdir(parents=True)
        tex_path.write_text(r"\documentclass{article}\begin{document}OK\end{document}", encoding="utf-8")

        captured: dict[str, object] = {}

        def fake_run(cmd, cwd, capture_output, text, timeout):
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            pdf_path = Path(cwd) / "exam.pdf"
            pdf_path.write_text("pdf", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr("app.utils.latex._find_pdflatex", lambda: fake_pdflatex)
        monkeypatch.setattr("app.utils.latex.subprocess.run", fake_run)

        pdf = compile_pdf(tex_path, runs=1)

        assert pdf == tex_path.resolve().with_suffix(".pdf")
        assert captured["cmd"][-1] == "exam.tex"
        assert captured["cwd"] == str(tex_path.resolve().parent)
