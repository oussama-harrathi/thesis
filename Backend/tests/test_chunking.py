"""
Unit tests for app.services.chunking_service

Covers pure functions (split_into_sentences, build_chunks, _hard_split)
and the ChunkingService wrapper.  No database or LLM calls are made.
"""
import pytest

from app.services.chunking_service import (
    ChunkingService,
    TextChunk,
    _hard_split,
    build_chunks,
    split_into_sentences,
)


# ── split_into_sentences ──────────────────────────────────────────────────────

class TestSplitIntoSentences:
    def test_empty_string_returns_empty(self):
        assert split_into_sentences("") == []

    def test_whitespace_only_returns_empty(self):
        assert split_into_sentences("   \n\n  ") == []

    def test_single_sentence(self):
        result = split_into_sentences("Hello world.")
        assert result == ["Hello world."]

    def test_two_sentences_in_paragraph(self):
        result = split_into_sentences("Hello world. How are you?")
        assert len(result) == 2
        assert any("Hello" in s for s in result)
        assert any("How" in s for s in result)

    def test_two_paragraphs_split_at_blank_line(self):
        result = split_into_sentences("Paragraph one.\n\nParagraph two.")
        assert len(result) == 2

    def test_multiple_paragraphs_multiple_sentences(self):
        text = (
            "First sentence. Second sentence.\n\n"
            "Third sentence. Fourth sentence."
        )
        result = split_into_sentences(text)
        assert len(result) == 4

    def test_exclamation_and_question_marks_split(self):
        result = split_into_sentences("Stop! Who goes there? Identify yourself.")
        assert len(result) == 3

    def test_units_are_non_empty_strings(self):
        result = split_into_sentences("Hello world.\n\nGoodbye world.")
        assert all(s.strip() for s in result)


# ── build_chunks ──────────────────────────────────────────────────────────────

class TestBuildChunks:
    def test_empty_text_returns_empty_list(self):
        assert build_chunks("", chunk_size=1000, overlap=100) == []

    def test_short_text_produces_single_chunk(self):
        text = "Short text."
        spans = build_chunks(text, chunk_size=1000, overlap=100)
        assert len(spans) == 1
        start, end = spans[0]
        assert start == 0
        assert end == len(text)

    def test_spans_cover_full_text(self):
        """The union of all spans should cover the entire text from 0 to end."""
        text = " ".join(f"Sentence number {i}." for i in range(100))
        spans = build_chunks(text, chunk_size=200, overlap=50)
        assert len(spans) >= 2
        # First span starts at 0
        assert spans[0][0] == 0
        # Last span ends at the text length
        assert spans[-1][1] == len(text)

    def test_chunks_do_not_exceed_chunk_size_by_more_than_one_unit(self):
        """
        build_chunks is sentence-aware, so a single sentence may push a chunk
        slightly over chunk_size.  But no chunk may exceed chunk_size + the
        length of the longest sentence unit (we use a loose upper threshold).
        """
        text = " ".join(f"Sentence number {i} with some extra words." for i in range(60))
        spans = build_chunks(text, chunk_size=300, overlap=50)
        # No span should be absurdly large (> 2× chunk_size)
        for start, end in spans:
            assert (end - start) <= 600, f"Chunk too large: {end - start} chars"

    def test_overlap_means_consecutive_spans_share_content(self):
        """
        With overlap=100, chunk[i+1] should start before where chunk[i] ended.
        At least one consecutive pair should show overlap.
        """
        # Build a text with many short sentences so we get multiple chunks
        text = " ".join(f"Word group {i}." for i in range(120))
        spans = build_chunks(text, chunk_size=200, overlap=80)
        if len(spans) > 1:
            overlapping_pairs = [
                i for i in range(len(spans) - 1)
                if spans[i + 1][0] < spans[i][1]
            ]
            assert len(overlapping_pairs) > 0, "Expected at least one overlapping pair"

    def test_single_very_long_sentence_still_emits_one_chunk(self):
        """
        A text consisting of a single long 'sentence' (no ., !, ?) that exceeds
        chunk_size should still produce at least one chunk.
        """
        text = "A" * 5000
        spans = build_chunks(text, chunk_size=1000, overlap=100)
        assert len(spans) >= 1
        assert spans[-1][1] == len(text)

    def test_spans_are_ordered(self):
        text = " ".join(f"Sentence number {i}." for i in range(100))
        spans = build_chunks(text, chunk_size=200, overlap=50)
        for i in range(len(spans) - 1):
            assert spans[i][0] < spans[i + 1][0], "Spans are not ordered by start position"


