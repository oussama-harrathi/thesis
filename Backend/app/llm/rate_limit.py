"""
Provider-agnostic token-budget rate-limit manager.

Problem
-------
Groq free tier: 12 000 tokens per minute (TPM).  With one call consuming
~2 600 tokens, firing 10 sequential calls takes only ~3 seconds but uses
~26 000 tokens — 2× the limit, causing a flood of 429 errors.

Solution
--------
``RateLimitManager`` is a sliding-window token tracker.  Before every LLM
request, callers ``await rate_limit_manager.acquire(estimated_tokens)``.
If the acquisition would push usage past the TPM limit, the coroutine sleeps
until the oldest window entry expires and capacity becomes available.

This is complementary to (not a replacement for) 429-retry backoff in the
provider: the manager *prevents* most rate-limit hits proactively, while the
provider's backoff *recovers* from the hits that still slip through.

Configuration
-------------
LLM_TPM_LIMIT  — tokens per minute (default: 12 000 for Groq free tier).
                 Set to a large number (e.g. 1 000 000) to effectively
                 disable pacing for providers without strict TPM limits.

Usage
-----
    from app.llm.rate_limit import rate_limit_manager

    async def call_llm():
        estimated = rate_limit_manager.estimate_tokens(prompt_text)
        await rate_limit_manager.acquire(estimated)
        result = await provider.generate_json(...)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimitManager:
    """
    Sliding-window async token budgeter.

    Thread/coroutine safety: protected by an ``asyncio.Lock``.  Only one
    coroutine holds the lock at a time; the lock is released while sleeping
    so other coroutines can proceed or check the window in parallel.
    """

    def __init__(self, tpm_limit: int) -> None:
        self._tpm_limit = tpm_limit
        # Each entry: (monotonic insertion time, token count)
        self._window: deque[tuple[float, int]] = deque()
        self._lock: asyncio.Lock | None = None  # created lazily inside async context

    # ── Public API ─────────────────────────────────────────────────────────

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Heuristic: 1 token ≈ 4 chars (sufficient for English + maths).

        Always returns at least 1 to avoid zero-token entries.
        """
        return max(1, len(text) // 4)

    async def acquire(self, estimated_tokens: int) -> None:
        """
        Block until *estimated_tokens* fit inside the current 60-second window.

        Updates the internal window entry after acquiring capacity.

        Parameters
        ----------
        estimated_tokens : Approximate token count for the upcoming request.
                           Use ``estimate_tokens(prompt_text)`` to compute.
        """
        lock = await self._get_lock()

        async with lock:
            while True:
                self._purge()
                current_usage = sum(t for _, t in self._window)

                if current_usage + estimated_tokens <= self._tpm_limit:
                    self._window.append((time.monotonic(), estimated_tokens))
                    logger.debug(
                        "RateLimitManager.acquire: ok — usage=%d + requested=%d ≤ limit=%d",
                        current_usage, estimated_tokens, self._tpm_limit,
                    )
                    return

                # Need to wait for the oldest entry to age out.
                oldest_ts = self._window[0][0]
                wait_sec = (oldest_ts + 60.0) - time.monotonic()
                if wait_sec <= 0:
                    # Already expired — purge and retry immediately.
                    self._purge()
                    continue

                logger.info(
                    "RateLimitManager: pacing — usage=%d, limit=%d, "
                    "requested=%d — waiting %.1fs",
                    current_usage, self._tpm_limit, estimated_tokens, wait_sec,
                )
                # Release the lock while sleeping so others can also check.
                lock.release()
                try:
                    await asyncio.sleep(wait_sec + 0.25)  # +0.25s safety margin
                finally:
                    await lock.acquire()

    # ── Private helpers ────────────────────────────────────────────────────

    async def _get_lock(self) -> asyncio.Lock:
        """
        Return (or lazily create) the asyncio.Lock.

        The lock must be created inside an event loop, which is why we delay
        creation until the first ``acquire()`` call rather than ``__init__``.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _purge(self) -> None:
        """Remove window entries older than 60 seconds."""
        cutoff = time.monotonic() - 60.0
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()


# ── Module-level singleton ─────────────────────────────────────────────────────
# Import and use this in provider code and Celery tasks.
# The tpm_limit is read once at import time from settings; restart the worker
# after changing LLM_TPM_LIMIT in .env.

def _build_singleton() -> RateLimitManager:
    try:
        from app.core.config import settings
        limit = int(getattr(settings, "LLM_TPM_LIMIT", 12_000))
    except Exception:
        limit = 12_000
    return RateLimitManager(tpm_limit=limit)


rate_limit_manager: RateLimitManager = _build_singleton()
