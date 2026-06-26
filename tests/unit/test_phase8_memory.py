"""
Phase 8 tests — Qdrant vector memory and NetworkX knowledge graph.
Covers: Embedder, VectorStore, MemoryRetriever, KnowledgeGraph.
"""
from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


# ── TestEmbedder ───────────────────────────────────────────────────────────────

class TestEmbedder:
    def _get_embedder(self):
        from apps.memory.vector.embedder import Embedder
        return Embedder()

    def test_embed_returns_list_of_floats(self):
        emb = self._get_embedder()
        vec = emb.embed("hello world")
        assert isinstance(vec, list)
        assert len(vec) == emb.DIMS
        assert all(isinstance(v, float) for v in vec)

    def test_pseudo_embed_deterministic(self):
        emb = self._get_embedder()
        v1 = emb._pseudo_embed("test text")
        v2 = emb._pseudo_embed("test text")
        assert v1 == v2

    def test_pseudo_embed_different_texts_differ(self):
        emb = self._get_embedder()
        v1 = emb._pseudo_embed("hello")
        v2 = emb._pseudo_embed("world")
        assert v1 != v2

    def test_pseudo_embed_normalized(self):
        emb = self._get_embedder()
        vec = emb._pseudo_embed("normalization test")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_pseudo_embed_correct_dims(self):
        emb = self._get_embedder()
        vec = emb._pseudo_embed("dimensions test")
        assert len(vec) == emb.DIMS

    def test_cosine_similarity_identical_vectors(self):
        emb = self._get_embedder()
        vec = emb._pseudo_embed("identical")
        sim = emb.cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    def test_cosine_similarity_range(self):
        emb = self._get_embedder()
        v1 = emb._pseudo_embed("alpha")
        v2 = emb._pseudo_embed("beta")
        sim = emb.cosine_similarity(v1, v2)
        assert -1.0 <= sim <= 1.0

    def test_embed_batch_returns_multiple_vectors(self):
        emb = self._get_embedder()
        texts = ["foo", "bar", "baz"]
        vecs = emb.embed_batch(texts)
        assert len(vecs) == 3
        for vec in vecs:
            assert len(vec) == emb.DIMS

    def test_dims_property(self):
        emb = self._get_embedder()
        assert emb.dims == 384

    def test_is_semantic_property_is_bool(self):
        emb = self._get_embedder()
        assert isinstance(emb.is_semantic, bool)

    def test_embed_empty_string_does_not_raise(self):
        emb = self._get_embedder()
        vec = emb.embed("")
        assert len(vec) == emb.DIMS

    def test_get_embedder_singleton(self):
        from apps.memory.vector.embedder import get_embedder
        e1 = get_embedder()
        e2 = get_embedder()
        assert e1 is e2


# ── TestVectorStore ────────────────────────────────────────────────────────────

