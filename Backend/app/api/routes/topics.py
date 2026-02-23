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
from app.schemas.topic import TopicCreate, TopicResponse, TopicUpdate
from app.services.topic_service import TopicService

courses_router = APIRouter(prefix="/courses", tags=["topics"])
topics_router = APIRouter(prefix="/topics", tags=["topics"])

# ── Dependency alias ─────────────────────────────────────────────
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _get_service(db: DbSession) -> TopicService:
    return TopicService(db)


Service = Annotated[TopicService, Depends(_get_service)]


# ── Nested under /courses ─────────────────────────────────────────

@courses_router.get(
    "/{course_id}/topics",
    response_model=list[TopicResponse],
    summary="List topics for a course",
)
async def list_topics(course_id: uuid.UUID, svc: Service) -> list[TopicResponse]:
    topics = await svc.list_by_course(course_id)
    return [TopicResponse.model_validate(t) for t in topics]


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
    return TopicResponse.model_validate(topic)


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
    return TopicResponse.model_validate(topic)


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
