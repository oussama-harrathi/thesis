"""
Celery application instance.

Import this module (not tasks.py directly) to get the configured Celery app.
The broker and result backend both use REDIS_URL from settings.

Usage:
    from app.workers.celery_app import celery_app
"""

import os
import signal
import sys

from celery import Celery
from celery.signals import worker_ready
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
    # ── Shutdown / time limits ────────────────────────────────────
    # Soft limit: task receives SoftTimeLimitExceeded (can clean up).
    # Hard limit: worker kills the task process unconditionally.
    # Generation tasks typically finish in < 5 min; 10 min hard cap
    # prevents a hung task from blocking Ctrl+C indefinitely.
    task_soft_time_limit=540,       # 9 min — task gets SoftTimeLimitExceeded
    task_time_limit=600,            # 10 min — hard kill
    # Cancel tasks that are still in the queue on warm shutdown so
    # Ctrl+C doesn't wait for all queued slots to drain.
    worker_cancel_long_running_tasks_on_connection_loss=True,
)


# ── Windows Ctrl+C fix ────────────────────────────────────────────────────────
# On Windows, SIGTERM is not available; SIGBREAK (Ctrl+Break) and SIGINT
# (Ctrl+C) are. Register SIGBREAK so that pressing Ctrl+Break forces an
# immediate hard exit when the warm-shutdown stalls.
@worker_ready.connect
def _register_windows_sigbreak(**kwargs: object) -> None:  # noqa: ARG001
    if sys.platform != "win32":
        return
    try:
        def _hard_exit(signum: int, frame: object) -> None:  # noqa: ARG001
            print("\n[worker] SIGBREAK received — forcing exit.", flush=True)
            # os._exit() bypasses all Python cleanup (atexit, __del__, asyncio
            # event loops) so it works even when asyncio.run() is blocking.
            os._exit(0)  # noqa: SLF001

        signal.signal(signal.SIGBREAK, _hard_exit)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass  # not available on this platform — ignore
