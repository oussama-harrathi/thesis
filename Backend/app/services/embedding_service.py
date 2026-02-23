"""
EmbeddingService — wraps sentence-transformers all-MiniLM-L6-v2.

Design decisions
────────────────
- Lazy-loaded singleton: the model is heavy (~90 MB), so it is loaded once
  on first use, not at import time.  Subsequent calls reuse the cached instance.
- Thread-safe initialisation via a simple lock (safe for Celery workers with
  the default prefork pool).
- Pure encode interface: accepts a list of strings, returns a list of float
  vectors.  No DB, no side-effects.

Typical usage (worker context)
───────────────────────────────
    from app.services.embedding_service import EmbeddingService

    svc = EmbeddingService()
    vectors = svc.encode(["chunk text 1", "chunk text 2"])
    # vectors: list[list[float]], each of length 384
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_instance: "SentenceTransformer | None" = None


def _load_model() -> "SentenceTransformer":
    """Load model on first call; return cached instance thereafter."""
    global _model_instance
    if _model_instance is not None:
        return _model_instance
    with _model_lock:
        if _model_instance is not None:          # double-checked locking
            return _model_instance
        logger.info("Loading embedding model '%s'…", settings.EMBEDDING_MODEL)
        from sentence_transformers import SentenceTransformer
        _model_instance = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info(
            "Embedding model loaded (dim=%d).", settings.EMBEDDING_DIM
        )
    return _model_instance


class EmbeddingService:
    """
    Thin wrapper around SentenceTransformer.

    All methods are synchronous — intended for use inside Celery tasks.
    """

    def encode(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> list[list[float]]:
        """
        Encode a list of texts into embedding vectors.

        Parameters
        ----------
        texts        : non-empty list of strings to encode
        batch_size   : forwarded to sentence-transformers (tune for GPU/CPU)
        show_progress: show tqdm bar (useful during development)

        Returns
        -------
        list of float vectors, length == settings.EMBEDDING_DIM (384)
        """
        if not texts:
            return []

        model = _load_model()
        logger.debug("Encoding %d text(s) with batch_size=%d", len(texts), batch_size)

        raw = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
            normalize_embeddings=True,   # unit-norm vectors → cosine via dot product
        )
        # Convert numpy array rows to plain Python lists
        return [row.tolist() for row in raw]

    def encode_one(self, text: str) -> list[float]:
        """Convenience wrapper for a single text."""
        return self.encode([text])[0]
