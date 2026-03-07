"""
Generation API routes (Phase 7).

POST /api/v1/courses/{course_id}/generate/mcq                                   → generate MCQ questions
POST /api/v1/courses/{course_id}/generate/true-false                            → generate True/False questions
GET  /api/v1/courses/{course_id}/questions                                      → list questions for a course
GET  /api/v1/courses/{course_id}/questions/replacement-candidates               → approved same-type questions from other blueprints
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.question import Difficulty, QuestionSet, QuestionSetMode, QuestionStatus, QuestionType
from app.schemas.question import (
    GenerateMCQRequest,
    GenerateTrueFalseRequest,
    GenerationResponse,
    QuestionListResponse,
    QuestionResponse,
    ReplacementCandidateResponse,
)
from app.services.question_generation_service import QuestionGenerationService
from app.services.question_service import QuestionService

router = APIRouter(tags=["generation"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _ensure_question_set(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    question_set_id: uuid.UUID | None,
    mode: QuestionSetMode = QuestionSetMode.professor,
    title: str | None = None,
) -> uuid.UUID:
    """
    Return *question_set_id* if provided, otherwise create a new QuestionSet
    for the course and return its new UUID.

    The caller (get_db) will commit the session after the handler returns.
    """
    if question_set_id is not None:
        return question_set_id

    new_set = QuestionSet(
        id=uuid.uuid4(),
        course_id=course_id,
        mode=mode,
        title=title,
    )
    db.add(new_set)
    await db.flush()  # obtain PK; session commits after handler
    return new_set.id


async def _reload_questions(
    db: AsyncSession,
    question_ids: list[uuid.UUID],
) -> list[QuestionResponse]:
    """
    Reload generated questions with eager-loaded relations so the response
    schema can serialise options and sources without lazy-load errors.
    """
    svc = QuestionService(db)
    responses: list[QuestionResponse] = []
    for qid in question_ids:
        question = await svc.get_by_id(qid)
        if question is not None:
            responses.append(QuestionResponse.model_validate(question))
    return responses


# ── Generation endpoints ──────────────────────────────────────────────────────


@router.post(
    "/courses/{course_id}/generate/mcq",
    response_model=GenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate MCQ questions",
    description=(
        "Generate multiple-choice questions from the course's uploaded materials. "
        "Questions are grounded in the retrieved context chunks — the LLM is "
        "instructed not to use external knowledge."
    ),
)
async def generate_mcq(
    course_id: uuid.UUID,
    body: GenerateMCQRequest,
    db: DbSession,
) -> GenerationResponse:
    qs_id = await _ensure_question_set(
        db,
        course_id=course_id,
        question_set_id=body.question_set_id,
        title=f"MCQ – {body.topic_name}",
    )

    gen_svc = QuestionGenerationService()
    questions = await gen_svc.generate_mcq(
        db,
        question_set_id=qs_id,
        course_id=course_id,
        topic_id=body.topic_id,
        topic_name=body.topic_name,
        difficulty=body.difficulty.value,
        count=body.count,
        retrieval_query=body.retrieval_query,
    )

    if not questions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No questions could be generated. The retrieved context may be "
                "insufficient or the LLM call failed. Check the server logs for details."
            ),
        )

    question_ids = [q.id for q in questions]
    responses = await _reload_questions(db, question_ids)

    return GenerationResponse(generated=len(responses), questions=responses)


@router.post(
    "/courses/{course_id}/generate/true-false",
    response_model=GenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate True/False questions",
    description=(
        "Generate true/false questions from the course's uploaded materials. "
        "Questions are grounded in the retrieved context chunks."
    ),
)
async def generate_true_false(
    course_id: uuid.UUID,
    body: GenerateTrueFalseRequest,
    db: DbSession,
) -> GenerationResponse:
    qs_id = await _ensure_question_set(
        db,
        course_id=course_id,
        question_set_id=body.question_set_id,
        title=f"TF – {body.topic_name}",
    )

    gen_svc = QuestionGenerationService()
    questions = await gen_svc.generate_true_false(
        db,
        question_set_id=qs_id,
        course_id=course_id,
        topic_id=body.topic_id,
        topic_name=body.topic_name,
        difficulty=body.difficulty.value,
        count=body.count,
        retrieval_query=body.retrieval_query,
    )

    if not questions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No questions could be generated. The retrieved context may be "
                "insufficient or the LLM call failed. Check the server logs for details."
            ),
        )

    question_ids = [q.id for q in questions]
    responses = await _reload_questions(db, question_ids)

    return GenerationResponse(generated=len(responses), questions=responses)


# ── Question listing endpoint ─────────────────────────────────────────────────


@router.get(
    "/courses/{course_id}/questions/replacement-candidates",
    response_model=list[ReplacementCandidateResponse],
    summary="List approved replacement candidates for a blueprint question",
    description=(
        "Return approved questions of the requested type in this course that are "
        "not already mapped to the specified blueprint."
    ),
)
async def list_replacement_candidates(
    course_id: uuid.UUID,
    db: DbSession,
    question_type: QuestionType = Query(alias="type"),
    exclude_blueprint_id: uuid.UUID = Query(),
) -> list[ReplacementCandidateResponse]:
    svc = QuestionService(db)
    return await svc.list_replacement_candidates(
        course_id,
        question_type=question_type,
        exclude_blueprint_id=exclude_blueprint_id,
    )


@router.get(
    "/courses/{course_id}/questions",
    response_model=list[QuestionListResponse],
    summary="List questions for a course",
    description="Return all questions belonging to any question set in the course.",
)
async def list_questions(
    course_id: uuid.UUID,
    db: DbSession,
    question_type: QuestionType | None = Query(default=None, alias="type"),
    difficulty: Difficulty | None = Query(default=None),
    question_status: QuestionStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[QuestionListResponse]:
    svc = QuestionService(db)
    questions = await svc.list_by_course(
        course_id,
        question_type=question_type,
        difficulty=difficulty,
        status=question_status,
        limit=limit,
        offset=offset,
    )
    return questions
