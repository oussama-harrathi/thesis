"""
Student Practice Routes

POST /api/v1/student/practice-sets              – create + generate a practice set
GET  /api/v1/student/practice-sets/{id}         – retrieve a practice set with questions

No authentication. Designed for the student workflow in the thesis MVP.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.practice import CreatePracticeSetRequest, PracticeSetResponse
from app.schemas.question import QuestionResponse
from app.services.practice_service import PracticeService

router = APIRouter(prefix="/student", tags=["student-practice"])

# ── Dependency aliases ────────────────────────────────────────────────────────

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _get_practice_service() -> PracticeService:
    """FastAPI dependency — returns a PracticeService with default providers."""
    return PracticeService()


PracticeSvc = Annotated[PracticeService, Depends(_get_practice_service)]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_response(question_set) -> PracticeSetResponse:
    """Assemble a PracticeSetResponse from an ORM QuestionSet."""
    questions = question_set.questions or []
    return PracticeSetResponse(
        id=question_set.id,
        course_id=question_set.course_id,
        mode=question_set.mode,
        title=question_set.title,
        created_at=question_set.created_at,
        generated=len(questions),
        questions=[QuestionResponse.model_validate(q) for q in questions],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/practice-sets",
    response_model=PracticeSetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a student practice set",
    description=(
        "Generate a set of practice questions from uploaded course material. "
        "Questions are produced on-demand using the RAG pipeline and stored "
        "with source snippets, correct answers, and explanations for answer reveal. "
        "No authentication required."
    ),
)
async def create_practice_set(
    payload: CreatePracticeSetRequest,
    db: DbSession,
    svc: PracticeSvc,
) -> PracticeSetResponse:
    """
    Generate a student practice set.

    - Distributes *count* questions evenly across requested *question_types*.
    - Constrains retrieval to *topic_ids* when supplied.
    - Only MCQ and True/False are supported in this MVP phase.
    """
    try:
        question_set = await svc.create_practice_set(db, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Practice set generation failed: {exc}",
        ) from exc

    return _build_response(question_set)


@router.get(
    "/practice-sets/{question_set_id}",
    response_model=PracticeSetResponse,
    summary="Get a student practice set",
    description=(
        "Retrieve a previously generated practice set by its UUID. "
        "Returns all questions with correct answers, explanations, MCQ options, "
        "and source snippets — suitable for an answer-reveal practice session."
    ),
)
async def get_practice_set(
    question_set_id: uuid.UUID,
    db: DbSession,
    svc: PracticeSvc,
) -> PracticeSetResponse:
    """Retrieve a practice set with full question detail for answer reveal."""
    question_set = await svc.get_practice_set(db, question_set_id)
    if question_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Practice set {question_set_id} not found.",
        )

    return _build_response(question_set)
