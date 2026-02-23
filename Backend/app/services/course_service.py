"""
CourseService — all business logic for Course CRUD.

Keeps route handlers thin: they call these methods and return the result.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.schemas.course import CourseCreate, CourseUpdate

logger = logging.getLogger(__name__)


class CourseService:
    """CRUD operations for the Course resource."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Create ────────────────────────────────────────────────────

    async def create(self, data: CourseCreate) -> Course:
        """Persist a new course and return the ORM instance."""
        course = Course(
            name=data.name,
            description=data.description,
        )
        self._db.add(course)
        await self._db.flush()  # populate id / server defaults
        await self._db.refresh(course)
        logger.info("Created course id=%s name=%r", course.id, course.name)
        return course

    # ── Read ──────────────────────────────────────────────────────

    async def list_all(self) -> Sequence[Course]:
        """Return all courses ordered by creation date (newest first)."""
        result = await self._db.execute(
            select(Course).order_by(Course.created_at.desc())
        )
        return result.scalars().all()

    async def get_by_id(self, course_id: uuid.UUID) -> Course | None:
        """Return a single course or None if not found."""
        result = await self._db.execute(
            select(Course).where(Course.id == course_id)
        )
        return result.scalar_one_or_none()

    # ── Update ────────────────────────────────────────────────────

    async def update(
        self, course_id: uuid.UUID, data: CourseUpdate
    ) -> Course | None:
        """
        Apply partial updates (only provided fields).
        Returns the updated course or None if not found.
        """
        course = await self.get_by_id(course_id)
        if course is None:
            return None

        patch = data.model_dump(exclude_unset=True)
        for field, value in patch.items():
            setattr(course, field, value)

        await self._db.flush()
        await self._db.refresh(course)
        logger.info("Updated course id=%s fields=%s", course.id, list(patch.keys()))
        return course
