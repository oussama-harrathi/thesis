import os
import uuid
from types import SimpleNamespace

import pytest

os.environ["DEBUG"] = "true"

from app.models.topic import Topic
from app.services.question_generation_service import QuestionGenerationService
from app.services.topic_extraction.base import (
    LEVEL_CHAPTER,
    LEVEL_SECTION,
    METHOD_PDF_OUTLINE,
    METHOD_SLIDE_TITLES,
    METHOD_LAYOUT_HEADINGS,
    METHOD_REGEX_HEADINGS,
    ExtractedTopic,
    TopicExtractionResult,
)
from app.services.topic_extraction.extractors.layout_heading import LayoutHeadingExtractor
from app.services.topic_extraction.extractors.regex_heading import RegexHeadingExtractor
from app.services.topic_extraction.extractors.slide_title import SlideTitleExtractor
from app.services.topic_extraction.orchestrator import TopicExtractionOrchestrator


class FakePage:
    def __init__(self, text: str, blocks: list[dict], *, height: float = 800.0):
        self._text = text
        self._dict = {"blocks": blocks}
        self.rect = SimpleNamespace(height=height)

    def get_text(self, mode: str, flags=None):  # noqa: ANN001
        if mode == "text":
            return self._text
        if mode == "dict":
            return self._dict
        raise ValueError(mode)


class FakeDoc:
    def __init__(self, pages: list[FakePage]):
        self._pages = pages

    def __len__(self) -> int:
        return len(self._pages)

    def load_page(self, idx: int) -> FakePage:
        return self._pages[idx]

    def close(self) -> None:
        return None


def _line(text: str, *, size: float, y0: float, y1: float | None = None, flags: int = 0) -> dict:
    return {
        "bbox": (0.0, y0, 500.0, y1 if y1 is not None else y0 + 20.0),
        "spans": [
            {
                "text": text,
                "size": size,
                "flags": flags,
            }
        ],
    }


def _page_from_lines(lines: list[dict]) -> FakePage:
    text = "\n".join(
        span["text"]
        for line in lines
        for span in line["spans"]
    )
    return FakePage(text, [{"type": 0, "lines": lines}])


class _FakeExtractor:
    def __init__(self, name: str, result: TopicExtractionResult) -> None:
        self.name = name
        self._result = result

    def extract(self, file_path: str, *, chunks=None):  # noqa: ANN001
        return self._result


class _FakePostProcessor:
    def process(self, topics: list[ExtractedTopic]) -> list[ExtractedTopic]:
        return topics


class _FakeChunkMapper:
    def build_mappings(self, topics, chunks, extracted_topics):  # noqa: ANN001
        return []


