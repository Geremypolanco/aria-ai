"""
document_engine.py — Document and Research Engine powered by LlamaIndex.

Provides:
  - Advanced RAG (Retrieval Augmented Generation)
  - Document agents for deep research
  - Indexing of multiple sources (PDF, Notion, Slack, etc.)
  - Semantic and hierarchical retrieval

Reference: https://docs.llamaindex.ai/
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("aria.document_engine")

# ── LlamaIndex import with fallback ──────────────────────────────────────────
try:
    from llama_index.core import (  # noqa: F401
        Settings,
        SimpleDirectoryReader,
        StorageContext,
        VectorStoreIndex,
    )

    LLAMA_INDEX_AVAILABLE = True
    logger.info("[LlamaIndex] Library loaded successfully.")
except ImportError:
    LLAMA_INDEX_AVAILABLE = False
    logger.warning("[LlamaIndex] llama-index not installed. Using fallback.")


class AriaDocumentEngine:
    """
    ARIA's document research engine.
    Uses LlamaIndex to process and query large volumes of information.
    """

    def __init__(self, index_dir: str = "./storage") -> None:
        self.index_dir = index_dir
        self._index = None

        if LLAMA_INDEX_AVAILABLE:
            # Default configuration (using OpenAI for simplicity)
            try:
                if not os.path.exists(self.index_dir):
                    os.makedirs(self.index_dir)
                logger.info("[LlamaIndex] Storage directory ready: %s", self.index_dir)
            except Exception as exc:
                logger.error("[LlamaIndex] Error initializing: %s", exc)

    async def index_directory(self, directory_path: str):
        """Indexes all documents in a directory."""
        if not LLAMA_INDEX_AVAILABLE:
            return

        try:
            documents = SimpleDirectoryReader(directory_path).load_data()
            self._index = VectorStoreIndex.from_documents(documents)
            self._index.storage_context.persist(persist_dir=self.index_dir)
            logger.info("[LlamaIndex] Directory %s indexed successfully.", directory_path)
        except Exception as exc:
            logger.error("[LlamaIndex] Error indexing directory: %s", exc)

    async def query_knowledge(self, query: str) -> str:
        """Queries the indexed knowledge."""
        if not self._index:
            return "No documents indexed to answer with."

        try:
            query_engine = self._index.as_query_engine()
            response = query_engine.query(query)
            return str(response)
        except Exception as exc:
            logger.error("[LlamaIndex] Error during query: %s", exc)
            return f"Error querying knowledge: {exc}"


# ── Singleton ────────────────────────────────────────────────────────────────
_document_engine_instance: AriaDocumentEngine | None = None


def get_document_engine() -> AriaDocumentEngine:
    """Returns the document engine singleton."""
    global _document_engine_instance
    if _document_engine_instance is None:
        _document_engine_instance = AriaDocumentEngine()
    return _document_engine_instance
