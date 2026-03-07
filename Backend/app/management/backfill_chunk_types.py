"""
Backfill Chunk Types
════════════════════
One-shot maintenance script that classifies every existing Chunk row that has
``chunk_type = 'instructional'`` AND ``chunk_type_score = 0``.  This covers
all chunks that were persisted *before* the f1a2b3c4d5e6 migration was applied
(the migration uses a server_default of 'instructional' / '0', so those rows
need an explicit re-classification pass).

Safe to run multiple times — only rows that still have the sentinel values
(type='instructional', score=0) are touched.  Rows that were already
classified are left untouched.

Usage (from the Backend/ directory, with DATABASE_URL set):
    python -m app.management.backfill_chunk_types
    python -m app.management.backfill_chunk_types --batch-size 200 --dry-run
    python -m app.management.backfill_chunk_types --limit 1000  # partial run

Options
───────
--batch-size INT    Rows processed per DB transaction (default: 500)
--dry-run           Classify and print stats but do not write to DB.
--limit INT         Stop after processing this many rows (useful for testing).
--verbose           Print one line per changed row.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Iterator

from sqlalchemy import select, update
from sqlalchemy.orm import Session

# Bootstrap sys.path so the script can be run as __main__ from Backend/.
if __name__ == "__main__":
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from app.models.chunk import Chunk
from app.utils.chunk_classifier import ChunkType, classify_chunk_type
from app.workers.db import get_sync_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_chunk_types")

# Only rows that have NEVER been classified are candidates.
_SENTINEL_TYPE  = ChunkType.instructional
_SENTINEL_SCORE = 0


def _iter_unclassified_batches(
    db: Session,
    batch_size: int,
    limit: int | None,
) -> Iterator[list[Chunk]]:
    """
    Yield batches of Chunk rows whose classification is still at the sentinel
    (instructional / score=0 — i.e. never been explicitly classified).
    """
    offset = 0
    fetched_total = 0

    while True:
        remaining = None if limit is None else (limit - fetched_total)
        if remaining is not None and remaining <= 0:
            break

        fetch = batch_size
        if remaining is not None:
            fetch = min(fetch, remaining)

        rows = db.execute(
            select(Chunk)
            .where(Chunk.chunk_type == _SENTINEL_TYPE)
            .where(Chunk.chunk_type_score == _SENTINEL_SCORE)
            .order_by(Chunk.created_at)
            .limit(fetch)
            .offset(offset)
        ).scalars().all()

        if not rows:
            break

        yield list(rows)
        fetched_total += len(rows)
        offset += len(rows)


def run_backfill(
    batch_size: int = 500,
    dry_run: bool = False,
    limit: int | None = None,
    verbose: bool = False,
) -> dict[str, int]:
    """
    Classify all unclassified Chunk rows.

    Returns a dict with stats: total_processed, changed, skipped.
    """
    stats: dict[str, int] = {
        "total_processed": 0,
        "changed": 0,
        "skipped": 0,
    }
    type_counts: dict[str, int] = {t.value: 0 for t in ChunkType}

    start_time = time.monotonic()

    with get_sync_db() as db:
        for batch in _iter_unclassified_batches(db, batch_size, limit):
            changes: list[tuple[Chunk, ChunkType, int]] = []

            for chunk in batch:
                ct_type, ct_score, ct_rules = classify_chunk_type(chunk.content)
                stats["total_processed"] += 1
                type_counts[ct_type.value] += 1

                if ct_type == _SENTINEL_TYPE and ct_score == _SENTINEL_SCORE:
                    # Truly instructional — nothing to update.
                    stats["skipped"] += 1
                    continue

                changes.append((chunk, ct_type, ct_score))
                stats["changed"] += 1

                if verbose:
                    logger.info(
                        "  chunk %s → %s (score=%d, rules=%s)",
                        chunk.id,
                        ct_type.value,
                        ct_score,
                        ct_rules[:5],
                    )

            if changes and not dry_run:
                for chunk, ct_type, ct_score in changes:
                    chunk.chunk_type = ct_type
                    chunk.chunk_type_score = ct_score
                db.commit()
                logger.info(
                    "Committed batch: %d changed of %d processed so far",
                    stats["changed"], stats["total_processed"],
                )

    elapsed = time.monotonic() - start_time
    logger.info(
        "Backfill %scomplete in %.1fs — processed=%d  changed=%d  skipped=%d",
        "[DRY RUN] " if dry_run else "",
        elapsed,
        stats["total_processed"],
        stats["changed"],
        stats["skipped"],
    )
    logger.info("Type distribution: %s", type_counts)
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill chunk_type / chunk_type_score for existing Chunk rows."
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="Rows per transaction (default: 500)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Classify but do not write to DB",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop after this many rows",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print one line per changed row",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_backfill(
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        limit=args.limit,
        verbose=args.verbose,
    )
