"""Prompt templates for classifying question difficulty."""

DIFFICULTY_CLASSIFIER_SYSTEM = """\
You are an expert educational assessment specialist. Your task is to classify the \
difficulty level of an exam question according to cognitive demand.

Difficulty levels:
- easy: Tests direct recall of facts or straightforward application of a concept.
- medium: Requires understanding of relationships between concepts, moderate reasoning.
- hard: Requires synthesis, evaluation, or complex multi-step reasoning across concepts.

Return a JSON object matching the schema exactly.
"""

DIFFICULTY_CLASSIFIER_USER = """\
Classify the difficulty level of the following question.

--- QUESTION ---
{question_text}
--- END QUESTION ---

{answer_hint}

Return a JSON object with this schema:
{{
  "difficulty": "easy" | "medium" | "hard",
  "confidence": 0.0,
  "reasoning": "<one sentence explanation of the difficulty classification>"
}}

Confidence is a float between 0.0 (uncertain) and 1.0 (certain).
"""
