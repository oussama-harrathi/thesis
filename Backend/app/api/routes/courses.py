"""
Course API routes.

POST   /api/v1/courses          → create a course
GET    /api/v1/courses          → list all courses
GET    /api/v1/courses/{id}     → get course by id
PATCH  /api/v1/courses/{id}     → partial update
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.course import CourseCreate, CourseResponse, CourseUpdate
from app.services.course_service import CourseService

router = APIRouter(prefix="/courses", tags=["courses"])

# ── Dependency alias ─────────────────────────────────────────────
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _get_service(db: DbSession) -> CourseService:
    return CourseService(db)


Service = Annotated[CourseService, Depends(_get_service)]


# ── Endpoints ────────────────────────────────────────────────────


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(body: CourseCreate, svc: Service) -> CourseResponse:
    """Create a new course."""
    course = await svc.create(body)
    return CourseResponse.model_validate(course)


@router.get("", response_model=list[CourseResponse])
async def list_courses(svc: Service) -> list[CourseResponse]:
    """Return all courses (newest first)."""
    courses = await svc.list_all()
    return [CourseResponse.model_validate(c) for c in courses]


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(course_id: uuid.UUID, svc: Service) -> CourseResponse:
    """Return a single course by its UUID."""
    course = await svc.get_by_id(course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
    return CourseResponse.model_validate(course)


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: uuid.UUID, body: CourseUpdate, svc: Service
) -> CourseResponse:
    """Partially update a course's name and/or description."""
    course = await svc.update(course_id, body)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
    return CourseResponse.model_validate(course)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(course_id: uuid.UUID, svc: Service) -> None:
    """Delete a course and all its associated data (cascades)."""
    deleted = await svc.delete(course_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
