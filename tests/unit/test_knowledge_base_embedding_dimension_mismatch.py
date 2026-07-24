"""Regression test: KnowledgeChunk.cosine_similarity() used
zip(self.embedding, other, strict=False), which silently truncates the dot
product to the shorter vector's length while norm1/norm2 are each computed
over their own full length. Since _embed() falls back from the 384-dim HF
model to the 128-dim _hash_embed() on ANY HF failure (timeout, rate limit,
non-200 — all routine with the free HF inference API), a knowledge base can
end up with a mix of 128-dim and 384-dim vectors. Comparing across that mix
produced a systematically deflated, meaningless similarity score instead of
an explicit "not comparable" signal — silently degrading search() results
below SIMILARITY_THRESHOLD with no error surfaced.
"""

from __future__ import annotations

from apps.core.tools.knowledge_base import KnowledgeChunk


def test_cosine_similarity_returns_zero_for_mismatched_dimensions():
    chunk = KnowledgeChunk(
        id="1", source="test", category="general", text="hello", embedding=[1.0] * 384
    )

    result = chunk.cosine_similarity([1.0] * 128)

    assert result == 0.0


def test_cosine_similarity_still_works_for_matching_dimensions():
    chunk = KnowledgeChunk(
        id="1", source="test", category="general", text="hello", embedding=[1.0, 0.0]
    )

    result = chunk.cosine_similarity([1.0, 0.0])

    assert result == 1.0
