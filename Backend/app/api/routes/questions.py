"""
Question review / edit API routes (Phase 9 — Approve/Reject/Edit flow).

GET   /api/v1/questions/{question_id}         → fetch single question
PATCH /api/v1/questions/{question_id}         → edit question body, tags, or MCQ options
POST  /api/v1/questions/{question_id}/approve → approve a draft question
POST  /api/v1/questions/{question_id}/reject  → reject a draft question

Note: GET /api/v1/courses/{course_id}/questions (list + filter) lives in generation.py
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.question import (
    QuestionResponse,
    QuestionStatusResponse,
    QuestionUpdateRequest,
    RejectRequest,
)
from app.services.question_service import QuestionService

router = APIRouter(tags=["questions"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


# ── Shared helper ─────────────────────────────────────────────────────────────

async def _get_question_or_404(db: AsyncSession, question_id: uuid.UUID):  # type: ignore[return]
    """Load question with eager options + sources, raise 404 if missing."""
    svc = QuestionService(db)
    question = await svc.get_by_id(question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question {question_id} not found.",
        )
    return question


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/questions/{question_id}",
    response_model=QuestionResponse,
    summary="Get a single question by ID",
)
async def get_question(
    question_id: uuid.UUID,
    db: DbSession,
) -> QuestionResponse:
    """
    Return a single question with all nested MCQ options and source snippets.

    Raises **404** if the question does not exist.
    """
    question = await _get_question_or_404(db, question_id)
    return QuestionResponse.model_validate(question)


@router.patch(
    "/questions/{question_id}",
    response_model=QuestionResponse,
    summary="Edit a question (body, tags, MCQ options)",
)
async def update_question(
    question_id: uuid.UUID,
    payload: QuestionUpdateRequest,
    db: DbSession,
) -> QuestionResponse:
    """
    Apply a partial update to a question.

    **Editable fields** (all optional):
    - ``body`` — question stem text
    - ``correct_answer`` — authoritative answer string (non-MCQ; ignored for MCQ)
    - ``explanation`` — shown after the answer is revealed
    - ``difficulty`` — ``easy | medium | hard``
    - ``bloom_level`` — Bloom taxonomy level
    - ``mcq_options`` — list of option updates (MCQ questions only)

    **MCQ option editing** (`mcq_options` list):
    Each entry targets one existing option by ``id`` (UUID) or ``label`` (A–D).
    You can change ``text`` and/or ``is_correct``.
    Setting ``is_correct=true`` on an option automatically clears all other
    options' ``is_correct`` flag so the invariant "exactly one correct" is preserved.
    The endpoint returns **422** if the resulting state has 0 or >1 correct options,
    or if an option identifier doesn't exist on the question.

    Raises **404** if the question does not exist.
    """
    question = await _get_question_or_404(db, question_id)
    svc = QuestionService(db)
    updated = await svc.update(question, payload)
    await db.commit()
    # Re-fetch to return fresh state with updated relations.
    refreshed = await _get_question_or_404(db, updated.id)
    return QuestionResponse.model_validate(refreshed)


@router.post(
    "/questions/{question_id}/approve",
    response_model=QuestionStatusResponse,
    summary="Approve a question",
)
async def approve_question(
    question_id: uuid.UUID,
    db: DbSession,
) -> QuestionStatusResponse:
    """
    Set the question status to ``approved``.

    Approved questions are eligible to be added to an exam during assembly.

    Raises **404** if the question does not exist.
    Raises **409** if the question is already approved.
    """
    question = await _get_question_or_404(db, question_id)
    svc = QuestionService(db)
    updated = await svc.approve(question)
    await db.commit()
    return QuestionStatusResponse(id=updated.id, status=updated.status)


@router.post(
    "/questions/{question_id}/reject",
    response_model=QuestionStatusResponse,
    summary="Reject a question",
)
async def reject_question(
    question_id: uuid.UUID,
    db: DbSession,
    payload: RejectRequest | None = None,
) -> QuestionStatusResponse:
    """
    Set the question status to ``rejected``.

    Optionally supply a ``reason`` string in the request body; it will be
    stored in the question's ``explanation`` field for traceability.

    Raises **404** if the question does not exist.
    Raises **409** if the question is already rejected.
    """
    question = await _get_question_or_404(db, question_id)
    svc = QuestionService(db)
    updated = await svc.reject(question, payload)
    await db.commit()
    return QuestionStatusResponse(id=updated.id, status=updated.status)
