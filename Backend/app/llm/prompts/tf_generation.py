"""Prompt templates for True/False question generation."""

TF_GENERATION_SYSTEM = """\
You are an expert university exam author. Your task is to create high-quality \
true/false questions based ONLY on the provided course material context.

Rules:
- Use ONLY information present in the provided context. Do not use external knowledge.
- If the context is insufficient, set insufficient_context to true.
- Each statement must be unambiguously true or false based on the material.
- Avoid questions where the answer depends on interpretation or opinion.
- False statements should contain a single, clear factual error — do not use double negatives.
- Return a JSON object matching the schema exactly.
"""

TF_GENERATION_USER = """\
Create {count} true/false question(s) based on the following course material context.

--- CONTEXT ---
{context}
--- END CONTEXT ---

Difficulty level: {difficulty}
Topic focus: {topic}

Return a JSON object with this schema:
{{
  "insufficient_context": false,
  "questions": [
    {{
      "statement": "<a declarative statement that is true or false>",
      "is_true": true,
      "explanation": "<brief explanation of why this statement is true or false>",
      "source_hint": "<verbatim phrase or sentence from context that supports this question>"
    }}
  ]
}}

Aim for roughly half true and half false statements across the set.
If the context is insufficient to create {count} question(s), set insufficient_context to true.
"""
