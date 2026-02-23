"""
Text chunking service.

Splits cleaned document text into overlapping character-based chunks.
The approach is intentionally simple for the MVP:

  • Split on sentence / paragraph boundaries where possible
  • Target chunk size  : CHUNK_SIZE  chars  (default 3 000)
  • Overlap            : CHUNK_OVERLAP chars (default 400)
  • Page metadata is preserved by tracking char offsets against the
    original ExtractionResult's page boundaries.

All core logic lives in pure functions for easy unit-testing.

Typical usage
─────────────
    from app.utils.pdf import extract_pages
    from app.utils.text_cleaning import clean_text
    from app.services.chunking_service import ChunkingService

    result  = extract_pages("lecture.pdf")
    cleaned = clean_text(result.full_text)
    chunks  = ChunkingService().chunk_document(cleaned, extraction=result)

    for c in chunks:
        print(c.chunk_index, c.start_char, c.end_char,
              c.page_start, c.page_end, c.content[:60])
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.core.config import settings
from app.utils.pdf import ExtractionResult

logger = logging.getLogger(__name__)

# Sentence-boundary splitter — split after . ! ? followed by whitespace or EOL
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
# Paragraph boundary (blank line)
_PARAGRAPH_RE = re.compile(r"\n\n+")


# ── Data structures ───────────────────────────────────────────────


@dataclass
class TextChunk:
    """One chunk produced by the chunking service."""

    chunk_index: int          # 0-based position within the document
    content: str              # chunk text (already cleaned)
    start_char: int           # inclusive start offset in the full cleaned text
    end_char: int             # exclusive end offset in the full cleaned text

    # Page metadata — derived from ExtractionResult if provided, else None
    page_start: int | None = field(default=None)
    page_end: int | None = field(default=None)


# ── Pure helper functions ─────────────────────────────────────────


def split_into_sentences(text: str) -> list[str]:
    """
    Split text into a list of sentence-like units.

    Splits on paragraph breaks first, then on sentence endings within
    each paragraph, so paragraph structure is preferred as a split point.
    This avoids cutting in the middle of headings or bullet points.
    """
    paragraphs = _PARAGRAPH_RE.split(text)
    units: list[str] = []
    for para in paragraphs:
        if not para.strip():
            continue
        sentences = _SENTENCE_END_RE.split(para)
        units.extend(s for s in sentences if s.strip())
    return units


def build_chunks(
    text: str,
    chunk_size: int = 3000,
    overlap: int = 400,
) -> list[tuple[int, int]]:
    """
    Return a list of (start, end) character offset pairs for the given text.

    Algorithm
    ─────────
    1. Split the text into sentence-like units.
    2. Greedily fill a window up to `chunk_size` chars.
    3. When the window would exceed `chunk_size`, emit a chunk and
       backtrack `overlap` chars to start the next one.

    Pure function: no side-effects.

    Parameters
    ----------
    text       : full cleaned document text
    chunk_size : target maximum characters per chunk
    overlap    : characters carried over to the next chunk

    Returns
    -------
    List of (start_char, end_char) tuples (exclusive end).
    """
    if not text:
        return []

    units = split_into_sentences(text)
    if not units:
        # Fallback: hard-split with no sentence awareness
        return _hard_split(text, chunk_size, overlap)

    spans: list[tuple[int, int]] = []
    cursor = 0            # position in the original text we've consumed
    chunk_start = 0

    for unit in units:
        # Find where this unit sits in the original text
        unit_pos = text.find(unit, cursor)
        if unit_pos == -1:
            # unit not found at cursor position (shouldn't happen, but be safe)
            cursor += len(unit)
            continue

        unit_end = unit_pos + len(unit)
        current_len = unit_end - chunk_start

        if current_len > chunk_size and chunk_start < unit_pos:
            # Emit the current chunk before adding this unit
            spans.append((chunk_start, unit_pos))
            # Start next chunk `overlap` chars back from the boundary
            chunk_start = max(chunk_start, unit_pos - overlap)

        cursor = unit_end

    # Emit the final remaining chunk
    if chunk_start < len(text):
        spans.append((chunk_start, len(text)))

    return spans


def _hard_split(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int]]:
    """Fallback: sliding window when sentence detection yields nothing."""
    spans: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        spans.append((start, end))
        if end == length:
            break
        start = end - overlap
    return spans


def resolve_page_range(
    start_char: int,
    end_char: int,
    extraction: ExtractionResult,
) -> tuple[int | None, int | None]:
    """
    Given a character range in the *full_text* of an ExtractionResult,
    return the (page_start, page_end) page numbers (1-based) that the
    chunk overlaps.

    The mapping is approximate because `clean_text` may shift offsets
    slightly; we do a best-effort lookup.
    """
    page_start: int | None = None
    page_end: int | None = None

    for page in extraction.pages:
        # overlap check: [page.char_start, page.char_end) ∩ [start_char, end_char)
        if page.char_end <= start_char:
            continue
        if page.char_start >= end_char:
            break
        if page_start is None:
            page_start = page.page_number
        page_end = page.page_number

    return page_start, page_end


# ── Service class ─────────────────────────────────────────────────


class ChunkingService:
    """
    Stateless service that turns a cleaned document text into TextChunks.

    chunk_size and overlap default to settings values so they can be
    overridden at construction time in tests.
    """

    def __init__(
        self,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> None:
        self.chunk_size = chunk_size if chunk_size is not None else settings.CHUNK_SIZE
        self.overlap = overlap if overlap is not None else settings.CHUNK_OVERLAP

    def chunk_document(
        self,
        cleaned_text: str,
        extraction: ExtractionResult | None = None,
    ) -> list[TextChunk]:
        """
        Chunk `cleaned_text` and optionally attach page metadata.

        Parameters
        ----------
        cleaned_text : output of ``clean_text(full_text)``
        extraction   : original ExtractionResult used for page-number mapping.
                       If None, page_start/page_end will be None on every chunk.

        Returns
        -------
        Ordered list of TextChunk objects.
        """
        spans = build_chunks(cleaned_text, self.chunk_size, self.overlap)
        chunks: list[TextChunk] = []

        for idx, (start, end) in enumerate(spans):
            content = cleaned_text[start:end].strip()
            if not content:
                continue

            page_start, page_end = (
                resolve_page_range(start, end, extraction)
                if extraction is not None
                else (None, None)
            )

            chunks.append(
                TextChunk(
                    chunk_index=idx,
                    content=content,
                    start_char=start,
                    end_char=end,
                    page_start=page_start,
                    page_end=page_end,
                )
            )

        logger.debug(
            "Chunked document: %d chunks from %d chars (size=%d, overlap=%d)",
            len(chunks),
            len(cleaned_text),
            self.chunk_size,
            self.overlap,
        )
        return chunks
