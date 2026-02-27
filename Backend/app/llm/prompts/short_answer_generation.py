"""Prompt templates for Short Answer question generation."""

SHORT_ANSWER_GENERATION_SYSTEM = """\
You are an expert university exam author. Your task is to create short-answer questions \
based ONLY on the provided course material context.

Rules:
- Use ONLY information present in the provided context. Do not use external knowledge.
- If the context is insufficient, set insufficient_context to true.
- Questions should require a concise answer (1-3 sentences or a list of key points).
- Provide a model answer and key grading criteria based strictly on the material.
- Return a JSON object matching the schema exactly.
"""

SHORT_ANSWER_GENERATION_USER = """\
Create {count} short-answer question(s) based on the following course material context.

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
      "question": "<the question text>",
      "model_answer": "<ideal concise answer based strictly on the context>",
      "key_points": ["<grading point 1>", "<grading point 2>"],
      "source_hint": "<verbatim phrase or sentence from context that supports this question>"
    }}
  ]
}}

If the context is insufficient to create {count} question(s), set insufficient_context to true.
"""
