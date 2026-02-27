"""
Integration tests: Course and Document persistence.

Verifies that ORM models can be written to and read from a live PostgreSQL
instance, exercising the Course, Document, and Chunk models.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.course import Course
from app.models.document import Document, DocumentStatus


# ── Course ─────────────────────────────────────────────────────────────────────


class TestCoursePersistence:
    """The ``course`` fixture creates and commits a Course row."""

    async def test_course_row_exists(
        self, db_session: AsyncSession, course: Course
    ) -> None:
        """Row can be retrieved by PK after the fixture commits it."""
        result = await db_session.execute(
            select(Course).where(Course.id == course.id)
        )
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.id == course.id

    async def test_course_name_persisted(
        self, db_session: AsyncSession, course: Course
    ) -> None:
        """Name attribute survives a round-trip."""
        result = await db_session.execute(
            select(Course).where(Course.id == course.id)
        )
        found = result.scalar_one()
        assert found.name == course.name

    async def test_course_description_persisted(
        self, db_session: AsyncSession, course: Course
    ) -> None:
        result = await db_session.execute(
            select(Course).where(Course.id == course.id)
        )
        found = result.scalar_one()
        assert found.description == "Fixture course for integration tests."

    async def test_multiple_courses_are_independent(
        self, db_session: AsyncSession
    ) -> None:
        """Two separately created courses have distinct IDs."""
        c1 = Course(id=uuid.uuid4(), name="Alpha Course", description=None)
        c2 = Course(id=uuid.uuid4(), name="Beta Course", description=None)
        db_session.add(c1)
        db_session.add(c2)
        await db_session.commit()

        try:
            result = await db_session.execute(
                select(Course).where(Course.id.in_([c1.id, c2.id]))
            )
            found = result.scalars().all()
            assert len(found) == 2
            ids = {row.id for row in found}
            assert c1.id in ids
            assert c2.id in ids
        finally:
            from sqlalchemy import delete
            await db_session.execute(delete(Course).where(Course.id.in_([c1.id, c2.id])))
            await db_session.commit()


# ── Document ──────────────────────────────────────────────────────────────────


class TestDocumentPersistence:
    """The ``document`` fixture creates and commits a Document linked to ``course``."""

    async def test_document_row_exists(
        self, db_session: AsyncSession, document: Document
    ) -> None:
        result = await db_session.execute(
            select(Document).where(Document.id == document.id)
        )
        found = result.scalar_one_or_none()
        assert found is not None

    async def test_document_linked_to_course(
        self, db_session: AsyncSession, document: Document, course: Course
    ) -> None:
        result = await db_session.execute(
            select(Document).where(Document.id == document.id)
        )
        found = result.scalar_one()
        assert found.course_id == course.id

    async def test_document_status_is_completed(
        self, db_session: AsyncSession, document: Document
    ) -> None:
        result = await db_session.execute(
            select(Document).where(Document.id == document.id)
        )
        found = result.scalar_one()
        assert found.status == DocumentStatus.completed

    async def test_document_filename_persisted(
        self, db_session: AsyncSession, document: Document
    ) -> None:
        result = await db_session.execute(
            select(Document).where(Document.id == document.id)
        )
        found = result.scalar_one()
        assert found.filename == "test_lecture.pdf"
        assert found.original_filename == "Lecture 1 – Photosynthesis.pdf"


# ── Chunk ─────────────────────────────────────────────────────────────────────


class TestChunkPersistence:
    """The ``chunk`` fixture creates a Chunk row with embedding=None."""

    async def test_chunk_row_exists(
        self, db_session: AsyncSession, chunk: Chunk
    ) -> None:
        result = await db_session.execute(
            select(Chunk).where(Chunk.id == chunk.id)
        )
        found = result.scalar_one_or_none()
        assert found is not None

    async def test_chunk_linked_to_document(
        self, db_session: AsyncSession, chunk: Chunk, document: Document
    ) -> None:
        result = await db_session.execute(
            select(Chunk).where(Chunk.id == chunk.id)
        )
        found = result.scalar_one()
        assert found.document_id == document.id

    async def test_chunk_content_persisted(
        self, db_session: AsyncSession, chunk: Chunk
    ) -> None:
        result = await db_session.execute(
            select(Chunk).where(Chunk.id == chunk.id)
        )
        found = result.scalar_one()
        assert "Photosynthesis" in found.content
        assert found.chunk_index == 0

    async def test_chunk_embedding_nullable(
        self, db_session: AsyncSession, chunk: Chunk
    ) -> None:
        """Embedding column accepts NULL — real embeddings are only needed for pgvector queries."""
        result = await db_session.execute(
            select(Chunk).where(Chunk.id == chunk.id)
        )
        found = result.scalar_one()
        # embedding is either None or a vector — in our fixture it is None
        # The important thing is the row persisted without error.
        assert found.id == chunk.id
