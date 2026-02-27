"""
Exam assembly API routes (Phase 9 — Exam Assembly).

POST   /api/v1/blueprints/{blueprint_id}/assemble              → create exam
GET    /api/v1/blueprints/{blueprint_id}/exams                 → list exams for blueprint
GET    /api/v1/exams/{exam_id}                                 → get exam detail
POST   /api/v1/exams/{exam_id}/questions                       → add question to exam
PATCH  /api/v1/exams/{exam_id}/questions/reorder               → reorder / update points
DELETE /api/v1/exams/{exam_id}/questions/{exam_question_id}    → remove question
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.exam import (
    AddExamQuestionRequest,
    AssembleExamRequest,
    ExamListItem,
    ExamResponse,
    ExamQuestionResponse,
    ReorderExamQuestionsRequest,
)
from app.schemas.question import QuestionResponse
from app.services.exam_assembly_service import ExamAssemblyService

# Two routers:
#   blueprints_router: for /blueprints/{blueprint_id}/... sub-routes
#   exams_router:      for standalone /exams/{exam_id}/... routes
blueprints_router = APIRouter(tags=["exams"])
exams_router = APIRouter(tags=["exams"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


# ── Shared helpers ────────────────────────────────────────────────────────────

async def _get_blueprint_or_404(db: AsyncSession, blueprint_id: uuid.UUID):  # type: ignore[return]
    svc = ExamAssemblyService(db)
    bp = await svc.get_blueprint_or_none(blueprint_id)
    if bp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blueprint {blueprint_id} not found.",
        )
    return bp


async def _get_exam_or_404(db: AsyncSession, exam_id: uuid.UUID):  # type: ignore[return]
    svc = ExamAssemblyService(db)
    exam = await svc.get_exam_or_none(exam_id)
    if exam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam {exam_id} not found.",
        )
    return exam


# ── Blueprint-scoped routes ───────────────────────────────────────────────────


@blueprints_router.post(
    "/blueprints/{blueprint_id}/assemble",
    response_model=ExamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assemble an exam from approved questions",
)
async def assemble_exam(
    blueprint_id: uuid.UUID,
    payload: AssembleExamRequest,
    db: DbSession,
) -> ExamResponse:
    """
    Collect all **approved** questions from the blueprint's course (or from a
    specific question set if ``question_set_id`` is provided) and create an
    ordered ``Exam`` with ``ExamQuestion`` rows.

    Returns the newly created exam with all nested question slots.
    """
    blueprint = await _get_blueprint_or_404(db, blueprint_id)
    svc = ExamAssemblyService(db)

    try:
        exam = await svc.assemble(blueprint, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    # Re-fetch with full eager loading via get_exam_or_none
    exam = await svc.get_exam_or_none(exam.id)
    assert exam is not None
    return ExamResponse.model_validate(exam)


@blueprints_router.get(
    "/blueprints/{blueprint_id}/exams",
    response_model=list[ExamListItem],
    summary="List exams for a blueprint",
)
async def list_exams(
    blueprint_id: uuid.UUID,
    db: DbSession,
) -> list[ExamListItem]:
    """Return all assembled exams for a blueprint, newest first."""
    await _get_blueprint_or_404(db, blueprint_id)
    svc = ExamAssemblyService(db)
    exams = await svc.list_by_blueprint(blueprint_id)

    items: list[ExamListItem] = []
    for exam in exams:
        item = ExamListItem.model_validate(exam)
        item.question_count = len(exam.exam_questions)
        items.append(item)
    return items


# ── Exam-scoped routes ────────────────────────────────────────────────────────


@exams_router.get(
    "/exams/{exam_id}",
    response_model=ExamResponse,
    summary="Get exam detail",
)
async def get_exam(
    exam_id: uuid.UUID,
    db: DbSession,
) -> ExamResponse:
    """Return an exam with all ordered question slots (including full question detail)."""
    exam = await _get_exam_or_404(db, exam_id)
    return ExamResponse.model_validate(exam)


@exams_router.post(
    "/exams/{exam_id}/questions",
    response_model=ExamQuestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a question to an exam",
)
async def add_question(
    exam_id: uuid.UUID,
    payload: AddExamQuestionRequest,
    db: DbSession,
) -> ExamQuestionResponse:
    """
    Append an **approved** question to the exam at the next available position.

    Raises **422** if the question does not exist or is not approved.
    """
    exam = await _get_exam_or_404(db, exam_id)
    svc = ExamAssemblyService(db)

    try:
        eq = await svc.add_question(exam, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    await db.refresh(eq)

    # Build response — load question with nested data
    from app.models.question import Question, McqOption, QuestionSource
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select

    result = await db.execute(
        select(Question)
        .where(Question.id == eq.question_id)
        .options(
            selectinload(Question.mcq_options),
            selectinload(Question.sources),
        )
    )
    question = result.scalar_one()

    return ExamQuestionResponse(
        id=eq.id,
        exam_id=eq.exam_id,
        question_id=eq.question_id,
        position=eq.position,
        points=float(eq.points) if eq.points is not None else None,
        question=QuestionResponse.model_validate(question),
    )


@exams_router.patch(
    "/exams/{exam_id}/questions/reorder",
    response_model=ExamResponse,
    summary="Reorder exam questions and/or update points",
)
async def reorder_questions(
    exam_id: uuid.UUID,
    payload: ReorderExamQuestionsRequest,
    db: DbSession,
) -> ExamResponse:
    """
    Apply new positions (and optionally update points) for any subset of exam
    questions.  Supply the complete desired ordering to avoid gaps.

    Raises **422** if duplicate positions are provided or an ``exam_question_id``
    does not belong to this exam.
    """
    exam = await _get_exam_or_404(db, exam_id)
    svc = ExamAssemblyService(db)

    try:
        exam = await svc.reorder(exam, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    # Re-fetch with full eager loading
    exam = await svc.get_exam_or_none(exam_id)
    assert exam is not None
    return ExamResponse.model_validate(exam)


@exams_router.delete(
    "/exams/{exam_id}/questions/{exam_question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a question from an exam",
)
async def remove_question(
    exam_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    db: DbSession,
) -> None:
    """
    Remove a question slot from the exam.  Remaining positions are
    re-compacted automatically (1, 2, 3, …).

    Raises **404** if the exam_question does not belong to this exam.
    """
    exam = await _get_exam_or_404(db, exam_id)
    svc = ExamAssemblyService(db)

    eq = await svc.get_exam_question_or_none(exam_question_id)
    if eq is None or eq.exam_id != exam.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ExamQuestion {exam_question_id} not found in exam {exam_id}.",
        )

    await svc.remove_question(eq)
    await db.commit()
