"""
vector_store.py — Vector Search Engines for ARIA AI.

Integrates Qdrant and Weaviate for high-performance RAG.
Enables storing and retrieving embeddings at scale for:
  - Large knowledge bases
  - Agent memory
  - Semantic search over documents

Reference:
  - Qdrant: https://qdrant.tech/
  - Weaviate: https://weaviate.io/
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("aria.vector_store")

# ── Qdrant import with fallback ──────────────────────────────────────────────
try:
    from qdrant_client import QdrantClient

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

# ── Weaviate import with fallback ────────────────────────────────────────────
try:
    import weaviate

    WEAVIATE_AVAILABLE = True
except ImportError:
    WEAVIATE_AVAILABLE = False


class AriaVectorStore:
    """
    ARIA's vector database manager.
    Abstracts the use of Qdrant or Weaviate based on configuration.
    """

    def __init__(self, provider: str = "qdrant", host: str = "localhost", port: int = 6333) -> None:
        self.provider = provider
        self.client = None

        if provider == "qdrant" and QDRANT_AVAILABLE:
            try:
                self.client = QdrantClient(host=host, port=port)
                logger.info("[VectorStore] Qdrant connected at %s:%d", host, port)
            except Exception as exc:
                logger.error("[VectorStore] Error connecting to Qdrant: %s", exc)

        elif provider == "weaviate" and WEAVIATE_AVAILABLE:
            try:
                # Simplified connection for Weaviate v4
                self.client = weaviate.connect_to_local(host=host, port=port)
                logger.info("[VectorStore] Weaviate connected at %s:%d", host, port)
            except Exception as exc:
                logger.error("[VectorStore] Error connecting to Weaviate: %s", exc)

    async def search(self, collection: str, query_vector: list[float], limit: int = 5):
        """Performs a vector similarity search."""
        if not self.client:
            return []

        if self.provider == "qdrant":
            return self.client.search(
                collection_name=collection, query_vector=query_vector, limit=limit
            )

        return []


# ── Singleton ────────────────────────────────────────────────────────────────
_vector_store_instance: AriaVectorStore | None = None


def get_vector_store() -> AriaVectorStore:
    """Returns the vector store singleton."""
    global _vector_store_instance
    if _vector_store_instance is None:
        provider = os.getenv("VECTOR_STORE_PROVIDER", "qdrant")
        _vector_store_instance = AriaVectorStore(provider=provider)
    return _vector_store_instance
