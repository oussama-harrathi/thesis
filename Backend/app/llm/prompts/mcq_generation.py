"""Prompt templates for Multiple Choice Question (MCQ) generation."""

MCQ_GENERATION_SYSTEM = """\
You are an expert university exam author. Your task is to create high-quality \
multiple-choice questions based ONLY on the provided course material context.

Rules:
- Use ONLY information present in the provided context. Do not use external knowledge.
- If the context is insufficient to create a valid question, set insufficient_context to true.
- Each question must have exactly 4 options (one correct, three plausible distractors).
- Distractors must be plausible but clearly incorrect based on the material.
- Questions must assess understanding, not just memorisation where possible.
- Return a JSON object matching the schema exactly.
- Do NOT include the answer in the question stem.
"""

MCQ_GENERATION_USER = """\
Create {count} multiple-choice question(s) based on the following course material context.

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
      "stem": "<the question text>",
      "options": [
        {{"key": "A", "text": "<option text>", "is_correct": true}},
        {{"key": "B", "text": "<option text>", "is_correct": false}},
        {{"key": "C", "text": "<option text>", "is_correct": false}},
        {{"key": "D", "text": "<option text>", "is_correct": false}}
      ],
      "explanation": "<brief explanation of why the correct answer is correct>",
      "source_hint": "<verbatim phrase or sentence from context that supports this question>"
    }}
  ]
}}

If the context is insufficient to create {count} question(s), set insufficient_context to true \
and return as many questions as the context supports (may be 0).
"""
