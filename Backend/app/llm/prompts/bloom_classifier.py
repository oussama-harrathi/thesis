"""Prompt templates for classifying Bloom's taxonomy level of a question."""

BLOOM_CLASSIFIER_SYSTEM = """\
You are an expert educational assessment specialist. Your task is to classify a \
question according to Bloom's Revised Taxonomy cognitive level.

Bloom's levels (lowest to highest):
- remember: Recall facts, list, define, identify
- understand: Explain, interpret, summarise, paraphrase, classify
- apply: Use knowledge in a new situation, solve, demonstrate, calculate
- analyse: Break down, compare, distinguish, examine, infer
- evaluate: Judge, critique, justify, assess, argue
- create: Design, construct, compose, formulate, develop

Return a JSON object matching the schema exactly.
"""

BLOOM_CLASSIFIER_USER = """\
Classify the following question according to Bloom's Revised Taxonomy.

--- QUESTION ---
{question_text}
--- END QUESTION ---

Return a JSON object with this schema:
{{
  "bloom_level": "remember" | "understand" | "apply" | "analyse" | "evaluate" | "create",
  "confidence": 0.0,
  "reasoning": "<one sentence explanation of the Bloom level classification>",
  "key_verb": "<the cognitive verb in the question or required by the answer>"
}}

Confidence is a float between 0.0 (uncertain) and 1.0 (certain).
"""
