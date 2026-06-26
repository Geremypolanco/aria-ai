"""
VectorStore — Qdrant production backend with in-memory fallback.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )

    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False

from apps.memory.vector.embedder import get_embedder

_COLLECTION_NAME = "aria_memory"
_VECTOR_SIZE = 384


@dataclass
class MemoryPoint:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    embedding: list[float] = field(default_factory=list)
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    source: str = ""
    score: float = 1.0  # relevance/importance
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "score": self.score,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class VectorStore:
    """
    Dual-backend vector store.
    - If QDRANT_URL env var is set → Qdrant cloud/local
    - Otherwise → in-memory fallback with cosine similarity
    """

    def __init__(self, collection_name: str = _COLLECTION_NAME):
        self._collection = collection_name
        self._embedder = get_embedder()
        self._client = None
        self._in_memory: list[MemoryPoint] = []
        self._backend = "memory"
        self._init_backend()

    def _init_backend(self) -> None:
        if not _QDRANT_AVAILABLE:
            return
        import os

        url = os.environ.get("QDRANT_URL", "")
        api_key = os.environ.get("QDRANT_API_KEY", "")
        if url:
            try:
                self._client = QdrantClient(url=url, api_key=api_key or None)
                self._ensure_collection()
                self._backend = "qdrant"
            except Exception:
                self._client = None
        else:
            try:
                self._client = QdrantClient(":memory:")
                self._ensure_collection()
                self._backend = "qdrant_memory"
            except Exception:
                self._client = None

    def _ensure_collection(self) -> None:
        if not self._client:
            return
        try:
            collections = [c.name for c in self._client.get_collections().collections]
            if self._collection not in collections:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
                )
        except Exception:
            pass

    def upsert(self, point: MemoryPoint) -> bool:
        """Add or update a memory point."""
        if not point.embedding:
            point.embedding = self._embedder.embed(point.content)

        if self._client:
            try:
                payload = point.to_dict()
                self._client.upsert(
                    collection_name=self._collection,
                    points=[
                        PointStruct(
                            id=point.id,
                            vector=point.embedding,
                            payload=payload,
                        )
                    ],
                )
                return True
            except Exception:
                pass

        # In-memory fallback
        existing_idx = next((i for i, p in enumerate(self._in_memory) if p.id == point.id), None)
        if existing_idx is not None:
            self._in_memory[existing_idx] = point
        else:
            self._in_memory.append(point)
        return True

    def search(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        score_threshold: float = 0.0,
    ) -> list[tuple[MemoryPoint, float]]:
        """Semantic search returning (point, similarity_score) tuples."""
        query_vec = self._embedder.embed(query)

        if self._client:
            try:
                filter_condition = None
                if category:
                    filter_condition = Filter(
                        must=[FieldCondition(key="category", match=MatchValue(value=category))]
                    )
                results = self._client.search(
                    collection_name=self._collection,
                    query_vector=query_vec,
                    limit=top_k,
                    query_filter=filter_condition,
                    score_threshold=score_threshold,
                )
                points = []
                for r in results:
                    payload = r.payload or {}
                    p = MemoryPoint(
                        id=str(r.id),
                        content=payload.get("content", ""),
                        category=payload.get("category", "general"),
                        tags=payload.get("tags", []),
                        source=payload.get("source", ""),
                        score=payload.get("score", 1.0),
                        created_at=payload.get("created_at", time.time()),
                        metadata=payload.get("metadata", {}),
                        embedding=query_vec,
                    )
                    points.append((p, r.score))
                return points
            except Exception:
                pass

        # In-memory cosine search
        scored = []
        for p in self._in_memory:
            if category and p.category != category:
                continue
            sim = self._embedder.cosine_similarity(query_vec, p.embedding or [])
            if sim >= score_threshold:
                scored.append((p, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def delete(self, point_id: str) -> bool:
        if self._client:
            try:
                self._client.delete(collection_name=self._collection, points_selector=[point_id])
                return True
            except Exception:
                pass
        self._in_memory = [p for p in self._in_memory if p.id != point_id]
        return True

    def count(self) -> int:
        if self._client:
            try:
                return self._client.count(collection_name=self._collection).count
            except Exception:
                pass
        return len(self._in_memory)

    def status(self) -> dict:
        return {
            "backend": self._backend,
            "collection": self._collection,
            "point_count": self.count(),
            "embedder_semantic": self._embedder.is_semantic,
            "embedder_dims": self._embedder.dims,
            "qdrant_available": _QDRANT_AVAILABLE,
        }


_store_instance: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = VectorStore()
    return _store_instance
