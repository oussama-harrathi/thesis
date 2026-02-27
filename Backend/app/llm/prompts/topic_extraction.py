"""Prompt templates for topic extraction from course material chunks."""

TOPIC_EXTRACTION_SYSTEM = """\
You are an expert academic content analyst. Your task is to identify the main topics \
covered in the provided course material excerpt.
Rules:
- Use ONLY the provided text. Do not introduce topics from external knowledge.
- Topics must be directly evidenced by the text.
- Return a JSON object matching the schema exactly.
- If the text is too short or unclear to identify topics, return an empty list.
"""

TOPIC_EXTRACTION_USER = """\
Analyze the following course material and extract the main topics covered.

--- COURSE MATERIAL ---
{text}
--- END OF MATERIAL ---

Return a JSON object with this schema:
{{
  "topics": [
    {{
      "name": "<short topic name, 2-6 words>",
      "description": "<one sentence description of what this topic covers>",
      "keywords": ["<keyword1>", "<keyword2>", "..."]
    }}
  ]
}}

Extract between 1 and {max_topics} distinct topics. Focus on conceptual themes, \
not section headings or administrative content.
"""
