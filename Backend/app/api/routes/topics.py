"""
Topics API routes.

GET    /api/v1/courses/{course_id}/topics          → list topics for a course
POST   /api/v1/courses/{course_id}/topics          → add manual topic
PATCH  /api/v1/topics/{topic_id}                   → rename topic
DELETE /api/v1/topics/{topic_id}                   → delete topic
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.topic import Topic
from app.schemas.topic import (
    CourseExtractionMetaResponse,
    TopicCreate,
    TopicListResponse,
    TopicResponse,
    TopicUpdate,
)
from app.services.topic_extraction.orchestrator import get_extraction_meta
from app.services.topic_service import TopicService

courses_router = APIRouter(prefix="/courses", tags=["topics"])
topics_router = APIRouter(prefix="/topics", tags=["topics"])

# ── Dependency alias ─────────────────────────────────────────────
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _get_service(db: DbSession) -> TopicService:
    return TopicService(db)


Service = Annotated[TopicService, Depends(_get_service)]


# ── Helper ────────────────────────────────────────────────────────

def _build_response(topic: Topic, chunk_count: int = 0) -> TopicResponse:
    """Construct a TopicResponse from an ORM Topic + chunk count."""
    return TopicResponse(
        id=topic.id,
        course_id=topic.course_id,
        name=topic.name,
        is_auto_extracted=topic.is_auto_extracted,
        source=topic.source,
        level=topic.level,
        parent_topic_id=topic.parent_topic_id,
        coverage_score=topic.coverage_score,
        chunk_count=chunk_count,
        created_at=topic.created_at,
        updated_at=topic.updated_at,
    )


# ── Nested under /courses ─────────────────────────────────────────

@courses_router.get(
    "/{course_id}/topics",
    response_model=TopicListResponse,
    summary="List topics for a course",
)
async def list_topics(
    course_id: uuid.UUID, svc: Service
) -> TopicListResponse:
    pairs = await svc.list_by_course(course_id)
    topic_responses = [_build_response(topic, chunk_count) for topic, chunk_count in pairs]
    raw_meta = get_extraction_meta(course_id)
    meta_response = (
        CourseExtractionMetaResponse(
            chosen_method=raw_meta.chosen_method,
            overall_confidence=raw_meta.overall_confidence,
            is_low_confidence=raw_meta.is_low_confidence,
            coverage_ratio=raw_meta.coverage_ratio,
            topic_count=raw_meta.topic_count,
        )
        if raw_meta is not None
        else None
    )
    return TopicListResponse(topics=topic_responses, extraction_meta=meta_response)


@courses_router.post(
    "/{course_id}/topics",
    response_model=TopicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a manual topic to a course",
)
async def create_topic(
    course_id: uuid.UUID,
    body: TopicCreate,
    svc: Service,
) -> TopicResponse:
    topic = await svc.create(course_id, body)
    return _build_response(topic, chunk_count=0)


@courses_router.post(
    "/{course_id}/topics/reextract",
    response_model=TopicListResponse,
    summary="Re-run topic extraction for a course (replaces all auto-extracted topics)",
)
async def reextract_topics(
    course_id: uuid.UUID,
    svc: Service,
) -> TopicListResponse:
    """
    Deletes all auto-extracted topics for the course and re-runs the full
    pluggable extraction pipeline (PDF outline → layout → regex → clusters).
    Manually-added topics are preserved.
    """
    topic_rows, meta = await svc.reextract(course_id)
    topic_responses = [_build_response(t, chunk_count=0) for t in topic_rows]
    meta_response = (
        CourseExtractionMetaResponse(
            chosen_method=meta.chosen_method,
            overall_confidence=meta.overall_confidence,
            is_low_confidence=meta.is_low_confidence,
            coverage_ratio=meta.coverage_ratio,
            topic_count=meta.topic_count,
        )
        if meta is not None
        else None
    )
    return TopicListResponse(topics=topic_responses, extraction_meta=meta_response)


# ── Standalone /topics ────────────────────────────────────────────

@topics_router.patch(
    "/{topic_id}",
    response_model=TopicResponse,
    summary="Rename a topic",
)
async def update_topic(
    topic_id: uuid.UUID,
    body: TopicUpdate,
    svc: Service,
) -> TopicResponse:
    topic = await svc.update(topic_id, body)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topic {topic_id} not found.",
        )
    return _build_response(topic, chunk_count=0)


@topics_router.delete(
    "/{topic_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a topic",
)
async def delete_topic(topic_id: uuid.UUID, svc: Service) -> None:
    deleted = await svc.delete(topic_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topic {topic_id} not found.",
        )
