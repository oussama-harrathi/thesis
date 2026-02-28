"""
TopicChunkMapper — builds TopicChunkMap associations.

Strategy (in order of reliability):
  1. Page-range match  — if topic has start/end_page, find chunks whose
     page_start falls inside [topic.start_page, topic.end_page]
  2. Embedding similarity — for topics without page range, or to fill
     gaps where page-range mapping is sparse, cosine-similarity between
     the topic-title embedding and each chunk embedding.

Returns a list of dicts ready for bulk-insert into `topic_chunk_map`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

_SIM_TOP_K = 8           # max chunks per topic via embedding similarity
_SIM_THRESHOLD = 0.30    # minimum cosine similarity to include a mapping
_PAGE_MIN_CHUNKS = 2     # if page-range gives fewer chunks, augment with emb


def _cosine_batch(query: "np.ndarray", matrix: "np.ndarray") -> "np.ndarray":
    """Return cosine-similarity between query vector and every row of matrix."""
    import numpy as np

    qn = query / (float(np.linalg.norm(query)) + 1e-10)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    return (matrix / norms) @ qn


class TopicChunkMapper:
    """Matches Topic rows to Chunk rows and returns association data."""

    def __init__(self, embedding_service: Any | None = None):
        """
        Args:
            embedding_service: optional service that has an `embed(text)` method
                returning a float list.  If None, embedding-similarity mapping
                is skipped for topics without page ranges.
        """
        self._embed_svc = embedding_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_mappings(
        self,
        topics: list[Any],          # ORM Topic rows (have .id, .title, .page_start, .page_end)
        chunks: list[Any],          # ORM Chunk rows  (have .id, .page_start, .embedding)
        extracted_topics: list[Any] | None = None,  # original ExtractedTopic dataclasses
    ) -> list[dict[str, Any]]:
        """
        Returns a list of dicts:
            {"topic_id": UUID, "chunk_id": UUID, "relevance_score": float}
        """
        if not topics or not chunks:
            return []

        rows: list[dict[str, Any]] = []

        # Build page → chunks lookup
        page_to_chunks: dict[int, list[Any]] = {}
        for ch in chunks:
            pg = getattr(ch, "page_start", None)
            if pg is not None:
                page_to_chunks.setdefault(pg, []).append(ch)

        # Build chunk id lookup and embedding matrix (for similarity path)
        chunk_list = list(chunks)
        emb_matrix: Any | None = None
        valid_emb_chunks: list[Any] = []

        valid_emb_chunks = [ch for ch in chunk_list if getattr(ch, "embedding", None) is not None]
        if valid_emb_chunks:
            try:
                import numpy as np
                emb_matrix = np.array(
                    [np.asarray(ch.embedding, dtype=np.float32) for ch in valid_emb_chunks]
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("TopicChunkMapper: could not build emb matrix: %s", exc)
                emb_matrix = None

        # topic_id → set of chunk_ids already mapped (dedup)
        seen: dict[Any, set[Any]] = {}

        for topic in topics:
            tid = topic.id
            seen.setdefault(tid, set())

            start_pg: int | None = getattr(topic, "page_start", None)
            end_pg: int | None = getattr(topic, "page_end", None)
            if end_pg is None and start_pg is not None:
                # Give page-less topics a 1-page span
                end_pg = start_pg

            # --- Path 1: page-range mapping --------------------------------
            page_matched: list[Any] = []
            if start_pg is not None and end_pg is not None:
                for pg in range(start_pg, end_pg + 1):
                    for ch in page_to_chunks.get(pg, []):
                        if ch.id not in seen[tid]:
                            seen[tid].add(ch.id)
                            page_matched.append(ch)
                            rows.append({
                                "topic_id": tid,
                                "chunk_id": ch.id,
                                "relevance_score": 0.80,
                            })

            # --- Path 2: embedding-similarity mapping ----------------------
            need_emb = len(page_matched) < _PAGE_MIN_CHUNKS
            if need_emb and emb_matrix is not None:
                # Get topic title embedding
                title_emb = self._get_title_embedding(
                    getattr(topic, "title", None) or getattr(topic, "name", "")
                )
                if title_emb is not None:
                    try:
                        import numpy as np
                        q = np.asarray(title_emb, dtype=np.float32)
                        sims = _cosine_batch(q, emb_matrix)
                        order = sims.argsort()[::-1]
                        added = 0
                        for idx in order:
                            if added >= _SIM_TOP_K:
                                break
                            sim = float(sims[idx])
                            if sim < _SIM_THRESHOLD:
                                break
                            ch = valid_emb_chunks[int(idx)]
                            if ch.id not in seen[tid]:
                                seen[tid].add(ch.id)
                                rows.append({
                                    "topic_id": tid,
                                    "chunk_id": ch.id,
                                    "relevance_score": round(sim, 4),
                                })
                                added += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("TopicChunkMapper: embedding sim error for topic %s: %s", tid, exc)

        logger.info(
            "TopicChunkMapper: %d topic-chunk mappings for %d topics",
            len(rows), len(topics),
        )
        return rows

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_title_embedding(self, title: str) -> list[float] | None:
        if self._embed_svc is None:
            return None
        try:
            # Support both encode_one() (EmbeddingService) and embed() (generic)
            if hasattr(self._embed_svc, "encode_one"):
                result = self._embed_svc.encode_one(title)
            else:
                result = self._embed_svc.embed(title)
            if isinstance(result, list):
                return result
            # sentence-transformers may return ndarray
            import numpy as np
            return np.asarray(result, dtype=np.float32).tolist()
        except Exception as exc:  # noqa: BLE001
            logger.debug("TopicChunkMapper: embed('%s') failed: %s", title, exc)
            return None
