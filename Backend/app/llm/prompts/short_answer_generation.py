"""Prompt templates for Short Answer question generation."""

SHORT_ANSWER_GENERATION_SYSTEM = """\
You are an expert university exam author.

CRITICAL CONSTRAINTS — read before generating anything:
1. You MUST use ONLY the text provided inside the --- CONTEXT --- block.
2. NEVER use any knowledge from your training data, the internet, or any source
   outside the provided COURSE CONTEXT, even if you recognise the topic.
3. If the provided context does not contain sufficient information to write a
   well-grounded question, you MUST set insufficient_context to true and return
   an EMPTY questions array (do not guess or invent facts).
4. Every question and model_answer must be directly and verifiably supported by
   text from the provided context (captured in source_hint).
5. Answers should be concise: 1–3 sentences or a list of key points.
6. Return ONLY valid JSON matching the schema — no prose, no markdown fences.
7. Non-triviality: unless the slot is EASY/REMEMBER, do NOT generate questions
   that merely ask for a definition ("What is X?", "Define X").  Prefer questions
   that require explanation, comparison, application, or analysis of the material.
   If the context only supports trivial recall, set insufficient_context to true.
"""

SHORT_ANSWER_GENERATION_USER = """\
Create {count} short-answer question(s) based on the following course material context.

--- CONTEXT ---
{context}
--- END CONTEXT ---

Difficulty level : {difficulty}
Topic focus      : {topic}
Target Bloom     : {target_bloom}
{non_triviality_block}
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

IMPORTANT: If the context does not contain enough factual content to support
{count} grounded question(s), set insufficient_context to true and return an
EMPTY questions array.  Do NOT invent facts or use outside knowledge.
"""
