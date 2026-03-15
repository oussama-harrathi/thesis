"""Prompt templates for Essay / Development question generation."""

ESSAY_GENERATION_SYSTEM = """\
You are an expert university exam author.

CRITICAL CONSTRAINTS — read before generating anything:
1. You MUST use ONLY the text provided inside the --- CONTEXT --- block.
2. NEVER use any knowledge from your training data, the internet, or any source
   outside the provided COURSE CONTEXT, even if you recognise the topic.
3. If the provided context does not contain sufficient information to write a
   well-grounded essay question, you MUST set insufficient_context to true and
   return an EMPTY questions array (do not guess or invent facts).
4. Every question must be directly and verifiably supported by verbatim text from
   the provided context (captured in source_hint).
5. NEVER apply concepts to real-world domains, analogies, or scenarios that are
   NOT explicitly mentioned in the context.  Do not invent examples such as
   "university courses", "software systems", "business processes", or any other
   domain that does not appear literally in the provided text.  If you want to
   use an example, it must come word-for-word from the context.
6. The question scenario, framing, and domain must come from the context itself.
   The student must be able to answer the question using ONLY the provided text.
7. Questions should require extended, analytical responses (multiple paragraphs).
8. Provide a rubric with scoring criteria tied directly to statements in the context.
9. Return ONLY valid JSON matching the schema — no prose, no markdown fences.
10. Non-triviality: unless the slot is EASY/REMEMBER, do NOT generate questions
    that merely ask for a bare definition.  Prefer questions that require the
    student to explain relationships, compare approaches, or analyse implications
    as described in the context.  If the context only supports trivial recall,
    set insufficient_context to true.

EXAM READABILITY RULES — the generated question will appear on a printed exam:
11. The question must be SELF-CONTAINED.  A student reading the exam will NOT
    have any "context block" or "provided text".
    NEVER use phrases like:
      "from the provided context", "according to the provided text",
      "based on the context", "the given passage", "the context states",
      "using the provided", "in the provided material".
    Write the question as a normal standalone exam question.
    WRONG:  "Using the provided relationship curves between TP and Temp…"
    RIGHT:  "Explain how changes in Total Phosphorus affect water transparency…"
12. Do NOT create questions that require looking at graphs, figures, charts,
    diagrams, curves, tables, or images.  The student will only have text on
    the exam paper — no visual elements.  If a question must reference visual
    data to be answerable, set insufficient_context to true instead.
"""

ESSAY_GENERATION_USER = """\
Create {count} essay/development question(s) based on the following course material context.

--- CONTEXT ---
{context}
--- END CONTEXT ---

Course subject   : {course_subject}
Difficulty level : {difficulty}
Target Bloom     : {target_bloom}
Topic focus      : {topic}
Suggested response length: {response_length}

{difficulty_focus_block}
{non_triviality_block}

Return a JSON object with this schema:
{{
  "insufficient_context": false,
  "questions": [
    {{
      "question": "<the essay/development question — must be answerable from the context above only>",
      "guidance": "<optional guidance for students on what to address, based on the context>",
      "model_outline": "<outline of an ideal answer based strictly on the context>",
      "rubric": [
        {{
          "criterion": "<assessment criterion tied to a specific claim in the context>",
          "max_points": 10,
          "description": "<what earns full marks for this criterion>"
        }}
      ],
      "source_hint": "<verbatim phrase or sentence from context that anchors this question>"
    }}
  ]
}}

IMPORTANT: If the context does not contain enough factual content to support
{count} grounded question(s), set insufficient_context to true and return an
EMPTY questions array.  Do NOT invent facts, scenarios, or real-world examples
not present in the text above.
"""
