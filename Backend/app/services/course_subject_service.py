"""
Detect the academic subject / domain of a course by sampling its chunks
and asking the LLM.  The result is cached in ``courses.detected_subject``
so the LLM is called at most once per course.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select, func as sa_func

from app.llm.factory import get_llm_provider
from app.utils.chunk_filter import is_excluded_for_generation

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Pydantic schema for the LLM response ────────────────────────────────

class SubjectDetectionOutput(BaseModel):
    subject: str
    description: str


# ── Prompt ───────────────────────────────────────────────────────────────

_SUBJECT_DETECTION_PROMPT = """\
You are an academic curriculum analyst.

Below are excerpts from a university course's uploaded materials.

--- EXCERPTS ---
{excerpts}
--- END EXCERPTS ---

Based ONLY on the excerpts above, identify the academic subject or field
this course belongs to and provide a one-sentence description of the course scope.

Return a JSON object:
{{
  "subject": "<subject name, e.g. Neural Networks and Machine Learning>",
  "description": "<one-sentence scope description>"
}}

Be specific — e.g. "Neural Networks and Machine Learning" rather than just
"Computer Science".  Use only the evidence in the excerpts.
"""

# Maximum total characters to send as sample text.
_MAX_SAMPLE_CHARS = 6000
# How many random chunks to pull for sampling.
_SAMPLE_CHUNK_COUNT = 10
_RAW_SAMPLE_MULTIPLIER = 3


async def detect_course_subject(
    db: "AsyncSession",
    course_id: uuid.UUID,
) -> str:
    """
    Detect and persist the academic subject for a course.

    If ``courses.detected_subject`` is already set, return it immediately
    (no LLM call).  Otherwise, sample some chunks, ask the LLM, and save
    the result.

    Returns the detected subject string (e.g. "Neural Networks and Machine
    Learning").
    """
    from app.models.course import Course

    course = await db.get(Course, course_id)
    if course is None:
        logger.warning("detect_course_subject: course %s not found", course_id)
        return ""

    # Already detected?  Return cached value.
    if course.detected_subject:
        return course.detected_subject

    # ── Sample chunks ────────────────────────────────────────────────
    from app.models.chunk import Chunk
    from app.models.document import Document

    stmt = (
        select(Chunk.content)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.course_id == course_id)
        .where(Chunk.content.isnot(None))
        .order_by(sa_func.random())
        .limit(_SAMPLE_CHUNK_COUNT * _RAW_SAMPLE_MULTIPLIER)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        logger.warning(
            "detect_course_subject: no chunks found for course %s", course_id
        )
        return ""

    # Prefer instructional chunks when building the subject sample.
    filtered_rows = [text for text in rows if not is_excluded_for_generation(text)]
    sample_rows = filtered_rows[:_SAMPLE_CHUNK_COUNT] or rows[:_SAMPLE_CHUNK_COUNT]

    # Build excerpt text, capping total length.
    excerpts: list[str] = []
    total = 0
    for text in sample_rows:
        if total + len(text) > _MAX_SAMPLE_CHARS:
            remaining = _MAX_SAMPLE_CHARS - total
            if remaining > 200:
                excerpts.append(text[:remaining])
            break
        excerpts.append(text)
        total += len(text)

    sample_text = "\n\n---\n\n".join(excerpts)

    # ── Call LLM ─────────────────────────────────────────────────────
    provider = get_llm_provider()
    prompt = _SUBJECT_DETECTION_PROMPT.format(excerpts=sample_text)

    try:
        result: SubjectDetectionOutput = await provider.generate_json(
            prompt, SubjectDetectionOutput
        )
        detected = result.subject.strip()
    except Exception as exc:
        logger.error(
            "detect_course_subject: LLM call failed for course %s: %s",
            course_id, exc, exc_info=True,
        )
        # Fallback: use the course name itself.
        detected = course.name

    if not detected:
        detected = course.name

    # ── Persist ──────────────────────────────────────────────────────
    course.detected_subject = detected
    await db.flush()

    logger.info(
        "detect_course_subject: course %s → %r",
        course_id, detected,
    )
    return detected
