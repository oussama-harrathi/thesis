"""
TopicExtractionOrchestrator — runs extractors in priority order, picks the
best result with coverage-ratio + topic-count sanity checks, post-processes
topics, maps them to chunks, and persists everything to the database.

Extractor priority
──────────────────
1. PdfOutlineTocExtractor   (confidence ≥ 0.60 — most reliable)
2. LayoutHeadingExtractor   (confidence ≥ 0.35 — good for slides/notes)
3. RegexHeadingExtractor    (confidence ≥ 0.30 — broad fallback)
4. EmbeddingClusterExtractor (confidence ≥ 0.25 — last resort)

Sanity checks (configured in base.py):
  - SANITY_MIN_TOPICS ≤ topic_count ≤ SANITY_MAX_TOPICS
  - estimated coverage_ratio ≥ SANITY_MIN_COVERAGE

Returns (list[Topic], CourseExtractionMeta) — meta is also cached in
_meta_cache for the GET /topics endpoint to retrieve without a DB round-trip.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.topic import Topic, TopicChunkMap
from app.services.topic_extraction.base import (
    LEVEL_CHAPTER,
    LEVEL_SECTION,
    LEVEL_SUBSECTION,
    LOW_CONFIDENCE_THRESHOLD,
    SANITY_MIN_COVERAGE,
    SANITY_MIN_TOPICS,
    SANITY_MAX_TOPICS,
    CourseExtractionMeta,
    ExtractedTopic,
    TopicExtractionResult,
)
from app.services.topic_extraction.chunk_mapper import TopicChunkMapper
from app.services.topic_extraction.extractors.embedding_cluster import EmbeddingClusterExtractor
from app.services.topic_extraction.extractors.layout_heading import LayoutHeadingExtractor
from app.services.topic_extraction.extractors.pdf_outline import PdfOutlineTocExtractor
from app.services.topic_extraction.extractors.regex_heading import RegexHeadingExtractor
from app.services.topic_extraction.post_processor import TopicPostProcessor

logger = logging.getLogger(__name__)

# Module-level cache: str(course_id) → CourseExtractionMeta
# Lets the GET /topics endpoint return confidence data without a new DB table.
_meta_cache: dict[str, CourseExtractionMeta] = {}


def get_extraction_meta(course_id: Any) -> CourseExtractionMeta | None:
    """Return the last extraction metadata for *course_id*, or None."""
    return _meta_cache.get(str(course_id))


class TopicExtractionOrchestrator:
    """
    Coordinates all extraction strategies and persists the winning result.

    Usage (sync, for Celery workers / topic_extraction_service.py)::

        orch = TopicExtractionOrchestrator(embedding_service)
        topics, meta = orch.extract_and_save(db, course_id, chunks, file_path)
    """

    def __init__(self, embedding_service: Any | None = None) -> None:
        self._extractors = [
            PdfOutlineTocExtractor(),
            LayoutHeadingExtractor(),
            RegexHeadingExtractor(),
            EmbeddingClusterExtractor(),
        ]
        self._post_processor = TopicPostProcessor()
        self._chunk_mapper = TopicChunkMapper(embedding_service)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_and_save(
        self,
        db: Session,
        course_id: Any,
        chunks: list[Any],
        file_path: str,
    ) -> tuple[list[Topic], CourseExtractionMeta]:
        """
        Full pipeline:
          1. Run all extractors with sanity-checked selection
          2. Post-process (normalize, deduplicate, filter noise)
          3. Persist Topic rows with hierarchy
          4. Build & persist TopicChunkMap rows
          5. Compute coverage scores + CourseExtractionMeta
          6. Cache meta and return (topics, meta)
        """
        total_chunks = max(1, len(chunks))
        total_pages = _estimate_total_pages(chunks)

        # ── Step 1: run extractors with sanity checking ────────────
        best: TopicExtractionResult | None = None
        best_score: float = -1.0
        best_passes_sanity = False

        for extractor in self._extractors:
            try:
                result = extractor.extract(str(file_path), chunks=chunks)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Extractor '%s' raised: %s", extractor.name, exc)
                continue

            if not result.topics:
                logger.debug("Extractor '%s': 0 topics", extractor.name)
                continue

            usable = result.is_usable()
            est_coverage = _estimate_coverage(result.topics, total_pages)
            passes_sanity = (
                usable
                and (est_coverage >= SANITY_MIN_COVERAGE or total_pages == 0)
            )

            count_bonus = min(1.0, len(result.topics) / 20.0) * 0.10
            sanity_mult = 1.30 if passes_sanity else (1.00 if usable else 0.70)
            score = result.overall_confidence * sanity_mult + count_bonus

            logger.debug(
                "Extractor '%s': n=%d conf=%.2f usable=%s cov=%.2f passes=%s score=%.3f",
                extractor.name, len(result.topics), result.overall_confidence,
                usable, est_coverage, passes_sanity, score,
            )

            if score > best_score:
                best_score = score
                best = result
                best_passes_sanity = passes_sanity

            if passes_sanity and result.overall_confidence >= 0.75:
                logger.info(
                    "Extractor '%s' high-conf early-exit (%.2f, cov=%.2f)",
                    extractor.name, result.overall_confidence, est_coverage,
                )
                break

        def _empty_meta(reason: str) -> CourseExtractionMeta:
            m = CourseExtractionMeta(
                chosen_method=best.method if best else "NONE",
                overall_confidence=best.overall_confidence if best else 0.0,
                is_low_confidence=True,
                coverage_ratio=0.0,
                topic_count=0,
                debug_info={"reason": reason},
            )
            _meta_cache[str(course_id)] = m
            return m

        if best is None or not best.topics:
            logger.warning("Orchestrator: all extractors returned 0 topics for course %s", course_id)
            return [], _empty_meta("no extractor produced topics")

        logger.info(
            "Orchestrator picked '%s' (score=%.3f, n=%d, sanity=%s)",
            best.method, best_score, len(best.topics), best_passes_sanity,
        )

        # ── Step 2: post-process ───────────────────────────────────
        clean_topics = self._post_processor.process(best.topics)
        if not clean_topics:
            logger.warning("Orchestrator: post-processor eliminated all topics for course %s", course_id)
            return [], _empty_meta("post_processor eliminated all topics")

        # ── Step 3: persist Topic rows ────────────────────────────
        source_tag = _method_to_source(best.method)
        ext_to_orm: dict[int, Topic] = {}

        for i, et in enumerate(clean_topics):
            row = Topic(
                course_id=course_id,
                name=et.title,
                is_auto_extracted=True,
                source=source_tag,
                level=et.level,
                coverage_score=None,
                parent_topic_id=None,
            )
            db.add(row)
            ext_to_orm[i] = row

        db.flush()

        title_to_orm: dict[str, Topic] = {
            et.title: ext_to_orm[i] for i, et in enumerate(clean_topics)
        }
        for i, et in enumerate(clean_topics):
            if et.parent_ref:
                parent_row = title_to_orm.get(et.parent_ref)
                if parent_row is not None:
                    ext_to_orm[i].parent_topic_id = parent_row.id
            elif et.level in (LEVEL_SECTION, LEVEL_SUBSECTION):
                for j in range(i - 1, -1, -1):
                    prev_et = clean_topics[j]
                    if prev_et.level == LEVEL_CHAPTER and et.level == LEVEL_SECTION:
                        ext_to_orm[i].parent_topic_id = ext_to_orm[j].id
                        break
                    if prev_et.level == LEVEL_SECTION and et.level == LEVEL_SUBSECTION:
                        ext_to_orm[i].parent_topic_id = ext_to_orm[j].id
                        break

        db.flush()
        topic_rows = list(ext_to_orm.values())
        for row in topic_rows:
            db.refresh(row)

        # ── Step 4: build & persist TopicChunkMap rows ────────────
        for i, row in ext_to_orm.items():
            et = clean_topics[i]
            row.page_start = et.start_page   # type: ignore[attr-defined]
            row.page_end = et.end_page       # type: ignore[attr-defined]

        mappings = self._chunk_mapper.build_mappings(topic_rows, chunks, clean_topics)
        map_rows = [TopicChunkMap(**m) for m in mappings]
        for mr in map_rows:
            db.add(mr)
        db.flush()

        # ── Step 5: coverage scores + meta ─────────────────────────
        chunk_ids_per_topic: dict[Any, set[Any]] = {}
        for mr in map_rows:
            chunk_ids_per_topic.setdefault(mr.topic_id, set()).add(mr.chunk_id)

        all_covered: set[Any] = set()
        for row in topic_rows:
            mapped = chunk_ids_per_topic.get(row.id, set())
            row.coverage_score = round(len(mapped) / total_chunks, 4)
            all_covered.update(mapped)

        db.flush()
        for row in topic_rows:
            db.refresh(row)

        actual_coverage = round(len(all_covered) / total_chunks, 4)
        is_low = (
            best.overall_confidence < LOW_CONFIDENCE_THRESHOLD
            or not best_passes_sanity
            or actual_coverage < SANITY_MIN_COVERAGE
        )
        meta = CourseExtractionMeta(
            chosen_method=best.method,
            overall_confidence=round(best.overall_confidence, 4),
            is_low_confidence=is_low,
            coverage_ratio=actual_coverage,
            topic_count=len(topic_rows),
            debug_info={
                **best.debug_info,
                "passes_sanity": best_passes_sanity,
                "source_tag": source_tag,
                "total_chunks": total_chunks,
                "covered_chunks": len(all_covered),
            },
        )
        _meta_cache[str(course_id)] = meta

        logger.info(
            "Orchestrator: %d topics, coverage=%.2f, conf=%.2f, low=%s for course %s",
            len(topic_rows), actual_coverage, best.overall_confidence, is_low, course_id,
        )
        return topic_rows, meta


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _method_to_source(method: str) -> str:
    from app.services.topic_extraction.base import (
        METHOD_EMBEDDING_CLUSTERS,
        METHOD_LAYOUT_HEADINGS,
        METHOD_PDF_OUTLINE,
        METHOD_REGEX_HEADINGS,
    )
    return {
        METHOD_PDF_OUTLINE: "TOC",
        METHOD_LAYOUT_HEADINGS: "AUTO",
        METHOD_REGEX_HEADINGS: "AUTO",
        METHOD_EMBEDDING_CLUSTERS: "AUTO",
    }.get(method, "AUTO")


def _estimate_total_pages(chunks: list[Any]) -> int:
    """Guess total page count from chunk page_start values."""
    page_values: list[int] = [
        p
        for ch in chunks
        if (p := getattr(ch, "page_start", None)) is not None
    ]
    return max(page_values) if page_values else 0


def _estimate_coverage(topics: list[ExtractedTopic], total_pages: int) -> float:
    """
    Proxy for coverage_ratio before chunk mapping.
    Uses page ranges when available; falls back to topic-count heuristic.
    """
    if total_pages == 0:
        return 1.0

    covered: set[int] = set()
    has_pages = False
    for t in topics:
        if t.start_page is not None:
            has_pages = True
            end = t.end_page if t.end_page is not None else t.start_page
            covered.update(range(t.start_page, end + 1))

    if not has_pages:
        return min(1.0, len(topics) / max(1, total_pages / 10))

    return min(1.0, len(covered) / total_pages)
