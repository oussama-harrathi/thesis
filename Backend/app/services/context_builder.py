"""
ContextBuilder — compact, token-efficient context for LLM generation.

Problem
-------
Sending 6–8 full chunks to Groq free tier (~6000 tokens / call) exhausts the
12 000 TPM budget after the very first question.  Naively truncating makes the
context less useful.

Solution
--------
Produce a *compact context bundle* that prioritises the highest-value text:

1. **Raw evidence** (top-2 retrieved chunks, capped at ~1400 chars each).
   These supply the densest on-topic material.

2. **Key facts** extracted heuristically from the remaining chunks (no LLM):
   • Definition-style lines  ("X is …", "X defined as …", "X := …")
   • Theorem / lemma / proposition header lines
   • Bullet-point lines
   • Lines with ≥2 mathematical / symbolic operators

   Extracted lines are deduplicated and ordered by first appearance.

3. A **total character budget** (default 8 000 chars ≈ 2 000 tokens) caps the
   final context string so total prompt tokens stay well within the limit.

Usage
-----
    from app.services.context_builder import ContextBuilder

    ctx = ContextBuilder.build(chunks)
    prompt = MCQ_GENERATION_USER.format(context=ctx, ...)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.retrieval_service import RetrievedChunk

logger = logging.getLogger(__name__)

# ── Tunable limits ────────────────────────────────────────────────────────────
# chars / 4 ≈ tokens (OpenAI tokenisation heuristic, good enough for pacing)

# Max characters taken from each "raw evidence" chunk (≈ 350 tokens each)
RAW_EVIDENCE_CAP_CHARS: int = 1400

# Max characters for one extracted key-fact line
KEY_FACT_LINE_CAP_CHARS: int = 220

# Total context character budget (≈ 2 000 tokens at 4 chars/token)
TOTAL_BUDGET_CHARS: int = 8_000

# ── Heuristic patterns ────────────────────────────────────────────────────────

# Lines that express a definition or equivalence
_DEF_PATTERN = re.compile(
    r"\b(is|are|means|defined as|denoted by|denoted|called|:=|≡|iff)\b",
    re.IGNORECASE,
)

# Lines that open a theorem / lemma / proof block
_THEOREM_PATTERN = re.compile(
    r"^(theorem|lemma|proposition|corollary|definition|proof|claim|remark)\b",
    re.IGNORECASE,
)

# Bullet-point lines
_BULLET_PATTERN = re.compile(r"^[\s]*[-•*·]\s+\S")

# Lines with two or more mathematical/symbolic operators or LaTeX commands
_MATH_PATTERN = re.compile(
    r"[=+\-*/^∑∏∫√≤≥≠∈∉∀∃λμσαβγδεζηθ]{2,}"
    r"|\\frac|\\sum|\\int|\\prod|\\lim|\\inf|\\sup"
    r"|<=>|->|<-|::"
)


def _extract_key_facts(text: str) -> list[str]:
    """
    Heuristically extract definition, theorem, bullet, and equation lines.

    Returns stripped strings (already capped to KEY_FACT_LINE_CAP_CHARS).
    """
    facts: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or len(stripped) < 10:
            continue
        if (
            _THEOREM_PATTERN.match(stripped)
            or _BULLET_PATTERN.match(raw_line)
            or _MATH_PATTERN.search(stripped)
            or _DEF_PATTERN.search(stripped)
        ):
            facts.append(stripped[:KEY_FACT_LINE_CAP_CHARS])
    return facts


class ContextBuilder:
    """
    Builds a compact, grounded context string from retrieved chunk objects.

    All methods are **static** — instantiation is not needed.
    """

    @staticmethod
    def build(
        chunks: "list[RetrievedChunk]",
        budget_chars: int = TOTAL_BUDGET_CHARS,
        raw_evidence_cap: int = RAW_EVIDENCE_CAP_CHARS,
        n_raw: int = 2,
    ) -> str:
        """
        Build quality-preserving compact context.

        Parameters
        ----------
        chunks          : Retrieved chunks ordered by relevance (best first).
        budget_chars    : Total character budget for the returned string.
        raw_evidence_cap: Character cap per raw-evidence chunk.
        n_raw           : How many top chunks to include as raw evidence.

        Returns
        -------
        str — formatted context string ready to embed in a generation prompt.
             Returns ``""`` when *chunks* is empty.
        """
        if not chunks:
            return ""

        parts: list[str] = []
        used_chars = 0

        # ── Section 1: Raw evidence (top-n chunks, largely intact) ─────
        raw_chunks = chunks[:n_raw]
        for idx, chunk in enumerate(raw_chunks, start=1):
            text = chunk.content.strip()
            if len(text) > raw_evidence_cap:
                # Truncate at a sentence boundary when possible.
                truncated = text[:raw_evidence_cap]
                last_period = truncated.rfind(".")
                if last_period > raw_evidence_cap // 2:
                    truncated = truncated[: last_period + 1]
                text = truncated + " …"

            section = f"[Evidence {idx}]\n{text}"
            parts.append(section)
            used_chars += len(section) + 2  # +2 for section separator

        # ── Section 2: Key facts from remaining chunks ──────────────────
        remaining_budget = budget_chars - used_chars - 20  # 20 for header
        remaining_chunks = chunks[n_raw:]

        if remaining_chunks and remaining_budget > 100:
            # Collect all candidate facts.
            all_facts: list[str] = []
            for chunk in remaining_chunks:
                all_facts.extend(_extract_key_facts(chunk.content))

            # Deduplicate while preserving order.
            seen: set[str] = set()
            deduped: list[str] = []
            for fact in all_facts:
                key = fact.lower().strip()
                if key not in seen:
                    seen.add(key)
                    deduped.append(fact)

            # Fill key-facts section up to the remaining budget.
            fact_lines: list[str] = []
            chars_used = 0
            for fact in deduped:
                entry = f"• {fact}"
                if chars_used + len(entry) + 1 > remaining_budget:
                    break
                fact_lines.append(entry)
                chars_used += len(entry) + 1

            if fact_lines:
                parts.append("[Key Facts]\n" + "\n".join(fact_lines))

        result = "\n\n".join(parts)
        logger.debug(
            "ContextBuilder.build: %d chunks → %d chars (budget=%d, n_raw=%d)",
            len(chunks),
            len(result),
            budget_chars,
            n_raw,
        )
        return result

    @staticmethod
    def estimate_prompt_tokens(context: str, extra_prompt_chars: int = 2400) -> int:
        """
        Estimate total prompt tokens for a generation call.

        Parameters
        ----------
        context           : The context string returned by ``build()``.
        extra_prompt_chars: Approximate chars for system + user template
                            (fixed overhead outside the context block).
                            Default 2 400 ≈ 600 tokens for MCQ/TF prompts.

        Returns
        -------
        Estimated token count (int).
        """
        return (len(context) + extra_prompt_chars) // 4
