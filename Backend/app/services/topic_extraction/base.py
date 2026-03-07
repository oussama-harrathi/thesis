"""
Base protocol and data structures for the pluggable topic-extraction system.

Every extractor must implement the `TopicExtractor` protocol.  Results are
returned as `TopicExtractionResult` containing a list of `ExtractedTopic`
objects that later pass through post-processing (normalisation, noise
filtering, deduplication) before being persisted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ── Level constants ───────────────────────────────────────────────────────────

LEVEL_PART       = "PART"
LEVEL_CHAPTER    = "CHAPTER"
LEVEL_SECTION    = "SECTION"
LEVEL_SUBSECTION = "SUBSECTION"
LEVEL_HEADING    = "HEADING"   # generic heading (layout / regex extractors)
LEVEL_CLUSTER    = "CLUSTER"   # embedding-cluster extractor

# ── Method constants ─────────────────────────────────────────────────────────

METHOD_PDF_OUTLINE         = "PDF_OUTLINE"
METHOD_LAYOUT_HEADINGS     = "LAYOUT_HEADINGS"
METHOD_REGEX_HEADINGS      = "REGEX_HEADINGS"
METHOD_EMBEDDING_CLUSTERS  = "EMBEDDING_CLUSTERS"

# ── Sanity-check thresholds (configurable) ────────────────────────────────────

SANITY_MIN_TOPICS:        int   = 3    # single-lecture PDFs may have fewer sections
SANITY_MAX_TOPICS:        int   = 50
SANITY_MIN_COVERAGE:      float = 0.20   # fraction of chunks covered across all topics
LOW_CONFIDENCE_THRESHOLD: float = 0.45   # overall_confidence below this → is_low_confidence


# ── Core data structures ──────────────────────────────────────────────────────

@dataclass
class ExtractedTopic:
    """A single candidate topic produced by an extractor."""

    title: str
    level: str                   # one of the LEVEL_* constants
    confidence: float            # 0–1, extractor's own estimate

    # Page anchors (1-based, inclusive); None when not available
    start_page: int | None = None
    end_page:   int | None = None

    # Temporary reference (normalised title of parent within same result)
    parent_ref: str | None = None

    # Extra extractor-specific metadata
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class TopicExtractionResult:
    """Full result from one extractor pass."""

    topics: list[ExtractedTopic]
    method: str                  # one of the METHOD_* constants
    overall_confidence: float    # aggregate confidence for the whole result

    # Diagnostics shown in API debug responses and logs
    debug_info: dict[str, Any] = field(default_factory=dict)

    # Convenience
    @property
    def topic_count(self) -> int:
        return len(self.topics)

    def is_usable(
        self,
        min_topics: int = SANITY_MIN_TOPICS,
        max_topics: int = SANITY_MAX_TOPICS,
    ) -> bool:
        """True when the result has topics in the configured sane range."""
        return min_topics <= self.topic_count <= max_topics


@dataclass
class CourseExtractionMeta:
    """
    Course-level metadata about the topic extraction run.
    Returned alongside the topic list so the UI can surface confidence warnings.
    """
    chosen_method: str
    overall_confidence: float
    is_low_confidence: bool
    coverage_ratio: float        # fraction of chunks covered by at least one topic
    topic_count: int
    debug_info: dict[str, Any] = field(default_factory=dict)


# ── Extractor protocol ────────────────────────────────────────────────────────

@runtime_checkable
class TopicExtractor(Protocol):
    """Interface every extractor must satisfy."""

    @property
    def name(self) -> str:
        """Human-readable extractor name (e.g. 'pdf_outline')."""
        ...

    def extract(
        self,
        file_path: str,
        *,
        chunks: list[Any] | None = None,
    ) -> TopicExtractionResult:
        """
        Run extraction and return a result.

        Parameters
        ----------
        file_path : Absolute path to the PDF file.
        chunks    : Optional pre-loaded Chunk ORM rows (used by
                    EmbeddingClusterExtractor).
        """
        ...
