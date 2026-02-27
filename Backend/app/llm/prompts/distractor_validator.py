"""Prompt templates for validating MCQ distractors."""

DISTRACTOR_VALIDATOR_SYSTEM = """\
You are an expert educational assessment specialist. Your task is to evaluate the \
quality of multiple-choice question distractors (incorrect options).

Good distractors:
- Are plausible — they could attract students with partial or incorrect knowledge.
- Are clearly wrong when the underlying material is understood.
- Are not trick questions or nonsensical.
- Are similar in length and grammatical form to the correct answer.
- Do not overlap with each other or with the correct answer.

Return a JSON object matching the schema exactly.
"""

DISTRACTOR_VALIDATOR_USER = """\
Evaluate the distractors in the following multiple-choice question.

--- QUESTION ---
{question_stem}

Options:
{options_list}

Correct answer: {correct_key}
--- END QUESTION ---

Return a JSON object with this schema:
{{
  "overall_quality": "good" | "acceptable" | "poor",
  "issues": [
    {{
      "option_key": "A|B|C|D",
      "issue_type": "implausible" | "overlaps_correct" | "trick" | "inconsistent_format" | "too_similar_to_distractor",
      "description": "<brief description of the issue>"
    }}
  ],
  "suggestions": ["<improvement suggestion 1>", "<improvement suggestion 2>"],
  "reasoning": "<overall assessment of distractor quality>"
}}

If there are no issues, return an empty issues list and overall_quality of "good".
"""