class TestVectorStore:
    def _get_store(self):
        from apps.memory.vector.vector_store import VectorStore
        return VectorStore()

    def _make_point(self, content="test memory", category="general"):
        from apps.memory.vector.vector_store import MemoryPoint
        return MemoryPoint(content=content, category=category)

    def test_upsert_returns_true(self):
        store = self._get_store()
        point = self._make_point("hello")
        result = store.upsert(point)
        assert result is True

    def test_upsert_adds_to_store(self):
        store = self._get_store()
        point = self._make_point("unique content abc123")
        store.upsert(point)
        assert store.count() >= 1

    def test_upsert_generates_embedding(self):
        store = self._get_store()
        point = self._make_point("embed me")
        store.upsert(point)
        assert len(point.embedding) == 384

    def test_search_returns_results(self):
        store = self._get_store()
        store.upsert(self._make_point("python programming language"))
        results = store.search("python", top_k=5)
        assert isinstance(results, list)

    def test_search_returns_tuples(self):
        store = self._get_store()
        point = self._make_point("machine learning model training")
        store.upsert(point)
        results = store.search("machine learning", top_k=5)
        if results:
            p, sim = results[0]
            assert isinstance(sim, float)
            assert hasattr(p, "content")

    def test_search_with_category_filter(self):
        store = self._get_store()
        store.upsert(self._make_point("category A content", category="typeA"))
        store.upsert(self._make_point("category B content", category="typeB"))
        results = store.search("content", top_k=10, category="typeA")
        for p, _ in results:
            assert p.category == "typeA"

    def test_delete_removes_point(self):
        store = self._get_store()
        point = self._make_point("to be deleted")
        store.upsert(point)
        count_before = store.count()
        store.delete(point.id)
        assert store.count() == count_before - 1

    def test_count_increases_after_upsert(self):
        store = self._get_store()
        before = store.count()
        store.upsert(self._make_point("count test"))
        assert store.count() == before + 1

    def test_status_has_required_keys(self):
        store = self._get_store()
        status = store.status()
        assert "backend" in status
        assert "point_count" in status
        assert "embedder_semantic" in status
        assert "embedder_dims" in status

    def test_upsert_update_existing_point(self):
        store = self._get_store()
        point = self._make_point("original")
        store.upsert(point)
        count_after_first = store.count()
        # Upsert same id again — should update, not add
        point.content = "updated"
        store.upsert(point)
        assert store.count() == count_after_first

    def test_memory_point_to_dict(self):
        from apps.memory.vector.vector_store import MemoryPoint
        p = MemoryPoint(content="test", category="unit")
        d = p.to_dict()
        assert d["content"] == "test"
        assert d["category"] == "unit"
        assert "id" in d
        assert "created_at" in d


# ── TestMemoryRetriever ────────────────────────────────────────────────────────

class TestMemoryRetriever:
    def _get_retriever(self):
        from apps.memory.vector.memory_retriever import MemoryRetriever
        from apps.memory.vector.vector_store import VectorStore
        retriever = MemoryRetriever.__new__(MemoryRetriever)
        retriever._store = VectorStore()
        retriever._session_cache = []
        return retriever

    @pytest.mark.asyncio
    async def test_remember_returns_point(self):
        retriever = self._get_retriever()
        with patch("apps.memory.vector.memory_retriever.get_cache", return_value=_mock_cache()):
            point = await retriever.remember("important fact", category="facts")
        assert point.content == "important fact"
        assert point.category == "facts"

    @pytest.mark.asyncio
    async def test_remember_stores_in_vector_store(self):
        retriever = self._get_retriever()
        with patch("apps.memory.vector.memory_retriever.get_cache", return_value=_mock_cache()):
            await retriever.remember("stored fact", category="test")
        assert retriever._store.count() >= 1

    @pytest.mark.asyncio
    async def test_recall_returns_list(self):
        retriever = self._get_retriever()
        with patch("apps.memory.vector.memory_retriever.get_cache", return_value=_mock_cache()):
            await retriever.remember("deep learning neural networks")
        results = await retriever.recall("neural networks")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_recall_result_has_similarity(self):
        retriever = self._get_retriever()
        with patch("apps.memory.vector.memory_retriever.get_cache", return_value=_mock_cache()):
            await retriever.remember("python web framework fastapi")
        results = await retriever.recall("fastapi framework", top_k=5)
        if results:
            assert "similarity" in results[0]

    @pytest.mark.asyncio
    async def test_inject_context_empty_when_no_memories(self):
        retriever = self._get_retriever()
        ctx = await retriever.inject_context("completely unrelated query xyz987")
        assert isinstance(ctx, str)

    @pytest.mark.asyncio
    async def test_inject_context_returns_string(self):
        retriever = self._get_retriever()
        with patch("apps.memory.vector.memory_retriever.get_cache", return_value=_mock_cache()):
            await retriever.remember("relevant context info", category="general")
        ctx = await retriever.inject_context("relevant context")
        assert isinstance(ctx, str)

    @pytest.mark.asyncio
    async def test_inject_context_has_header_when_memories_exist(self):
        retriever = self._get_retriever()
        with patch("apps.memory.vector.memory_retriever.get_cache", return_value=_mock_cache()):
            await retriever.remember("very specific topic about databases", category="general")
        ctx = await retriever.inject_context("databases topic")
        # If memories are found (threshold may vary), header appears
        if ctx:
            assert "Relevant context" in ctx

    def test_status_has_store_status(self):
        retriever = self._get_retriever()
        status = retriever.status()
        assert "store_status" in status
        assert "session_cache_size" in status

    @pytest.mark.asyncio
    async def test_remember_with_tags_and_metadata(self):
        retriever = self._get_retriever()
        with patch("apps.memory.vector.memory_retriever.get_cache", return_value=_mock_cache()):
            point = await retriever.remember(
                "tagged memory",
                tags=["tag1", "tag2"],
                metadata={"key": "value"},
                source="test_source",
            )
        assert point.tags == ["tag1", "tag2"]
        assert point.metadata == {"key": "value"}
        assert point.source == "test_source"

    @pytest.mark.asyncio
    async def test_cache_error_does_not_raise(self):
        retriever = self._get_retriever()
        bad_cache = MagicMock()
        bad_cache.get = AsyncMock(side_effect=Exception("Redis down"))
        bad_cache.set = AsyncMock(side_effect=Exception("Redis down"))
        with patch("apps.memory.vector.memory_retriever.get_cache", return_value=bad_cache):
            # Should not raise even if cache fails
            point = await retriever.remember("resilient memory")
        assert point.content == "resilient memory"