# ── _hard_split ───────────────────────────────────────────────────────────────

class TestHardSplit:
    def test_empty_text(self):
        assert _hard_split("", 1000, 100) == []

    def test_short_text_single_chunk(self):
        text = "abc"
        spans = _hard_split(text, chunk_size=100, overlap=10)
        assert spans == [(0, 3)]

    def test_exact_chunk_size_single_chunk(self):
        text = "a" * 100
        spans = _hard_split(text, chunk_size=100, overlap=10)
        assert spans == [(0, 100)]

    def test_two_chunks_with_overlap(self):
        text = "a" * 200
        spans = _hard_split(text, chunk_size=100, overlap=20)
        assert len(spans) == 3  # 0–100, 80–180, 160–200
        assert spans[0] == (0, 100)
        assert spans[1] == (80, 180)
        assert spans[2] == (160, 200)

    def test_last_chunk_ends_at_text_length(self):
        text = "a" * 250
        spans = _hard_split(text, chunk_size=100, overlap=10)
        assert spans[-1][1] == 250

    def test_sum_of_unique_chars_covers_all(self):
        text = "x" * 500
        spans = _hard_split(text, chunk_size=100, overlap=30)
        covered = set()
        for start, end in spans:
            covered.update(range(start, end))
        assert covered == set(range(len(text)))


# ── ChunkingService ───────────────────────────────────────────────────────────

class TestChunkingService:
    def test_empty_text_returns_empty_list(self):
        svc = ChunkingService(chunk_size=1000, overlap=100)
        result = svc.chunk_document("")
        assert result == []

    def test_short_text_produces_one_chunk(self):
        svc = ChunkingService(chunk_size=5000, overlap=500)
        text = "This is a short document. It has two sentences."
        chunks = svc.chunk_document(text)
        assert len(chunks) == 1
        assert isinstance(chunks[0], TextChunk)
        assert chunks[0].chunk_index == 0

    def test_text_chunk_fields_populated(self):
        svc = ChunkingService(chunk_size=5000, overlap=500)
        text = "Hello world. Goodbye world."
        chunks = svc.chunk_document(text)
        c = chunks[0]
        assert c.content  # non-empty
        assert c.start_char >= 0
        assert c.end_char > c.start_char
        assert c.page_start is None
        assert c.page_end is None

    def test_multiple_chunks_ordered_by_index(self):
        svc = ChunkingService(chunk_size=50, overlap=10)
        # Build a text long enough to exceed chunk_size
        text = " ".join(f"Sentence {i}." for i in range(50))
        chunks = svc.chunk_document(text)
        assert len(chunks) > 1
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_chunk_content_is_stripped(self):
        svc = ChunkingService(chunk_size=50, overlap=10)
        text = " ".join(f"Word {i}." for i in range(50))
        for chunk in svc.chunk_document(text):
            assert chunk.content == chunk.content.strip(), \
                f"Chunk content not stripped: {chunk.content!r}"

    def test_custom_chunk_size_used(self):
        """Smaller chunk_size → more chunks."""
        text = " ".join(f"Sentence number {i}." for i in range(100))
        big = ChunkingService(chunk_size=2000, overlap=100)
        small = ChunkingService(chunk_size=100, overlap=20)
        chunks_big = big.chunk_document(text)
        chunks_small = small.chunk_document(text)
        assert len(chunks_small) > len(chunks_big)

    def test_extraction_none_gives_no_page_metadata(self):
        svc = ChunkingService(chunk_size=5000, overlap=100)
        text = "Some text for testing. No extraction result provided."
        chunks = svc.chunk_document(text, extraction=None)
        for c in chunks:
            assert c.page_start is None
            assert c.page_end is None
