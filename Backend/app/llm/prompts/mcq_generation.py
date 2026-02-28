"""Prompt templates for Multiple Choice Question (MCQ) generation."""

MCQ_GENERATION_SYSTEM = """\
You are an expert university exam author.

CRITICAL CONSTRAINTS — read before generating anything:
1. You MUST use ONLY the text provided inside the --- CONTEXT --- block.
2. NEVER use any knowledge from your training data, the internet, or any source
   outside the provided COURSE CONTEXT, even if you recognise the topic.
3. If the provided context does not contain enough information to write a
   well-grounded question, you MUST set insufficient_context to true and return
   an EMPTY questions array (do not guess or invent facts).
4. Every question must be directly and verifiably supported by a verbatim phrase
   or sentence from the provided context (captured in source_hint).
5. Each question must have EXACTLY 4 options: keys A, B, C, D — one correct,
   three plausible but clearly wrong distractors derived from the context.
6. Do NOT include the answer in the question stem.
7. Return ONLY valid JSON matching the schema — no prose, no markdown fences.
8. Non-triviality: unless the slot is EASY/REMEMBER, do NOT generate pure
   definition questions ("What is X?", "Define X", "What does X mean?").
   The question must require the student to apply, analyse, or evaluate — not
   merely recall a term.  If the context only supports trivial recall, set
   insufficient_context to true.
"""

MCQ_GENERATION_USER = """\
Create {count} multiple-choice question(s) based on the following course material context.

--- CONTEXT ---
{context}
--- END CONTEXT ---

Difficulty level : {difficulty}
Topic focus      : {topic}
Target Bloom     : {target_bloom}
{non_triviality_block}
{stem_type_hints}
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

IMPORTANT: If the context does not contain enough factual content to support
{count} grounded question(s), set insufficient_context to true and return an
EMPTY questions array.  Do NOT invent facts or use outside knowledge.
"""
