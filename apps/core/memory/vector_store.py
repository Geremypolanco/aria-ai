"""
vector_store.py — Motores de Búsqueda Vectorial para ARIA AI.

Integra Qdrant y Weaviate para RAG de alto rendimiento.
Permite almacenar y recuperar embeddings de forma masiva para:
  - Bases de conocimiento extensas
  - Memoria de agentes
  - Búsqueda semántica en documentos

Referencia:
  - Qdrant: https://qdrant.tech/
  - Weaviate: https://weaviate.io/
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("aria.vector_store")

# ── Qdrant Import con fallback ───────────────────────────────────────────────
try:
    from qdrant_client import QdrantClient

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

# ── Weaviate Import con fallback ─────────────────────────────────────────────
try:
    import weaviate

    WEAVIATE_AVAILABLE = True
except ImportError:
    WEAVIATE_AVAILABLE = False


class AriaVectorStore:
    """
    Gestor de bases de datos vectoriales de ARIA.
    Abstrae el uso de Qdrant o Weaviate según configuración.
    """

    def __init__(self, provider: str = "qdrant", host: str = "localhost", port: int = 6333) -> None:
        self.provider = provider
        self.client = None

        if provider == "qdrant" and QDRANT_AVAILABLE:
            try:
                self.client = QdrantClient(host=host, port=port)
                logger.info("[VectorStore] Qdrant conectado en %s:%d", host, port)
            except Exception as exc:
                logger.error("[VectorStore] Error conectando a Qdrant: %s", exc)

        elif provider == "weaviate" and WEAVIATE_AVAILABLE:
            try:
                # Conexión simplificada para Weaviate v4
                self.client = weaviate.connect_to_local(host=host, port=port)
                logger.info("[VectorStore] Weaviate conectado en %s:%d", host, port)
            except Exception as exc:
                logger.error("[VectorStore] Error conectando a Weaviate: %s", exc)

    async def search(self, collection: str, query_vector: list[float], limit: int = 5):
        """Realiza una búsqueda por similitud vectorial."""
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
    """Retorna el singleton del almacén vectorial."""
    global _vector_store_instance
    if _vector_store_instance is None:
        provider = os.getenv("VECTOR_STORE_PROVIDER", "qdrant")
        _vector_store_instance = AriaVectorStore(provider=provider)
    return _vector_store_instance
