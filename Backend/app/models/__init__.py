"""
Models package.

Importing this package registers all ORM models on Base.metadata, which is
required for Alembic autogenerate to detect schema changes.

Add each new model module here as it is created.
"""

from app.models.course import Course                                    # noqa: F401
from app.models.document import Document, DocumentStatus                # noqa: F401
from app.models.chunk import Chunk                                      # noqa: F401
from app.models.topic import Topic, TopicChunkMap                      # noqa: F401
from app.models.question import (                                       # noqa: F401
    QuestionSet,
    QuestionSetMode,
    Question,
    QuestionType,
    Difficulty,
    BloomLevel,
    QuestionStatus,
    McqOption,
    QuestionSource,
    QuestionValidation,
)
from app.models.job import Job, JobStatus, JobType                      # noqa: F401
from app.models.exam import ExamBlueprint, Exam, ExamQuestion           # noqa: F401
from app.models.export import Export, ExportType, ExportStatus          # noqa: F401

__all__ = [
    # core
    "Course",
    "Document",
    "DocumentStatus",
    # chunks / topics
    "Chunk",
    "Topic",
    "TopicChunkMap",
    # questions
    "QuestionSet",
    "QuestionSetMode",
    "Question",
    "QuestionType",
    "Difficulty",
    "BloomLevel",
    "QuestionStatus",
    "McqOption",
    "QuestionSource",
    "QuestionValidation",
    # jobs
    "Job",
    "JobStatus",
    "JobType",
    # exam
    "ExamBlueprint",
    "Exam",
    "ExamQuestion",
    # exports
    "Export",
    "ExportType",
    "ExportStatus",
]
