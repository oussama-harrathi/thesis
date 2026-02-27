"""
Integration test configuration.

All tests in this directory require a running PostgreSQL instance
(the one provided by docker-compose on port 5433).  If the database
is unreachable, every test in this package is automatically skipped.

Isolation strategy
------------------
Each fixture that creates a top-level object (Course) is responsible for
deleting that object in its teardown via an explicit DELETE statement.
Because every dependent table uses ``ON DELETE CASCADE``, one DELETE on
``courses`` removes all documents, chunks, question_sets, questions,
exam_blueprints, exams, exports, etc. that were created during the test.

Fixtures are function-scoped by default so each test gets a clean DB state.

MockProvider
------------
The ``mock_provider`` fixture provides a deterministic LLM backend.
For MCQ generation tests, queue the MCQ response BEFORE calling generate_mcq:

    mock_provider.queue_response(MCQ_RESPONSE_DICT)

Subsequent LLM calls (difficulty tagging, bloom tagging) fall back to
heuristics automatically when the mock returns an empty / invalid response.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.llm.mock_provider import MockProvider
from app.models.chunk import Chunk
from app.models.course import Course
from app.models.document import Document, DocumentStatus
from app.models.exam import ExamBlueprint, Exam, ExamQuestion
from app.models.question import (
    Difficulty,
    McqOption,
    Question,
    QuestionSet,
    QuestionSetMode,
    QuestionSource,
    QuestionStatus,
    QuestionType,
)

_DB_URL: str = settings.DATABASE_URL


# ── DB connectivity guard ─────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def check_db_available() -> None:
    """
    Skip the entire integration test suite when PostgreSQL is not reachable.

    Called once per pytest session (sync fixture) so the connectivity check
    is cheap and doesn't interfere with the async test runner.
    """

    async def _ping() -> None:
        eng = create_async_engine(_DB_URL, echo=False)
        try:
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await eng.dispose()

    try:
        asyncio.run(_ping())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"Integration tests require a running PostgreSQL (docker-compose). {exc}",
            allow_module_level=True,
        )


# ── Per-test async DB session ─────────────────────────────────────────────────


@pytest.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a live async session connected to the application database.

    The fixture does NOT roll back — each test commits its own writes.
    Top-level ``course`` fixtures clean up all created rows via CASCADE
    DELETE in their teardown.
    """
    eng = create_async_engine(_DB_URL, echo=False, pool_pre_ping=True)
    factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await eng.dispose()


# ── LLM provider ──────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_provider() -> MockProvider:
    """A fresh MockProvider with empty response queue."""
    return MockProvider()


# ── Domain object fixtures ────────────────────────────────────────────────────


@pytest.fixture()
async def course(db_session: AsyncSession) -> AsyncGenerator[Course, None]:
    """
    Create and commit a Course row.
    Teardown deletes it (cascades to ALL child rows created during the test).
    """
    c = Course(
        id=uuid.uuid4(),
        name=f"Integration Test Course {uuid.uuid4().hex[:6]}",
        description="Fixture course for integration tests.",
    )
    db_session.add(c)
    await db_session.commit()

    yield c

    # CASCADE: removes documents, chunks, question_sets, questions,
    #          exam_blueprints, exams, exports, etc.
    await db_session.execute(delete(Course).where(Course.id == c.id))
    await db_session.commit()


@pytest.fixture()
async def document(db_session: AsyncSession, course: Course) -> Document:
    """Create and commit a Document row (metadata only — no real file)."""
    doc = Document(
        id=uuid.uuid4(),
        course_id=course.id,
        filename="test_lecture.pdf",
        original_filename="Lecture 1 – Photosynthesis.pdf",
        file_path="/data/uploads/test_lecture.pdf",
        file_size=524_288,
        mime_type="application/pdf",
        status=DocumentStatus.completed,
    )
    db_session.add(doc)
    await db_session.commit()
    return doc


