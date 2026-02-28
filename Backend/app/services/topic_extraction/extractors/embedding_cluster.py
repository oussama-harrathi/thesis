"""
EmbeddingClusterExtractor — last-resort topic discovery via k-means over
chunk embeddings.

Uses only the pre-computed chunk embeddings that are already in the DB.
Does NOT hit the LLM. Uses numpy (always available as dep of
sentence-transformers) for a simple k-means implementation since sklearn
is not installed.

Cluster labels are derived from TF-IDF-style top-3 keywords from the
combined chunk text of each cluster.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

from app.services.topic_extraction.base import (
    METHOD_EMBEDDING_CLUSTERS,
    LEVEL_CLUSTER,
    ExtractedTopic,
    TopicExtractionResult,
)

logger = logging.getLogger(__name__)

_MAX_CHUNKS = 500
_K_MIN = 5
_K_MAX = 40
_K_PER_CHUNKS = 20  # 1 cluster per K_PER_CHUNKS chunks
_MAX_ITERATIONS = 50
_STOP_THRESHOLD = 1e-4


# ------------------------------------------------------------------
# Pure-numpy k-means
# ------------------------------------------------------------------
def _numpy_kmeans(X: "np.ndarray", k: int) -> "np.ndarray":
    """Return label assignments (shape: N,) for k clusters."""
    import numpy as np

    rng = np.random.default_rng(42)
    idx = rng.choice(len(X), size=k, replace=False)
    centers = X[idx].copy()

    labels = np.zeros(len(X), dtype=int)
    for _ in range(_MAX_ITERATIONS):
        # assign
        dists = np.linalg.norm(X[:, None, :] - centers[None, :, :], axis=2)
        new_labels = dists.argmin(axis=1)
        if np.all(new_labels == labels):
            break
        labels = new_labels
        # update centers
        for c in range(k):
            members = X[labels == c]
            if len(members) > 0:
                centers[c] = members.mean(axis=0)
    return labels


# ------------------------------------------------------------------
# Simple TF-IDF keyword extraction (no external deps)
# ------------------------------------------------------------------
_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "will", "would", "shall", "should",
    "may", "might", "can", "could", "that", "this", "these", "those",
    "it", "its", "which", "who", "from", "by", "as", "not", "no", "if",
    "then", "so", "we", "you", "they", "i", "he", "she", "all", "also",
}

_TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")


def _top_keywords(texts: list[str], top_n: int = 4) -> list[str]:
    """Return top-N keywords by TF-IDF score across a small corpus."""
    import math

    tokens_per_doc = [_TOKEN_RE.findall(t.lower()) for t in texts]
    n_docs = max(1, len(tokens_per_doc))

    # document frequency
    df: dict[str, int] = {}
    for tokens in tokens_per_doc:
        for tok in set(tokens):
            df[tok] = df.get(tok, 0) + 1

    # TF-IDF score = tf * log(N/df)
    tfidf: dict[str, float] = {}
    for tokens in tokens_per_doc:
        for tok in tokens:
            if tok in _STOP_WORDS or len(tok) < 4:
                continue
            tf = tokens.count(tok) / max(1, len(tokens))
            idf = math.log(n_docs / max(1, df.get(tok, 1)))
            tfidf[tok] = tfidf.get(tok, 0.0) + tf * idf

    ranked = sorted(tfidf.items(), key=lambda kv: kv[1], reverse=True)
    return [w.title() for w, _ in ranked[:top_n]]


class EmbeddingClusterExtractor:
    """
    Cluster chunk embeddings with k-means; label each cluster by keywords.
    Requires chunks with pre-computed `.embedding` vectors.
    """

    name = "embedding_clusters"

    def extract(
        self,
        file_path: str,
        *,
        chunks: list[Any] | None = None,
    ) -> TopicExtractionResult:
        empty = TopicExtractionResult(
            topics=[],
            method=METHOD_EMBEDDING_CLUSTERS,
            overall_confidence=0.0,
            debug_info={"reason": "no embedding data"},
        )

        if not chunks:
            return empty

        try:
            import numpy as np
        except ImportError:
            empty.debug_info["reason"] = "numpy not available"
            return empty

        # Filter chunks that have embeddings
        valid: list[Any] = []
        for ch in chunks:
            emb = getattr(ch, "embedding", None)
            if emb is not None:
                valid.append(ch)

        if len(valid) < _K_MIN:
            empty.debug_info["reason"] = f"too few chunks with embeddings ({len(valid)})"
            return empty

        # Cap for performance
        if len(valid) > _MAX_CHUNKS:
            valid = valid[:_MAX_CHUNKS]

        # Build embedding matrix
        try:
            X = np.array([np.asarray(ch.embedding, dtype=np.float32) for ch in valid])
        except Exception as exc:  # noqa: BLE001
            empty.debug_info["reason"] = f"embedding array error: {exc}"
            return empty

        # Normalize for cosine similarity
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        X_norm = X / norms

        # Choose k
        k = min(_K_MAX, max(_K_MIN, len(valid) // _K_PER_CHUNKS))

        # K-means
        try:
            labels = _numpy_kmeans(X_norm, k)
        except Exception as exc:  # noqa: BLE001
            empty.debug_info["reason"] = f"kmeans error: {exc}"
            return empty

        # Build topics from clusters
        topics: list[ExtractedTopic] = []
        for cluster_id in range(k):
            members_idx = np.where(labels == cluster_id)[0]
            if len(members_idx) == 0:
                continue
            members = [valid[i] for i in members_idx]
            texts = [str(getattr(ch, "text", "") or "") for ch in members]
            keywords = _top_keywords(texts, top_n=4)
            if not keywords:
                continue
            title = " / ".join(keywords[:3])

            # Intra-cluster mean cosine similarity as confidence signal
            cluster_vecs = X_norm[members_idx]
            centroid = cluster_vecs.mean(axis=0)
            sims = cluster_vecs @ centroid
            mean_sim = float(sims.mean())
            # map [0.3, 0.9] → [0.25, 0.55]
            conf = 0.25 + 0.30 * min(1.0, max(0.0, (mean_sim - 0.30) / 0.60))

            # Page range from chunk metadata
            pages: list[int] = sorted(
                pg
                for ch in members
                if (pg := getattr(ch, "page_start", None)) is not None
            )
            start_pg = pages[0] if pages else None
            end_pg = pages[-1] if pages else None

            topics.append(
                ExtractedTopic(
                    title=title,
                    level=LEVEL_CLUSTER,
                    confidence=conf,
                    start_page=start_pg,
                    end_page=end_pg,
                    meta={"cluster_id": cluster_id, "chunk_count": len(members)},
                )
            )

        if not topics:
            empty.debug_info["reason"] = "clusters produced no valid titles"
            return empty

        overall_conf = min(0.55, sum(t.confidence for t in topics) / len(topics))
        logger.info(
            "EmbeddingClusterExtractor: k=%d → %d topics; overall_conf=%.2f",
            k, len(topics), overall_conf,
        )
        return TopicExtractionResult(
            topics=topics,
            method=METHOD_EMBEDDING_CLUSTERS,
            overall_confidence=overall_conf,
            debug_info={
                "chunks_used": len(valid),
                "k": k,
                "topics_found": len(topics),
            },
        )
