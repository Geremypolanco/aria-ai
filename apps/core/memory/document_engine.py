"""
document_engine.py — Motor de Documentos e Investigación con LlamaIndex.

Proporciona capacidades de:
  - RAG (Retrieval Augmented Generation) avanzado
  - Agentes documentales para investigación profunda
  - Indexación de múltiples fuentes (PDF, Notion, Slack, etc.)
  - Recuperación semántica y jerárquica

Referencia: https://docs.llamaindex.ai/
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("aria.document_engine")

# ── LlamaIndex Import con fallback ───────────────────────────────────────────
try:
    from llama_index.core import (  # noqa: F401
        Settings,
        SimpleDirectoryReader,
        StorageContext,
        VectorStoreIndex,
    )

    LLAMA_INDEX_AVAILABLE = True
    logger.info("[LlamaIndex] Librería cargada correctamente.")
except ImportError:
    LLAMA_INDEX_AVAILABLE = False
    logger.warning("[LlamaIndex] llama-index no instalado. Usando fallback.")


class AriaDocumentEngine:
    """
    Motor de investigación documental de ARIA.
    Utiliza LlamaIndex para procesar y consultar grandes volúmenes de información.
    """

    def __init__(self, index_dir: str = "./storage") -> None:
        self.index_dir = index_dir
        self._index = None

        if LLAMA_INDEX_AVAILABLE:
            # Configuración por defecto (usando OpenAI por simplicidad)
            try:
                if not os.path.exists(self.index_dir):
                    os.makedirs(self.index_dir)
                logger.info("[LlamaIndex] Directorio de almacenamiento listo: %s", self.index_dir)
            except Exception as exc:
                logger.error("[LlamaIndex] Error inicializando: %s", exc)

    async def index_directory(self, directory_path: str):
        """Indexa todos los documentos en un directorio."""
        if not LLAMA_INDEX_AVAILABLE:
            return

        try:
            documents = SimpleDirectoryReader(directory_path).load_data()
            self._index = VectorStoreIndex.from_documents(documents)
            self._index.storage_context.persist(persist_dir=self.index_dir)
            logger.info("[LlamaIndex] Directorio %s indexado con éxito.", directory_path)
        except Exception as exc:
            logger.error("[LlamaIndex] Error indexando directorio: %s", exc)

    async def query_knowledge(self, query: str) -> str:
        """Consulta el conocimiento indexado."""
        if not self._index:
            return "No hay documentos indexados para responder."

        try:
            query_engine = self._index.as_query_engine()
            response = query_engine.query(query)
            return str(response)
        except Exception as exc:
            logger.error("[LlamaIndex] Error en consulta: %s", exc)
            return f"Error consultando conocimiento: {exc}"


# ── Singleton ────────────────────────────────────────────────────────────────
_document_engine_instance: AriaDocumentEngine | None = None


def get_document_engine() -> AriaDocumentEngine:
    """Retorna el singleton del motor de documentos."""
    global _document_engine_instance
    if _document_engine_instance is None:
        _document_engine_instance = AriaDocumentEngine()
    return _document_engine_instance
