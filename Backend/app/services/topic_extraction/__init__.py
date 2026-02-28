"""topic_extraction package — pluggable architecture for topic discovery."""
from app.services.topic_extraction.base import (
    CourseExtractionMeta,
    ExtractedTopic,
    TopicExtractionResult,
    TopicExtractor,
)
from app.services.topic_extraction.orchestrator import TopicExtractionOrchestrator

__all__ = [
    "CourseExtractionMeta",
    "ExtractedTopic",
    "TopicExtractionResult",
    "TopicExtractor",
    "TopicExtractionOrchestrator",
]