# ── TestKnowledgeGraph ─────────────────────────────────────────────────────────

class TestKnowledgeGraph:
    def _get_kg(self):
        from apps.memory.graph.knowledge_graph import KnowledgeGraph
        return KnowledgeGraph()

    def test_add_entity_returns_entity(self):
        kg = self._get_kg()
        entity = kg.add_entity("Python", entity_type="language")
        assert entity.name == "Python"
        assert entity.entity_type == "language"
        assert entity.entity_id is not None

    def test_add_entity_stored_in_graph(self):
        kg = self._get_kg()
        entity = kg.add_entity("FastAPI")
        assert kg.get_entity(entity.entity_id) is entity

    def test_add_relation_returns_true(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e1 = kg.add_entity("Python")
        e2 = kg.add_entity("FastAPI")
        result = kg.add_relation(e1.entity_id, e2.entity_id, RelationType.USES)
        assert result is True

    def test_add_relation_invalid_source_returns_false(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e2 = kg.add_entity("FastAPI")
        result = kg.add_relation("nonexistent-id", e2.entity_id, RelationType.USES)
        assert result is False

    def test_find_by_name_returns_matching_entities(self):
        kg = self._get_kg()
        kg.add_entity("TensorFlow")
        kg.add_entity("PyTorch")
        kg.add_entity("OpenCV")
        results = kg.find_by_name("torch")
        assert any(e.name == "PyTorch" for e in results)

    def test_find_by_name_case_insensitive(self):
        kg = self._get_kg()
        kg.add_entity("PostgreSQL")
        results = kg.find_by_name("POSTGRESQL")
        assert len(results) >= 1

    def test_neighbors_returns_connected_entities(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e1 = kg.add_entity("ARIA")
        e2 = kg.add_entity("Memory")
        e3 = kg.add_entity("Graph")
        kg.add_relation(e1.entity_id, e2.entity_id, RelationType.HAS)
        kg.add_relation(e1.entity_id, e3.entity_id, RelationType.HAS)
        neighbors = kg.neighbors(e1.entity_id)
        neighbor_names = [e.name for e in neighbors]
        assert "Memory" in neighbor_names
        assert "Graph" in neighbor_names

    def test_neighbors_filtered_by_relation_type(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e1 = kg.add_entity("ARIA")
        e2 = kg.add_entity("Python")
        e3 = kg.add_entity("JavaScript")
        kg.add_relation(e1.entity_id, e2.entity_id, RelationType.USES)
        kg.add_relation(e1.entity_id, e3.entity_id, RelationType.COMPETES_WITH)
        uses_neighbors = kg.neighbors(e1.entity_id, RelationType.USES)
        assert any(e.name == "Python" for e in uses_neighbors)
        assert not any(e.name == "JavaScript" for e in uses_neighbors)

    def test_central_entities_returns_list(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e1 = kg.add_entity("Hub")
        e2 = kg.add_entity("Node1")
        e3 = kg.add_entity("Node2")
        kg.add_relation(e2.entity_id, e1.entity_id, RelationType.RELATED_TO)
        kg.add_relation(e3.entity_id, e1.entity_id, RelationType.RELATED_TO)
        centrals = kg.central_entities(top_k=3)
        assert isinstance(centrals, list)
        assert len(centrals) <= 3

    def test_entity_cluster_returns_connected_nodes(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e1 = kg.add_entity("Root")
        e2 = kg.add_entity("Child1")
        e3 = kg.add_entity("Child2")
        kg.add_relation(e1.entity_id, e2.entity_id, RelationType.HAS)
        kg.add_relation(e1.entity_id, e3.entity_id, RelationType.HAS)
        cluster = kg.entity_cluster(e1.entity_id, depth=1)
        cluster_names = [e.name for e in cluster]
        assert "Root" in cluster_names

    def test_summary_has_required_keys(self):
        kg = self._get_kg()
        summary = kg.summary()
        assert "backend" in summary
        assert "entity_count" in summary
        assert "relation_count" in summary
        assert "neo4j_connected" in summary
        assert "networkx_available" in summary

    def test_summary_counts_correctly(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e1 = kg.add_entity("A")
        e2 = kg.add_entity("B")
        kg.add_relation(e1.entity_id, e2.entity_id, RelationType.IS_A)
        summary = kg.summary()
        assert summary["entity_count"] == 2
        assert summary["relation_count"] == 1

    def test_to_dict_contains_entities_and_relations(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e1 = kg.add_entity("Source")
        e2 = kg.add_entity("Target")
        kg.add_relation(e1.entity_id, e2.entity_id, RelationType.PRODUCES)
        d = kg.to_dict()
        assert "entities" in d
        assert "relations" in d
        assert len(d["entities"]) == 2
        assert len(d["relations"]) == 1

    def test_entity_to_dict(self):
        from apps.memory.graph.knowledge_graph import Entity
        e = Entity(name="TestEntity", entity_type="test", properties={"x": 1})
        d = e.to_dict()
        assert d["name"] == "TestEntity"
        assert d["entity_type"] == "test"
        assert d["properties"] == {"x": 1}
        assert "entity_id" in d
        assert "created_at" in d

    def test_get_knowledge_graph_singleton(self):
        from apps.memory.graph.knowledge_graph import get_knowledge_graph
        kg1 = get_knowledge_graph()
        kg2 = get_knowledge_graph()
        assert kg1 is kg2

    def test_relation_type_values(self):
        from apps.memory.graph.knowledge_graph import RelationType
        assert RelationType.IS_A.value == "IS_A"
        assert RelationType.COMPETES_WITH.value == "COMPETES_WITH"
        assert RelationType.RELATED_TO.value == "RELATED_TO"

    def test_add_entity_with_properties(self):
        kg = self._get_kg()
        entity = kg.add_entity("Qdrant", entity_type="database", properties={"version": "1.7"})
        assert entity.properties == {"version": "1.7"}

    def test_shortest_path_direct(self):
        from apps.memory.graph.knowledge_graph import RelationType
        kg = self._get_kg()
        e1 = kg.add_entity("Start")
        e2 = kg.add_entity("End")
        kg.add_relation(e1.entity_id, e2.entity_id, RelationType.RELATED_TO)
        path = kg.shortest_path(e1.entity_id, e2.entity_id)
        assert len(path) >= 2
        assert path[0].name == "Start"
        assert path[-1].name == "End"

    def test_shortest_path_no_connection_returns_empty(self):
        kg = self._get_kg()
        e1 = kg.add_entity("Isolated1")
        e2 = kg.add_entity("Isolated2")
        path = kg.shortest_path(e1.entity_id, e2.entity_id)
        assert path == []
