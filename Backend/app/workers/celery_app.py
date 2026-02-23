"""
Celery application instance.

Import this module (not tasks.py directly) to get the configured Celery app.
The broker and result backend both use REDIS_URL from settings.

Usage:
    from app.workers.celery_app import celery_app
"""

from celery import Celery
from celery.utils.log import get_task_logger  # noqa: F401 – re-exported for convenience

from app.core.config import settings

celery_app = Celery(
    "exam_builder",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],   # auto-discover tasks module
)

# ── Celery configuration ─────────────────────────────────────────
celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Retry / ack behaviour
    task_acks_late=True,            # ack only after the task finishes
    task_reject_on_worker_lost=True,
    # Result expiry (keep for 24 h so the API can poll)
    result_expires=60 * 60 * 24,
    # Prevent silent drops on large payloads
    worker_prefetch_multiplier=1,
)
