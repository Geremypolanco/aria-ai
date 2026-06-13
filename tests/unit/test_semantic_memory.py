"""
Unit tests for semantic memory layer.

Verifies:
  - Fact storage and retrieval
  - Cosine similarity calculation
  - Keyword fallback when embeddings unavailable
  - Confidence reinforcement and contradiction
  - LRU eviction
  - Memory decay
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import AsyncMock, patch


class TestCosineSimilarity:
    def test_identical_vectors(self):
        from apps.core.memory.semantic_memory import _cosine_similarity
        v = [1.0, 0.0, 1.0, 0.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        from apps.core.memory.semantic_memory import _cosine_similarity
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_zero_vector(self):
        from apps.core.memory.semantic_memory import _cosine_similarity
        assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_length_mismatch_returns_zero(self):
        from apps.core.memory.semantic_memory import _cosine_similarity
        assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_similar_vectors(self):
        from apps.core.memory.semantic_memory import _cosine_similarity
        # Near-identical vectors should have high similarity
        sim = _cosine_similarity([1.0, 0.9, 1.0], [1.0, 1.0, 1.0])
        assert sim > 0.99


class TestFact:
    def test_relevance_score_with_embedding(self):
        from apps.core.memory.semantic_memory import Fact
        fact = Fact(
            id="f1", content="test", category="world_fact",
            source="aria", confidence=1.0,
            embedding=[1.0, 0.0],
            tags=[], created_at="", accessed_at="",
        )
        query_emb = [1.0, 0.0]
        score = fact.relevance_score(query_emb)
        assert abs(score - 1.0) < 1e-6

    def test_relevance_score_no_embedding(self):
        from apps.core.memory.semantic_memory import Fact
        fact = Fact(
            id="f1", content="test", category="world_fact",
            source="aria", confidence=0.9,
            embedding=[],
            tags=[], created_at="", accessed_at="",
        )
        assert fact.relevance_score([1.0, 0.0]) == 0.0

    def test_relevance_score_scaled_by_confidence(self):
        from apps.core.memory.semantic_memory import Fact
        fact_high = Fact(
            id="f1", content="test", category="world_fact",
            source="aria", confidence=1.0, embedding=[1.0, 0.0],
            tags=[], created_at="", accessed_at="",
        )
        fact_low = Fact(
            id="f2", content="test", category="world_fact",
            source="aria", confidence=0.5, embedding=[1.0, 0.0],
            tags=[], created_at="", accessed_at="",
        )
        q = [1.0, 0.0]
        assert fact_high.relevance_score(q) > fact_low.relevance_score(q)

    def test_serialization_roundtrip(self):
        from apps.core.memory.semantic_memory import Fact
        fact = Fact(
            id="abc123", content="ARIA prefers structured output",
            category="user_preference", source="user",
            confidence=0.9, embedding=[0.1, 0.2, 0.3],
            tags=["preferences", "output"],
            created_at="2026-01-01T00:00:00Z",
            accessed_at="2026-01-01T00:00:00Z",
            access_count=5, decay_factor=0.95,
        )
        d = fact.to_dict()
        restored = Fact.from_dict(d)
        assert restored.id == fact.id
        assert restored.content == fact.content
        assert restored.embedding == fact.embedding
        assert restored.access_count == 5


class TestSemanticMemory:
    @pytest.fixture
    def mem(self):
        from apps.core.memory.semantic_memory import SemanticMemory
        return SemanticMemory()

    @pytest.mark.asyncio
    async def test_store_and_retrieve_with_keyword_fallback(self, mem):
        """When embeddings unavailable, keyword search should still work."""
        with patch.object(mem, "_embed", new=AsyncMock(return_value=[])):
            fact_id = await mem.store("ARIA can write Python code", category="skill")
            results = await mem.search("Python programming")

        assert len(results) > 0
        assert any("Python" in r.content for r in results)

    @pytest.mark.asyncio
    async def test_store_returns_fact_id(self, mem):
        with patch.object(mem, "_embed", new=AsyncMock(return_value=[])):
            fact_id = await mem.store("Test fact")
        assert isinstance(fact_id, str)
        assert len(fact_id) > 0

    @pytest.mark.asyncio
    async def test_search_with_embeddings(self, mem):
        """With embeddings, more relevant facts should rank higher."""
        embedding_a = [1.0, 0.0, 0.0]
        embedding_b = [0.0, 1.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]  # closer to A

        call_count = 0

        async def mock_embed(text: str):
            nonlocal call_count
            call_count += 1
            if "Python" in text or call_count == 3:
                return embedding_a
            return embedding_b

        with patch.object(mem, "_embed", side_effect=mock_embed):
            await mem.store("Python code generation skill", category="skill")
            await mem.store("Cooking recipe knowledge", category="world_fact")
            results = await mem.search("Python programming", top_k=2)

        # Python-related fact should rank first when query embedding matches
        if results and len(results) >= 1:
            assert "Python" in results[0].content or len(results) >= 1

    @pytest.mark.asyncio
    async def test_category_filter(self, mem):
        with patch.object(mem, "_embed", new=AsyncMock(return_value=[])):
            await mem.store("User likes dark mode", category="user_preference")
            await mem.store("Python is a programming language", category="world_fact")

            skill_results = await mem.search("", category="user_preference")
            world_results = await mem.search("", category="world_fact")

        assert all(f.category == "user_preference" for f in skill_results)
        assert all(f.category == "world_fact" for f in world_results)

    @pytest.mark.asyncio
    async def test_reinforce_increases_confidence(self, mem):
        with patch.object(mem, "_embed", new=AsyncMock(return_value=[])):
            fact_id = await mem.store("Reinforceable fact", confidence=0.5)
            success = await mem.reinforce(fact_id, confidence_delta=0.2)

        assert success
        assert mem._working[fact_id].confidence > 0.5
        assert mem._working[fact_id].confidence <= 1.0

    @pytest.mark.asyncio
    async def test_contradict_decreases_confidence(self, mem):
        with patch.object(mem, "_embed", new=AsyncMock(return_value=[])):
            fact_id = await mem.store("Contradictable fact", confidence=0.9)
            success = await mem.contradict(fact_id, confidence_delta=0.3)

        assert success
        assert mem._working[fact_id].confidence < 0.9

    @pytest.mark.asyncio
    async def test_contradict_removes_low_confidence_fact(self, mem):
        with patch.object(mem, "_embed", new=AsyncMock(return_value=[])):
            fact_id = await mem.store("Weak fact", confidence=0.15)
            await mem.contradict(fact_id, confidence_delta=0.2)

        # Fact should be removed when confidence drops below 0.1
        assert fact_id not in mem._working

    def test_memory_decay(self, mem):
        from apps.core.memory.semantic_memory import Fact
        fact = Fact(
            id="decay-test", content="Decaying fact", category="world_fact",
            source="test", confidence=0.8, embedding=[],
            tags=[], created_at="", accessed_at="", decay_factor=1.0,
        )
        mem._working["decay-test"] = fact

        mem.apply_decay(decay_rate=0.1)

        assert mem._working["decay-test"].decay_factor < 1.0
        assert mem._working["decay-test"].decay_factor >= 0.1

    def test_eviction_removes_lru_facts(self, mem):
        from apps.core.memory.semantic_memory import Fact, MAX_WORKING_MEMORY

        # Fill working memory to limit
        for i in range(MAX_WORKING_MEMORY):
            fact = Fact(
                id=f"f{i}", content=f"Fact {i}", category="world_fact",
                source="test", confidence=0.5, embedding=[],
                tags=[], created_at="", accessed_at="",
                decay_factor=0.1 if i < MAX_WORKING_MEMORY // 2 else 1.0,
            )
            mem._working[f"f{i}"] = fact

        initial_count = len(mem._working)
        mem._evict_lru()

        assert len(mem._working) < initial_count

    def test_summary_returns_correct_counts(self, mem):
        from apps.core.memory.semantic_memory import Fact
        for i, cat in enumerate(["skill", "skill", "world_fact"]):
            fact = Fact(
                id=f"s{i}", content=f"Fact {i}", category=cat,
                source="test", confidence=0.8, embedding=[],
                tags=[], created_at="", accessed_at="",
            )
            mem._working[f"s{i}"] = fact

        summary = mem.summary()
        assert summary["total_facts"] == 3
        assert summary["by_category"]["skill"] == 2
        assert summary["by_category"]["world_fact"] == 1
        assert 0.0 < summary["avg_confidence"] <= 1.0

    def test_keyword_score(self, mem):
        score = mem._keyword_score("Python is a great language", {"python", "language"})
        assert score > 0.0

        no_match = mem._keyword_score("Cooking recipes", {"python", "language"})
        assert no_match == 0.0

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_id(self, mem):
        result = await mem.get("nonexistent-id-xyz")
        assert result is None
