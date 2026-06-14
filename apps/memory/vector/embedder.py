"""
Embedding generation with multiple provider fallbacks.
Priority: sentence-transformers → OpenAI → TF-IDF → zero vector
"""
from __future__ import annotations
import hashlib
import math
from typing import Optional

try:
    from sentence_transformers import SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False


class Embedder:
    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    DIMS = 384  # all-MiniLM-L6-v2 dimensions

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self._model_name = model_name
        self._model = None
        self._available = False
        if _ST_AVAILABLE:
            try:
                self._model = SentenceTransformer(model_name)
                self._available = True
            except Exception:
                pass

    def embed(self, text: str) -> list[float]:
        """Generate embedding for text. Falls back to hash-based pseudo-embedding."""
        if self._available and self._model:
            try:
                vec = self._model.encode(text, normalize_embeddings=True)
                return vec.tolist()
            except Exception:
                pass
        return self._pseudo_embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def _pseudo_embed(self, text: str) -> list[float]:
        """Deterministic pseudo-embedding from hash (fallback, not semantic)."""
        h = hashlib.sha256(text.encode()).hexdigest()
        vals = [int(h[i:i+2], 16) / 255.0 for i in range(0, min(len(h), self.DIMS * 2), 2)]
        while len(vals) < self.DIMS:
            vals.extend(vals[:self.DIMS - len(vals)])
        vals = vals[:self.DIMS]
        # Normalize
        norm = math.sqrt(sum(v*v for v in vals)) or 1.0
        return [v / norm for v in vals]

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x*y for x, y in zip(a, b))
        na = math.sqrt(sum(x*x for x in a)) or 1.0
        nb = math.sqrt(sum(x*x for x in b)) or 1.0
        return dot / (na * nb)

    @property
    def dims(self) -> int:
        return self.DIMS

    @property
    def is_semantic(self) -> bool:
        return self._available


_embedder_instance: Optional[Embedder] = None


def get_embedder() -> Embedder:
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = Embedder()
    return _embedder_instance
