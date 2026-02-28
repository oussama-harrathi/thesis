"""
TopicService — async CRUD for Topic rows.

Intended for use in FastAPI route handlers (AsyncSession).

Operations
──────────
list_by_course(course_id)       → list[tuple[Topic, int]]  (topic, chunk_count)
get_by_id(topic_id)             → Topic | None
create(course_id, data)         → Topic          (manual, is_auto_extracted=False)
update(topic_id, data)          → Topic | None
delete(topic_id)                → bool
reextract(course_id)            → list[Topic]    (background-safe sync call)
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.topic import Topic, TopicChunkMap
from app.schemas.topic import TopicCreate, TopicUpdate
from app.services.topic_extraction.base import CourseExtractionMeta

logger = logging.getLogger(__name__)


class TopicService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Queries ───────────────────────────────────────────────────

    async def list_by_course(
        self, course_id: uuid.UUID
    ) -> list[tuple[Topic, int]]:
        """Return all topics for a course with their chunk counts, ordered by name."""
        subq = (
            select(
                TopicChunkMap.topic_id,
                func.count(TopicChunkMap.id).label("cnt"),
            )
            .group_by(TopicChunkMap.topic_id)
            .subquery()
        )
        stmt = (
            select(Topic, func.coalesce(subq.c.cnt, 0).label("chunk_count"))
            .outerjoin(subq, Topic.id == subq.c.topic_id)
            .where(Topic.course_id == course_id)
            .order_by(Topic.name)
        )
        result = await self._db.execute(stmt)
        return [(row.Topic, int(row.chunk_count)) for row in result]

    async def get_by_id(self, topic_id: uuid.UUID) -> Topic | None:
        return await self._db.get(Topic, topic_id)

    # ── Mutations ─────────────────────────────────────────────────

    async def create(self, course_id: uuid.UUID, data: TopicCreate) -> Topic:
        """Create a manually-added topic (is_auto_extracted=False, source='MANUAL')."""
        topic = Topic(
            course_id=course_id,
            name=data.name.strip(),
            is_auto_extracted=False,
            source="MANUAL",
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

    # ── Re-extraction ─────────────────────────────────────────────

    async def reextract(self, course_id: uuid.UUID) -> tuple[list[Topic], CourseExtractionMeta | None]:
        """
        Delete all auto-extracted topics for *course_id* and re-run the
        pluggable extraction pipeline (TopicExtractionOrchestrator).

        Manually-added topics (is_auto_extracted=False) are preserved.

        This runs the sync orchestrator inside a sync session bridge because
        Celery workers use sync sessions but this service uses AsyncSession.
        We run a sync block using the async session's bind.
        """
        from sqlalchemy import text as _text

        # Delete auto-extracted topics and cascade mappings
        await self._db.execute(
            delete(Topic).where(
                Topic.course_id == course_id,
                Topic.is_auto_extracted.is_(True),
            )
        )
        await self._db.flush()

        # Fetch chunks for the course (all documents)
        chunks_result = await self._db.execute(
            select(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.course_id == course_id)
        )
        chunks = list(chunks_result.scalars().all())
        if not chunks:
            return [], None

        # Get the file path from the most recently processed document
        doc_result = await self._db.execute(
            select(Document)
            .where(Document.course_id == course_id)
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        doc = doc_result.scalar_one_or_none()
        source_path = doc.file_path if doc else None

        # Run orchestrator (sync) using the underlying sync connection
        from app.services.embedding_service import EmbeddingService
        from app.services.topic_extraction.orchestrator import TopicExtractionOrchestrator

        emb_svc = EmbeddingService()
        orch = TopicExtractionOrchestrator(emb_svc)

        # AsyncSession exposes sync session via run_sync
        def _sync_extract(sync_session):  # type: ignore[no-untyped-def]
            rows, meta = orch.extract_and_save(
                db=sync_session,
                course_id=course_id,
                chunks=chunks,
                file_path=source_path or "",
            )
            return rows, meta

        result = await self._db.run_sync(_sync_extract)
        topic_rows, meta = result
        return topic_rows, meta