@pytest.fixture()
async def chunk(db_session: AsyncSession, document: Document) -> Chunk:
    """
    Create a real Chunk row with ``embedding=None`` (the column is nullable).

    The chunk_id is used by question generation fixtures to satisfy the FK
    constraint on ``question_sources.chunk_id`` — no actual pgvector
    operations are needed because retrieval is mocked at the service level.
    """
    ch = Chunk(
        id=uuid.uuid4(),
        document_id=document.id,
        content=(
            "Photosynthesis is the process by which plants use sunlight, water "
            "and carbon dioxide to produce oxygen and energy in the form of glucose. "
            "The light-dependent reactions occur in the thylakoid membranes of the "
            "chloroplast, while the Calvin cycle takes place in the stroma."
        ),
        chunk_index=0,
        start_char=0,
        end_char=300,
        # embedding=None is intentional — we mock retrieval so no pgvector query runs
    )
    db_session.add(ch)
    await db_session.commit()
    return ch


@pytest.fixture()
async def question_set(db_session: AsyncSession, course: Course) -> QuestionSet:
    """Create and commit a professor QuestionSet."""
    qs = QuestionSet(
        id=uuid.uuid4(),
        course_id=course.id,
        mode=QuestionSetMode.professor,
        title="Integration Test Question Set",
    )
    db_session.add(qs)
    await db_session.commit()
    return qs


# ── Reusable builder helpers ──────────────────────────────────────────────────


async def make_mcq_question(
    db_session: AsyncSession,
    question_set: QuestionSet,
    *,
    status: QuestionStatus = QuestionStatus.draft,
    difficulty: Difficulty = Difficulty.medium,
    body: str = "What is the primary product of photosynthesis?",
) -> Question:
    """
    Insert a complete MCQ question (4 options, exactly 1 correct) and commit.

    All options satisfy the distractor validation rules (4 options, 1 correct,
    no duplicates, no catch-all phrases).
    """
    q = Question(
        id=uuid.uuid4(),
        question_set_id=question_set.id,
        type=QuestionType.mcq,
        body=body,
        correct_answer="A",
        explanation="Photosynthesis converts light energy into chemical energy as glucose.",
        difficulty=difficulty,
        status=status,
        model_name="mock",
        prompt_version="test-v1",
    )
    db_session.add(q)
    await db_session.flush()

    for label, text_val, correct in [
        ("A", "Glucose (chemical energy stored in sugar)", True),
        ("B", "Carbon dioxide released into the atmosphere", False),
        ("C", "Water molecules split by cellular respiration", False),
        ("D", "Nitrogen compounds absorbed from the soil", False),
    ]:
        db_session.add(McqOption(
            id=uuid.uuid4(),
            question_id=q.id,
            label=label,
            text=text_val,
            is_correct=correct,
        ))

    await db_session.commit()
    return q


async def make_blueprint(
    db_session: AsyncSession,
    course: Course,
    *,
    title: str = "Integration Test Blueprint",
) -> ExamBlueprint:
    """Create an ExamBlueprint and commit."""
    from app.schemas.blueprint import BlueprintConfig, QuestionTypeCounts

    config = BlueprintConfig(
        question_counts=QuestionTypeCounts(mcq=2),
    )
    bp = ExamBlueprint(
        id=uuid.uuid4(),
        course_id=course.id,
        title=title,
        config_json=config.model_dump_json(),
    )
    db_session.add(bp)
    await db_session.commit()
    return bp


# ── Shared MCQ mock response ──────────────────────────────────────────────────

#: Queue this dict into MockProvider before calling generate_mcq().
MCQ_MOCK_RESPONSE: dict = {
    "insufficient_context": False,
    "questions": [
        {
            "stem": "What is the primary function of chlorophyll in photosynthesis?",
            "options": [
                {
                    "key": "A",
                    "text": "To absorb light energy and transfer it to reaction centres",
                    "is_correct": True,
                },
                {
                    "key": "B",
                    "text": "To catalyse the splitting of water molecules",
                    "is_correct": False,
                },
                {
                    "key": "C",
                    "text": "To convert ATP into glucose in the Calvin cycle",
                    "is_correct": False,
                },
                {
                    "key": "D",
                    "text": "To transport oxygen out of the chloroplast",
                    "is_correct": False,
                },
            ],
            "explanation": (
                "Chlorophyll absorbs light mainly in the blue and red wavelengths "
                "and transfers the energy to the reaction centres of photosystems I and II."
            ),
            "source_hint": "plants use sunlight, water and carbon dioxide to produce glucose",
        }
    ],
}
