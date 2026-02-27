"""Prompt templates for Essay / Development question generation."""

ESSAY_GENERATION_SYSTEM = """\
You are an expert university exam author. Your task is to create essay/development \
questions based ONLY on the provided course material context.

Rules:
- Use ONLY information present in the provided context. Do not use external knowledge.
- If the context is insufficient, set insufficient_context to true.
- Questions should require extended, analytical responses (multiple paragraphs).
- Provide a detailed rubric with scoring criteria directly tied to the material.
- Return a JSON object matching the schema exactly.
"""

ESSAY_GENERATION_USER = """\
Create {count} essay/development question(s) based on the following course material context.

--- CONTEXT ---
{context}
--- END CONTEXT ---

Difficulty level: {difficulty}
Topic focus: {topic}
Suggested response length: {response_length}

Return a JSON object with this schema:
{{
  "insufficient_context": false,
  "questions": [
    {{
      "question": "<the essay/development question>",
      "guidance": "<optional guidance for students on what to address>",
      "model_outline": "<outline of an ideal answer based on the context>",
      "rubric": [
        {{
          "criterion": "<assessment criterion>",
          "max_points": 10,
          "description": "<what earns full marks for this criterion>"
        }}
      ],
      "source_hint": "<verbatim phrase or sentence from context that anchors this question>"
    }}
  ]
}}

If the context is insufficient to create {count} question(s), set insufficient_context to true.
"""
