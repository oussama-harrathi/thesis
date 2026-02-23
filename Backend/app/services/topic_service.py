"""
TopicService — async CRUD for Topic rows.

Intended for use in FastAPI route handlers (AsyncSession).

Operations
──────────
list_by_course(course_id)       → list[Topic]
get_by_id(topic_id)             → Topic | None
create(course_id, data)         → Topic          (manual, is_auto_extracted=False)
update(topic_id, data)          → Topic | None
delete(topic_id)                → bool
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topic import Topic
from app.schemas.topic import TopicCreate, TopicUpdate


class TopicService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Queries ───────────────────────────────────────────────────

    async def list_by_course(self, course_id: uuid.UUID) -> list[Topic]:
        """Return all topics for a course, ordered by name."""
        result = await self._db.execute(
            select(Topic)
            .where(Topic.course_id == course_id)
            .order_by(Topic.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, topic_id: uuid.UUID) -> Topic | None:
        return await self._db.get(Topic, topic_id)

    # ── Mutations ─────────────────────────────────────────────────

    async def create(self, course_id: uuid.UUID, data: TopicCreate) -> Topic:
        """Create a manually-added topic (is_auto_extracted=False)."""
        topic = Topic(
            course_id=course_id,
            name=data.name.strip(),
            is_auto_extracted=False,
        )
        self._db.add(topic)
        await self._db.flush()
        await self._db.refresh(topic)
        return topic

    async def update(self, topic_id: uuid.UUID, data: TopicUpdate) -> Topic | None:
        """Rename a topic; returns None if not found."""
        topic = await self.get_by_id(topic_id)
        if topic is None:
            return None
        topic.name = data.name.strip()
        await self._db.flush()
        await self._db.refresh(topic)
        return topic

    async def delete(self, topic_id: uuid.UUID) -> bool:
        """Delete a topic and its chunk mappings (cascade).  Returns False if not found."""
        topic = await self.get_by_id(topic_id)
        if topic is None:
            return False
        await self._db.delete(topic)
        await self._db.flush()
        return True
