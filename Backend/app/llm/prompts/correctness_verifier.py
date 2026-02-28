"""
LLM prompts for post-generation correctness verification.

These prompts are used by ValidationService to ask the LLM whether:
  • A True/False statement has the right truth label, and
  • An MCQ question's marked correct option is actually correct.

Both prompts are deliberately short (< 400 tokens system + user combined) and
run at temperature 0.1 to get near-deterministic verdicts.  The verifier is
run AFTER generation but BEFORE final DB persistence, enabling the generation
loop to flip a wrong TF label or reject a bad MCQ before saving.

Verdict definitions
-------------------
TF verifier
  CORRECT       — context clearly confirms the stated truth value.
  WRONG_LABEL   — context clearly contradicts the stated truth value.
  AMBIGUOUS     — context does not unambiguously resolve the truth value.

MCQ verifier
  CORRECT           — marked option is the single best answer per context.
  WRONG_CORRECT     — a different option is clearly the right answer.
  MULTIPLE_CORRECT  — more than one option is defensibly correct (distractor issue).
  AMBIGUOUS         — context does not clearly resolve which option is best.
"""

# ── True/False correctness verifier ─────────────────────────────────────────

TF_CORRECTNESS_SYSTEM = """\
You are an academic quality auditor for university exam questions.

Your task: verify whether a True/False statement has been correctly labelled
given a provided CONTEXT (the sole authoritative source).

Rules:
1. Use ONLY the text inside the CONTEXT block — never your training data.
2. If the context unambiguously supports the label, return CORRECT.
3. If the context clearly contradicts the label, return WRONG_LABEL.
4. If the context is unclear or does not address the claim, return AMBIGUOUS.
5. Return ONLY valid JSON — no prose, no markdown.
"""

TF_CORRECTNESS_USER = """\
CONTEXT:
---
{context}
---

Statement  : {statement}
Claimed as : {claimed_value}

Return a JSON object:
{{
  "verdict": "CORRECT" | "WRONG_LABEL" | "AMBIGUOUS",
  "confidence": 0.0,
  "reason": "<one sentence citing the relevant context passage>",
  "should_be_true": true
}}

"should_be_true" must be your assessment of the statement's actual truth value
regardless of verdict (always provide it).
"""

# ── MCQ correctness verifier ─────────────────────────────────────────────────

MCQ_CORRECTNESS_SYSTEM = """\
You are an academic quality auditor for university exam questions.

Your task: verify that exactly one answer option is correct given a provided
CONTEXT (the sole authoritative source).

Rules:
1. Use ONLY the text inside the CONTEXT block — never your training data.
2. If the marked option is the single best answer, return CORRECT.
3. If a different option is clearly better, return WRONG_CORRECT.
4. If two or more options are equally defensible, return MULTIPLE_CORRECT.
5. If the context is insufficient to judge, return AMBIGUOUS.
6. Return ONLY valid JSON — no prose, no markdown.
"""

MCQ_CORRECTNESS_USER = """\
CONTEXT:
---
{context}
---

Question : {stem}
Options  :
{options_text}

Marked correct : Option {claimed_correct}

Return a JSON object:
{{
  "verdict": "CORRECT" | "WRONG_CORRECT" | "MULTIPLE_CORRECT" | "AMBIGUOUS",
  "confidence": 0.0,
  "reason": "<one sentence citing the relevant context passage>",
  "correct_key": "{claimed_correct}"
}}

"correct_key" must be your best guess at the single correct option key (A–D).
"""
