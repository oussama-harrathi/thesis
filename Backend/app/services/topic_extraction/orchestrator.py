"""
TopicExtractionOrchestrator - runs all extractors, scores them, and persists
the best result.

Selection now considers both structural confidence and topic granularity so a
coarse PDF outline cannot automatically beat a better slide/layout result.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.topic import Topic, TopicChunkMap
from app.services.topic_extraction.base import (
    LEVEL_CHAPTER,
    LEVEL_PART,
    LEVEL_SECTION,
    LEVEL_SUBSECTION,
    LOW_CONFIDENCE_THRESHOLD,
    METHOD_EMBEDDING_CLUSTERS,
    METHOD_LAYOUT_HEADINGS,
    METHOD_PDF_OUTLINE,
    METHOD_REGEX_HEADINGS,
    METHOD_SLIDE_TITLES,
    SANITY_MAX_TOPICS,
    SANITY_MIN_COVERAGE,
    SANITY_MIN_TOPICS,
    CourseExtractionMeta,
    ExtractedTopic,
    TopicExtractionResult,
)
from app.services.topic_extraction.chunk_mapper import TopicChunkMapper
from app.services.topic_extraction.extractors.embedding_cluster import EmbeddingClusterExtractor
from app.services.topic_extraction.extractors.layout_heading import LayoutHeadingExtractor
from app.services.topic_extraction.extractors.pdf_outline import PdfOutlineTocExtractor
from app.services.topic_extraction.extractors.regex_heading import RegexHeadingExtractor
from app.services.topic_extraction.extractors.slide_title import SlideTitleExtractor
from app.services.topic_extraction.post_processor import TopicPostProcessor

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_COARSE_AVG_PAGES_PER_TOPIC = 4.5
_MIN_TOPICS_FOR_LONG_DOC = 8
_LONG_DOC_PAGE_THRESHOLD = 20
_MAX_AVG_TITLE_WORDS = 9.0
_SHORT_OUTLINE_TITLE_WORDS = 4.5
_STRUCTURAL_PRIOR = {
    METHOD_PDF_OUTLINE: 0.10,
    METHOD_SLIDE_TITLES: 0.12,
    METHOD_LAYOUT_HEADINGS: 0.08,
    METHOD_REGEX_HEADINGS: 0.06,
    METHOD_EMBEDDING_CLUSTERS: 0.03,
}

# Module-level cache: str(course_id) -> CourseExtractionMeta
_meta_cache: dict[str, CourseExtractionMeta] = {}


def get_extraction_meta(course_id: Any) -> CourseExtractionMeta | None:
    """Return the last extraction metadata for *course_id*, or None."""
    return _meta_cache.get(str(course_id))


@dataclass
class GranularityAssessment:
    topic_count: int
    total_pages: int
    average_pages_per_topic: float
    average_title_words: float
    is_flat_outline: bool
    is_low_confidence: bool
    reasons: list[str]


class TopicExtractionOrchestrator:
    """Coordinates all extraction strategies and persists the winning result."""

    def __init__(self, embedding_service: Any | None = None) -> None:
        self._extractors = [
            PdfOutlineTocExtractor(),
            SlideTitleExtractor(),
            LayoutHeadingExtractor(),
            RegexHeadingExtractor(),
            EmbeddingClusterExtractor(),
        ]
        self._post_processor = TopicPostProcessor()
        self._chunk_mapper = TopicChunkMapper(embedding_service)

    def extract_and_save(
        self,
        db: Session,
        course_id: Any,
        chunks: list[Any],
        file_path: str,
    ) -> tuple[list[Topic], CourseExtractionMeta]:
        """
        Full pipeline:
          1. Run all extractors and score them with sanity + granularity checks
          2. Post-process (normalize, deduplicate, filter noise)
          3. Persist Topic rows with hierarchy
          4. Build and persist TopicChunkMap rows
          5. Compute coverage scores + CourseExtractionMeta
          6. Cache meta and return (topics, meta)
        """
        total_chunks = max(1, len(chunks))
        total_pages = _estimate_total_pages(chunks)

        best: TopicExtractionResult | None = None
        best_score = -1.0
        best_passes_sanity = False
        best_granularity: GranularityAssessment | None = None

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
            granularity = _assess_granularity(result, total_pages)
            passes_sanity = (
                usable
                and (est_coverage >= SANITY_MIN_COVERAGE or total_pages == 0)
                and not granularity.is_low_confidence
            )
            score = _score_result(
                result=result,
                usable=usable,
                passes_sanity=passes_sanity,
                granularity=granularity,
            )

            result.debug_info = {
                **result.debug_info,
                "estimated_coverage": round(est_coverage, 4),
                "granularity": _granularity_debug_dict(granularity),
                "passes_sanity": passes_sanity,
                "selection_score": round(score, 4),
            }

            logger.info(
                "Extractor '%s': n=%d conf=%.2f cov=%.2f granularity_low=%s reasons=%s score=%.3f",
                extractor.name,
                len(result.topics),
                result.overall_confidence,
                est_coverage,
                granularity.is_low_confidence,
                granularity.reasons,
                score,
            )

            if score > best_score:
                best_score = score
                best = result
                best_passes_sanity = passes_sanity
                best_granularity = granularity

        def _empty_meta(reason: str) -> CourseExtractionMeta:
            meta = CourseExtractionMeta(
                chosen_method=best.method if best else "NONE",
                overall_confidence=best.overall_confidence if best else 0.0,
                is_low_confidence=True,
                coverage_ratio=0.0,
                topic_count=0,
                debug_info={
                    "reason": reason,
                    **(best.debug_info if best else {}),
                },
            )
            _meta_cache[str(course_id)] = meta
            return meta

        if best is None or not best.topics:
            logger.warning(
                "Orchestrator: all extractors returned 0 topics for course %s",
                course_id,
            )
            return [], _empty_meta("no extractor produced topics")

        logger.info(
            "Orchestrator picked '%s' (score=%.3f, n=%d, sanity=%s, granularity_low=%s)",
            best.method,
            best_score,
            len(best.topics),
            best_passes_sanity,
            best_granularity.is_low_confidence if best_granularity else None,
        )

        clean_topics = self._post_processor.process(best.topics)
        if not clean_topics:
            logger.warning(
                "Orchestrator: post-processor eliminated all topics for course %s",
                course_id,
            )
            return [], _empty_meta("post_processor eliminated all topics")

        source_tag = _method_to_source(best.method)
        ext_to_orm: dict[int, Topic] = {}

        for i, extracted_topic in enumerate(clean_topics):
            row = Topic(
                course_id=course_id,
                name=extracted_topic.title,
                is_auto_extracted=True,
                source=source_tag,
                level=extracted_topic.level,
                coverage_score=None,
                parent_topic_id=None,
            )
            db.add(row)
            ext_to_orm[i] = row

        db.flush()

        title_to_orm = {
            extracted_topic.title: ext_to_orm[i]
            for i, extracted_topic in enumerate(clean_topics)
        }
        for i, extracted_topic in enumerate(clean_topics):
            if extracted_topic.parent_ref:
                parent_row = title_to_orm.get(extracted_topic.parent_ref)
                if parent_row is not None:
                    ext_to_orm[i].parent_topic_id = parent_row.id
            elif extracted_topic.level in (LEVEL_SECTION, LEVEL_SUBSECTION):
                for j in range(i - 1, -1, -1):
                    prev = clean_topics[j]
                    if prev.level == LEVEL_CHAPTER and extracted_topic.level == LEVEL_SECTION:
                        ext_to_orm[i].parent_topic_id = ext_to_orm[j].id
                        break
                    if prev.level == LEVEL_SECTION and extracted_topic.level == LEVEL_SUBSECTION:
                        ext_to_orm[i].parent_topic_id = ext_to_orm[j].id
                        break

        db.flush()
        topic_rows = list(ext_to_orm.values())
        for row in topic_rows:
            db.refresh(row)

        for i, row in ext_to_orm.items():
            extracted_topic = clean_topics[i]
            row.page_start = extracted_topic.start_page  # type: ignore[attr-defined]
            row.page_end = extracted_topic.end_page  # type: ignore[attr-defined]

        mappings = self._chunk_mapper.build_mappings(topic_rows, chunks, clean_topics)
        map_rows = [TopicChunkMap(**mapping) for mapping in mappings]
        for map_row in map_rows:
            db.add(map_row)
        db.flush()

        chunk_ids_per_topic: dict[Any, set[Any]] = {}
        for map_row in map_rows:
            chunk_ids_per_topic.setdefault(map_row.topic_id, set()).add(map_row.chunk_id)

        all_covered: set[Any] = set()
        for row in topic_rows:
            mapped = chunk_ids_per_topic.get(row.id, set())
            row.coverage_score = round(len(mapped) / total_chunks, 4)
            all_covered.update(mapped)

        db.flush()
        for row in topic_rows:
            db.refresh(row)

        actual_coverage = round(len(all_covered) / total_chunks, 4)
        high_conf = (
            best.overall_confidence >= 0.75
            and best_passes_sanity
            and not (best_granularity.is_low_confidence if best_granularity else False)
        )
        is_low = (
            best.overall_confidence < LOW_CONFIDENCE_THRESHOLD
            or (not best_passes_sanity and actual_coverage < SANITY_MIN_COVERAGE)
            or (best_granularity.is_low_confidence if best_granularity else False)
        ) and not high_conf

        meta = CourseExtractionMeta(
            chosen_method=best.method,
            overall_confidence=round(best.overall_confidence, 4),
            is_low_confidence=is_low,
            coverage_ratio=actual_coverage,
            topic_count=len(topic_rows),
            debug_info={
                **best.debug_info,
                "source_tag": source_tag,
                "total_chunks": total_chunks,
                "covered_chunks": len(all_covered),
            },
        )
        _meta_cache[str(course_id)] = meta

        logger.info(
            "Orchestrator: %d topics, coverage=%.2f, conf=%.2f, low=%s for course %s",
            len(topic_rows),
            actual_coverage,
            best.overall_confidence,
            is_low,
            course_id,
        )
        return topic_rows, meta


def _method_to_source(method: str) -> str:
    return {
        METHOD_PDF_OUTLINE: "TOC",
        METHOD_SLIDE_TITLES: "AUTO",
        METHOD_LAYOUT_HEADINGS: "AUTO",
        METHOD_REGEX_HEADINGS: "AUTO",
        METHOD_EMBEDDING_CLUSTERS: "AUTO",
    }.get(method, "AUTO")


def _estimate_total_pages(chunks: list[Any]) -> int:
    """Guess total page count from chunk.page_start values."""
    page_values = [
        page
        for chunk in chunks
        if (page := getattr(chunk, "page_start", None)) is not None
    ]
    return max(page_values) if page_values else 0


def _estimate_coverage(topics: list[ExtractedTopic], total_pages: int) -> float:
    """Proxy for coverage ratio before chunk mapping."""
    if total_pages == 0:
        return 1.0

    covered: set[int] = set()
    has_pages = False
    for topic in topics:
        if topic.start_page is not None:
            has_pages = True
            end_page = topic.end_page if topic.end_page is not None else topic.start_page
            covered.update(range(topic.start_page, end_page + 1))

    if not has_pages:
        return min(1.0, len(topics) / max(1, total_pages / 10))

    return min(1.0, len(covered) / total_pages)


def _assess_granularity(
    result: TopicExtractionResult,
    total_pages: int,
) -> GranularityAssessment:
    topic_count = len(result.topics)
    average_pages_per_topic = (
        round(total_pages / max(1, topic_count), 4)
        if total_pages > 0
        else 0.0
    )
    average_title_words = round(
        sum(_title_word_count(topic.title) for topic in result.topics) / max(1, topic_count),
        4,
    )
    levels = {topic.level for topic in result.topics if topic.level}
    is_flat_outline = (
        result.method == METHOD_PDF_OUTLINE
        and bool(levels)
        and len(levels) == 1
        and levels.issubset({LEVEL_CHAPTER, LEVEL_PART})
    )

    reasons: list[str] = []
    if total_pages >= _LONG_DOC_PAGE_THRESHOLD and topic_count < _MIN_TOPICS_FOR_LONG_DOC:
        reasons.append("too_few_topics_for_document_length")
    if average_pages_per_topic > _COARSE_AVG_PAGES_PER_TOPIC:
        reasons.append("topics_too_broad")
    if average_title_words > _MAX_AVG_TITLE_WORDS:
        reasons.append("titles_too_long_like_prose")
    if (
        is_flat_outline
        and total_pages >= _LONG_DOC_PAGE_THRESHOLD
        and average_title_words <= _SHORT_OUTLINE_TITLE_WORDS
    ):
        reasons.append("flat_outline_short_titles")

    return GranularityAssessment(
        topic_count=topic_count,
        total_pages=total_pages,
        average_pages_per_topic=average_pages_per_topic,
        average_title_words=average_title_words,
        is_flat_outline=is_flat_outline,
        is_low_confidence=bool(reasons),
        reasons=reasons,
    )


def _score_result(
    *,
    result: TopicExtractionResult,
    usable: bool,
    passes_sanity: bool,
    granularity: GranularityAssessment,
) -> float:
    granularity_mult = 1.0
    for reason in granularity.reasons:
        if reason == "flat_outline_short_titles":
            granularity_mult *= 0.35
        elif reason == "topics_too_broad":
            granularity_mult *= 0.55
        elif reason == "too_few_topics_for_document_length":
            granularity_mult *= 0.65
        elif reason == "titles_too_long_like_prose":
            granularity_mult *= 0.70

    sanity_mult = 1.25 if passes_sanity else (0.95 if usable else 0.65)
    count_bonus = min(1.0, len(result.topics) / 20.0) * 0.10
    structural_prior = _STRUCTURAL_PRIOR.get(result.method, 0.02)
    return result.overall_confidence * sanity_mult * granularity_mult + count_bonus + structural_prior


def _title_word_count(title: str) -> int:
    return len(_WORD_RE.findall(title or ""))


def _granularity_debug_dict(granularity: GranularityAssessment) -> dict[str, Any]:
    return {
        "topic_count": granularity.topic_count,
        "total_pages": granularity.total_pages,
        "average_pages_per_topic": granularity.average_pages_per_topic,
        "average_title_words": granularity.average_title_words,
        "is_flat_outline": granularity.is_flat_outline,
        "is_low_confidence": granularity.is_low_confidence,
        "reasons": granularity.reasons,
    }
