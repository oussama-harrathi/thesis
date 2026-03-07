"""
Blueprint Service

Business logic for creating, reading, and updating ExamBlueprint records,
plus slot expansion to drive the question-generation Celery task.

All public async methods accept an open SQLAlchemy AsyncSession.
The caller (FastAPI route handler via get_db dependency) is responsible
for committing or rolling back the transaction.

Slot expansion (``expand_to_slots``) is a pure static method — no DB, no I/O.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exam import ExamBlueprint
from app.models.question import Difficulty, QuestionSet, QuestionType
from app.schemas.blueprint import (
    BlueprintConfig,
    BlueprintCreateRequest,
    BlueprintUpdateRequest,
)

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.question import QuestionSet

logger = logging.getLogger(__name__)


# ── Generation slot ───────────────────────────────────────────────────────────


@dataclass
class GenerationSlot:
    """
    A single generation unit: generate *count* questions of a given type,
    difficulty, and (optionally) topic.

    Slots are produced by ``BlueprintService.expand_to_slots()`` and consumed
    one-by-one by the ``generate_from_blueprint`` Celery task.
    """

    question_type: QuestionType
    difficulty: Difficulty
    count: int
    topic_id: uuid.UUID | None = field(default=None)
    topic_name: str = field(default="General")


# ── Private helpers ───────────────────────────────────────────────────────────


def _distribute(total: int, proportions: dict[str, float]) -> dict[str, int]:
    """
    Distribute *total* integer items across keys using the given proportions.

    The result always sums to *total* exactly — rounding remainder is assigned
    to the keys with the largest fractional parts (largest-remainder method).

    Parameters
    ----------
    total       : The whole number to distribute (e.g. 10 questions).
    proportions : ``{key: weight}`` — weights need not sum to 1.0 exactly.

    Returns
    -------
    ``{key: count}`` where all counts are ≥ 0 and their sum equals *total*.
    """
    if not proportions or total == 0:
        return {k: 0 for k in proportions}

    total_weight = sum(proportions.values())
    if total_weight == 0:
        return {k: 0 for k in proportions}

    raw = {k: total * (v / total_weight) for k, v in proportions.items()}
    floors = {k: int(v) for k, v in raw.items()}
    remainder = total - sum(floors.values())

    # Distribute remaining units by largest fractional part.
    fractions = sorted(
        ((k, raw[k] - floors[k]) for k in raw),
        key=lambda x: x[1],
        reverse=True,
    )
    result = dict(floors)
    for i in range(remainder):
        result[fractions[i][0]] += 1

    return result


class BlueprintService:
    """CRUD operations for ExamBlueprint."""

    # ------------------------------------------------------------------ #
    # Create                                                               #
    # ------------------------------------------------------------------ #

    async def create(
        self,
        db: AsyncSession,
        *,
        course_id: uuid.UUID,
        payload: BlueprintCreateRequest,
    ) -> ExamBlueprint:
        """
        Persist a new ExamBlueprint for *course_id*.

        ``payload.config`` (a ``BlueprintConfig`` instance) has already been
        validated by Pydantic; it is serialised to JSON for storage.

        Parameters
        ----------
        db        : Open async session.
        course_id : The course this blueprint belongs to.
        payload   : Validated create request.

        Returns
        -------
        The newly-inserted (and flushed) ExamBlueprint ORM object.
        """
        config_json = payload.config.model_dump_json()

        blueprint = ExamBlueprint(
            id=uuid.uuid4(),
            course_id=course_id,
            title=payload.title,
            description=payload.description,
            config_json=config_json,
        )
        db.add(blueprint)
        await db.flush()

        logger.info(
            "BlueprintService.create: blueprint=%s course=%s title=%r",
            blueprint.id,
            course_id,
            blueprint.title,
        )
        return blueprint

    # ------------------------------------------------------------------ #
    # Read                                                                 #
    # ------------------------------------------------------------------ #

    async def list_for_course(
        self,
        db: AsyncSession,
        *,
        course_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExamBlueprint]:
        """
        Return all blueprints for *course_id*, newest first.

        Parameters
        ----------
        db        : Open async session.
        course_id : Filter by this course UUID.
        limit     : Max rows to return (default 50).
        offset    : Pagination offset (default 0).

        Returns
        -------
        List of ExamBlueprint ORM objects (may be empty).
        """
        stmt = (
            select(ExamBlueprint)
            .where(ExamBlueprint.course_id == course_id)
            .order_by(ExamBlueprint.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return list(rows)

    async def get_by_id(
        self,
        db: AsyncSession,
        blueprint_id: uuid.UUID,
    ) -> ExamBlueprint | None:
        """
        Return a single ExamBlueprint by primary key, or None if not found.

        Parameters
        ----------
        db           : Open async session.
        blueprint_id : Primary key UUID.

        Returns
        -------
        ExamBlueprint or None.
        """
        stmt = select(ExamBlueprint).where(ExamBlueprint.id == blueprint_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Update                                                               #
    # ------------------------------------------------------------------ #

    async def update(
        self,
        db: AsyncSession,
        blueprint: ExamBlueprint,
        *,
        payload: BlueprintUpdateRequest,
    ) -> ExamBlueprint:
        """
        Apply a partial update to an existing ExamBlueprint.

        Only fields present (non-None) in *payload* are updated.
        ``payload.config``, if supplied, replaces the entire config_json.

        Parameters
        ----------
        db        : Open async session.
        blueprint : The ORM object to update (already loaded by caller).
        payload   : Validated PATCH request (all fields optional).

        Returns
        -------
        The mutated (and flushed) ExamBlueprint ORM object.
        """
        if payload.title is not None:
            blueprint.title = payload.title

        if payload.description is not None:
            blueprint.description = payload.description

        if payload.config is not None:
            blueprint.config_json = payload.config.model_dump_json()

        db.add(blueprint)
        await db.flush()

        logger.info(
            "BlueprintService.update: blueprint=%s",
            blueprint.id,
        )
        return blueprint

    # ------------------------------------------------------------------ #
    # Delete                                                               #
    # ------------------------------------------------------------------ #

    async def delete_with_questions(
        self,
        db: AsyncSession,
        blueprint: ExamBlueprint,
    ) -> None:
        """
        Delete *blueprint* and all questions that were generated for it.

        Cascade chain:
        1. Locate every QuestionSet whose blueprint_id matches.
        2. Delete each QuestionSet — DB CASCADE removes all child Questions,
           MCQOptions, QuestionSources, and QuestionValidations automatically.
        3. Delete the blueprint — DB CASCADE removes BlueprintQuestion mapping
           rows automatically.

        The caller is responsible for committing after this method returns.
        """
        stmt = select(QuestionSet).where(QuestionSet.blueprint_id == blueprint.id)
        result = await db.execute(stmt)
        question_sets = result.scalars().all()

        for qs in question_sets:
            await db.delete(qs)

        await db.flush()  # ensure question_set deletes propagate before blueprint delete

        await db.delete(blueprint)
        await db.flush()

        logger.info(
            "BlueprintService.delete_with_questions: deleted blueprint=%s "
            "question_sets=%d",
            blueprint.id,
            len(question_sets),
        )

    # ------------------------------------------------------------------ #
    # Slot expansion (pure — no I/O)                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def expand_to_slots(config: BlueprintConfig) -> list[GenerationSlot]:
        """
        Expand a ``BlueprintConfig`` into a flat list of ``GenerationSlot`` items.

        Each slot represents one call to the question generator:
        ``(question_type, difficulty, topic_id, count)``.

        Slot allocation logic
        ─────────────────────
        1. For each question type (mcq / true_false / short_answer / essay)
           whose count > 0:
             a. Use ``_distribute()`` to split that type's total across the
                three difficulty levels according to ``difficulty_mix``.
             b. For **auto** topic mode:
                  Create one slot per (type, difficulty) with topic_id=None.
                  The generation service retrieves chunks from the whole course.
             c. For **manual** topic mode:
                  For each TopicEntry, compute its contribution to this type
                  by scaling topic_entry.question_count proportionally.
                  Then split that scaled count across difficulties.
                  Create one slot per (type, difficulty, topic).

        The resulting slots may be empty for any combination where the rounded
        count rounds to zero (e.g. 1 question × 0.0 difficulty proportion).

        Returns
        -------
        Ordered list of ``GenerationSlot``; never None.
        """
        type_totals: dict[QuestionType, int] = {
            QuestionType.mcq: config.question_counts.mcq,
            QuestionType.true_false: config.question_counts.true_false,
            QuestionType.short_answer: config.question_counts.short_answer,
            QuestionType.essay: config.question_counts.essay,
        }
        diff_props: dict[str, float] = {
            "easy": config.difficulty_mix.easy,
            "medium": config.difficulty_mix.medium,
            "hard": config.difficulty_mix.hard,
        }

        slots: list[GenerationSlot] = []

        if config.topic_mix.mode == "auto":
            for qtype, type_total in type_totals.items():
                if type_total == 0:
                    continue
                diff_counts = _distribute(type_total, diff_props)
                for diff_str, count in diff_counts.items():
                    if count > 0:
                        slots.append(
                            GenerationSlot(
                                question_type=qtype,
                                difficulty=Difficulty(diff_str),
                                count=count,
                                topic_id=None,
                                topic_name="General",
                            )
                        )

        else:  # manual
            q_total = config.question_counts.total
            # Proportional weight of each type among all questions.
            type_props: dict[str, float] = {
                qt.value: tc / q_total
                for qt, tc in type_totals.items()
                if tc > 0 and q_total > 0
            }

            for entry in config.topic_mix.topics:
                topic_type_counts = _distribute(entry.question_count, type_props)
                for qtype in type_totals:
                    if type_totals[qtype] == 0:
                        continue
                    t_count = topic_type_counts.get(qtype.value, 0)
                    if t_count == 0:
                        continue
                    diff_counts = _distribute(t_count, diff_props)
                    for diff_str, count in diff_counts.items():
                        if count > 0:
                            slots.append(
                                GenerationSlot(
                                    question_type=qtype,
                                    difficulty=Difficulty(diff_str),
                                    count=count,
                                    topic_id=entry.topic_id,
                                    topic_name=str(entry.topic_id),
                                )
                            )

        return slots

    # ------------------------------------------------------------------ #
    # Job + QuestionSet creation (called by the start-generation endpoint) #
    # ------------------------------------------------------------------ #

    async def create_generation_job(
        self,
        db: AsyncSession,
        blueprint: ExamBlueprint,
    ) -> tuple["Job", "QuestionSet"]:
        """
        Create a pending Job and a new professor QuestionSet for a blueprint.

        The caller must flush/commit after this returns.

        Returns
        -------
        (job, question_set) — two newly-inserted ORM objects.
        """
        from app.models.job import Job, JobStatus, JobType
        from app.models.question import QuestionSet, QuestionSetMode

        question_set = QuestionSet(
            id=uuid.uuid4(),
            course_id=blueprint.course_id,
            mode=QuestionSetMode.professor,
            title=f"Generated from: {blueprint.title}",
            blueprint_id=blueprint.id,
        )
        db.add(question_set)
        await db.flush()

        job = Job(
            id=uuid.uuid4(),
            type=JobType.question_generation,
            status=JobStatus.pending,
            course_id=blueprint.course_id,
            blueprint_id=blueprint.id,
            progress=0,
            message="Queued for generation.",
        )
        db.add(job)
        await db.flush()

        logger.info(
            "BlueprintService.create_generation_job: job=%s question_set=%s blueprint=%s",
            job.id,
            question_set.id,
            blueprint.id,
        )
        return job, question_set
