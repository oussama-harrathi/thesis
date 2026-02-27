"""
Pydantic v2 schemas for structured LLM generation outputs.

These schemas model the JSON the LLM must return, not API request/response shapes.
They are used in question generation services to parse and validate raw LLM text.

Hierarchy:
  GenerationOutputBase          – shared insufficient_context flag
  ├── MCQGenerationOutput       – batch of MCQ questions
  └── TrueFalseGenerationOutput – batch of True/False questions

Per-question schemas:
  MCQOption           – one answer choice (key A–D, text, is_correct)
  MCQQuestionOutput   – stem + exactly-4 options + 1 correct + explanation + source_hint
  TFQuestionOutput    – statement + is_true + explanation + source_hint
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Shared base ───────────────────────────────────────────────────────────────


class GenerationOutputBase(BaseModel):
    """Fields present in every top-level LLM generation response."""

    insufficient_context: bool = Field(
        default=False,
        description=(
            "True when the retrieved context was not sufficient to generate "
            "the requested number of questions. The LLM must set this flag "
            "instead of fabricating questions from external knowledge."
        ),
    )


# ── MCQ schemas ───────────────────────────────────────────────────────────────

_VALID_KEYS = {"A", "B", "C", "D"}


class MCQOption(BaseModel):
    """One answer choice for an MCQ question."""

    key: Annotated[str, Field(pattern=r"^[A-D]$")] = Field(
        ...,
        description="Option key — must be exactly one of: A, B, C, D.",
        examples=["A"],
    )
    text: str = Field(
        ...,
        min_length=1,
        description="The answer option text.",
    )
    is_correct: bool = Field(
        ...,
        description="True for the single correct option, False for all distractors.",
    )


class MCQQuestionOutput(BaseModel):
    """
    A single MCQ question as returned by the LLM.

    Validation rules enforced by Pydantic:
    - ``options`` must contain exactly 4 entries.
    - The keys across all options must be exactly {A, B, C, D} (no repeats, no gaps).
    - Exactly one option must have ``is_correct=True``.
    - ``stem`` must be non-empty.
    """

    stem: str = Field(
        ...,
        min_length=1,
        description="The question text presented to the student.",
    )
    options: list[MCQOption] = Field(
        ...,
        description="Exactly 4 answer options keyed A–D.",
    )
    explanation: str | None = Field(
        default=None,
        description=(
            "Rationale for the correct answer, grounded in the source material. "
            "May be None if the LLM omits it; generation service should warn."
        ),
    )
    source_hint: str | None = Field(
        default=None,
        description=(
            "A verbatim phrase or sentence from the context that directly supports "
            "this question. Used for grounding validation."
        ),
    )

    # ── Validators ────────────────────────────────────────────────

    @field_validator("options")
    @classmethod
    def validate_option_count(cls, v: list[MCQOption]) -> list[MCQOption]:
        if len(v) != 4:
            raise ValueError(
                f"MCQ must have exactly 4 options, got {len(v)}."
            )
        return v

    @model_validator(mode="after")
    def validate_options_structure(self) -> "MCQQuestionOutput":
        keys = {opt.key for opt in self.options}
        if keys != _VALID_KEYS:
            missing = _VALID_KEYS - keys
            extra = keys - _VALID_KEYS
            parts: list[str] = []
            if missing:
                parts.append(f"missing keys: {sorted(missing)}")
            if extra:
                parts.append(f"unexpected keys: {sorted(extra)}")
            raise ValueError(
                "MCQ options must use keys A, B, C, D exactly once. "
                + "; ".join(parts)
            )

        correct = [opt for opt in self.options if opt.is_correct]
        if len(correct) == 0:
            raise ValueError(
                "MCQ must have exactly one correct option (is_correct=True), "
                "but none were found."
            )
        if len(correct) > 1:
            raise ValueError(
                f"MCQ must have exactly one correct option, "
                f"but {len(correct)} were marked correct "
                f"(keys: {[o.key for o in correct]})."
            )
        return self


class MCQGenerationOutput(GenerationOutputBase):
    """
    Top-level LLM response for an MCQ generation request.

    When ``insufficient_context=True`` the ``questions`` list may be shorter
    than requested (including empty).  The generation service must handle this
    gracefully rather than treating it as a failure.
    """

    questions: list[MCQQuestionOutput] = Field(
        default_factory=list,
        description="Zero or more MCQ questions generated from the context.",
    )


# ── True / False schemas ──────────────────────────────────────────────────────


class TFQuestionOutput(BaseModel):
    """
    A single True/False question as returned by the LLM.

    Validation rules:
    - ``statement`` must be non-empty.
    - ``is_true`` must be a boolean (strict — rejects string "true"/"false").
    - ``explanation`` is required; must be non-empty.
    """

    statement: str = Field(
        ...,
        min_length=1,
        description=(
            "A declarative statement that is unambiguously true or false "
            "based solely on the provided context."
        ),
    )
    is_true: bool = Field(
        ...,
        description="True if the statement is factually correct per the source material.",
    )
    explanation: str = Field(
        ...,
        min_length=1,
        description=(
            "Brief explanation of why the statement is true or false, "
            "grounded in the source material."
        ),
    )
    source_hint: str | None = Field(
        default=None,
        description=(
            "A verbatim phrase or sentence from the context that supports "
            "this statement. Used for grounding validation."
        ),
    )


class TrueFalseGenerationOutput(GenerationOutputBase):
    """
    Top-level LLM response for a True/False generation request.

    When ``insufficient_context=True`` the list may be shorter than requested.
    """

    questions: list[TFQuestionOutput] = Field(
        default_factory=list,
        description="Zero or more True/False questions generated from the context.",
    )


# ── Short Answer & Essay (stubs for Phase 7 expansion) ───────────────────────
# Defined here so the rest of the codebase can import them without circular
# imports later.  Full validators will be added when the generators are built.


class ShortAnswerQuestionOutput(BaseModel):
    """Parsed LLM output for one Short Answer question."""

    question: str = Field(..., min_length=1)
    model_answer: str = Field(..., min_length=1)
    key_points: list[str] = Field(default_factory=list)
    source_hint: str | None = Field(default=None)


class ShortAnswerGenerationOutput(GenerationOutputBase):
    questions: list[ShortAnswerQuestionOutput] = Field(default_factory=list)


class EssayRubricCriterion(BaseModel):
    criterion: str = Field(..., min_length=1)
    max_points: int = Field(..., ge=1)
    description: str = Field(..., min_length=1)


class EssayQuestionOutput(BaseModel):
    """Parsed LLM output for one Essay/Development question."""

    question: str = Field(..., min_length=1)
    guidance: str | None = Field(default=None)
    model_outline: str = Field(..., min_length=1)
    rubric: list[EssayRubricCriterion] = Field(default_factory=list)
    source_hint: str | None = Field(default=None)


class EssayGenerationOutput(GenerationOutputBase):
    questions: list[EssayQuestionOutput] = Field(default_factory=list)