class _FakeDB:
    def add(self, obj) -> None:  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    def flush(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def test_orchestrator_rejects_coarse_outline_and_picks_finer_result() -> None:
    coarse_outline = TopicExtractionResult(
        topics=[
            ExtractedTopic("Introduction", LEVEL_CHAPTER, 0.95, 3, 4),
            ExtractedTopic("Qubits and States", LEVEL_CHAPTER, 0.95, 5, 10),
            ExtractedTopic("Gates and Entanglement", LEVEL_CHAPTER, 0.95, 11, 24),
            ExtractedTopic("Noise and Hardware", LEVEL_CHAPTER, 0.95, 25, 30),
            ExtractedTopic("Applications and Conclusion", LEVEL_CHAPTER, 0.95, 31, 33),
        ],
        method=METHOD_PDF_OUTLINE,
        overall_confidence=0.95,
        debug_info={},
    )
    slide_topics = TopicExtractionResult(
        topics=[
            ExtractedTopic(f"Topic {i}", LEVEL_SECTION, 0.82, i, i)
            for i in range(1, 13)
        ],
        method=METHOD_SLIDE_TITLES,
        overall_confidence=0.82,
        debug_info={},
    )

    orchestrator = TopicExtractionOrchestrator()
    orchestrator._extractors = [
        _FakeExtractor("outline", coarse_outline),
        _FakeExtractor("slide", slide_topics),
    ]
    orchestrator._post_processor = _FakePostProcessor()
    orchestrator._chunk_mapper = _FakeChunkMapper()

    chunks = [
        SimpleNamespace(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=i,
            page_start=i,
            content=f"Chunk {i}",
        )
        for i in range(1, 34)
    ]

    topics, meta = orchestrator.extract_and_save(
        db=_FakeDB(),
        course_id=uuid.uuid4(),
        chunks=chunks,
        file_path="dummy.pdf",
    )

    assert meta.chosen_method == METHOD_SLIDE_TITLES
    assert len(topics) == 12


def test_slide_title_extractor_deduplicates_adjacent_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = []
    for title in [
        "Qubits and States",
        "Qubits and States",
        "Superposition",
        "Superposition",
        "Entanglement",
        "Entanglement",
    ]:
        lines = [
            _line(title, size=24.0, y0=24.0),
            _line("Short body text for the slide", size=12.0, y0=220.0),
            _line("Another short supporting line", size=12.0, y0=248.0),
        ]
        pages.append(_page_from_lines(lines))

    monkeypatch.setattr(
        "app.services.topic_extraction.extractors.slide_title.fitz.open",
        lambda _: FakeDoc(pages),
    )

    result = SlideTitleExtractor().extract("slides.pdf")

    assert result.method == METHOD_SLIDE_TITLES
    assert [topic.title for topic in result.topics] == [
        "Qubits and States",
        "Superposition",
        "Entanglement",
    ]
    assert [(topic.start_page, topic.end_page) for topic in result.topics] == [
        (1, 2),
        (3, 4),
        (5, 6),
    ]


def test_layout_heading_extractor_filters_sentence_like_body_text(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _page_from_lines(
        [
            _line("Superposition and Measurement", size=24.0, y0=24.0),
            _line("regular body text", size=12.0, y0=120.0),
            _line(
                "This sentence should never become a heading because it is clearly prose and far too long.",
                size=18.0,
                y0=250.0,
            ),
        ]
    )
    monkeypatch.setattr(
        "app.services.topic_extraction.extractors.layout_heading.fitz.open",
        lambda _: FakeDoc([page]),
    )

    result = LayoutHeadingExtractor().extract("layout.pdf")

    assert result.method == METHOD_LAYOUT_HEADINGS
    assert [topic.title for topic in result.topics] == ["Superposition and Measurement"]


def test_regex_heading_extractor_supports_title_case_headings(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "\n".join(
        [
            "",
            "Quantum Gates And Entanglement",
            "",
            "This is ordinary body text that should not be matched as a heading.",
        ]
    )
    page = FakePage(text, [])
    monkeypatch.setattr(
        "app.services.topic_extraction.extractors.regex_heading.fitz.open",
        lambda _: FakeDoc([page]),
    )

    result = RegexHeadingExtractor().extract("regex.pdf")

    assert result.method == METHOD_REGEX_HEADINGS
    assert any(topic.title == "Quantum Gates And Entanglement" for topic in result.topics)


@pytest.mark.asyncio
async def test_question_generation_bypasses_coarse_toc_topics() -> None:
    coarse_topic = Topic(
        course_id=uuid.uuid4(),
        name="Qubits and States",
        is_auto_extracted=True,
        source="TOC",
        level="CHAPTER",
        coverage_score=0.35,
    )
    coarse_topic.id = uuid.uuid4()

    class FakeResult:
        def first(self):
            return (coarse_topic, 9)

    class FakeDB:
        async def execute(self, stmt):  # noqa: ANN001
            return FakeResult()

    fake_provider = SimpleNamespace(provider_name="mock")
    service = QuestionGenerationService(
        provider=fake_provider,
        retrieval_service=SimpleNamespace(),
        diversity_service=SimpleNamespace(),
    )

    effective_topic_id, reason = await service._resolve_topic_focus(
        FakeDB(),
        course_id=coarse_topic.course_id,
        topic_id=coarse_topic.id,
        topic_name=coarse_topic.name,
        difficulty="medium",
    )

    assert effective_topic_id is None
    assert reason is not None
    assert "coarse TOC bucket" in reason
