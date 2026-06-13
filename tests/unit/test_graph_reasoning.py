"""
Tests for graph-based reasoning and hypothesis engine.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock


class TestReasoningGraph:
    def test_root_node_created_on_init(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph
        g = ReasoningGraph("Is the market large?")
        assert "root" in g._nodes
        assert g._nodes["root"].content == "Is the market large?"

    def test_add_hypothesis_creates_node_and_edge(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph, NodeType
        g = ReasoningGraph("Test question")
        h_id = g.add_hypothesis("Market is growing", confidence=0.7)
        assert h_id in g._nodes
        assert g._nodes[h_id].confidence == 0.7
        assert g._nodes[h_id].node_type == NodeType.HYPOTHESIS
        # Should have edge from root to hypothesis
        assert any(e.source == "root" and e.target == h_id for e in g._edges)

    def test_add_evidence_creates_node(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph, NodeType
        g = ReasoningGraph("Test")
        e_id = g.add_evidence("Google Trends shows 40% growth", confidence=0.9)
        assert e_id in g._nodes
        assert g._nodes[e_id].node_type == NodeType.EVIDENCE
        assert g._nodes[e_id].confidence == 0.9

    def test_supporting_evidence_raises_hypothesis_confidence(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph, EdgeType
        g = ReasoningGraph("Test question")
        h_id = g.add_hypothesis("Big market", confidence=0.5)
        e_id = g.add_evidence("Strong growth data", confidence=0.9)
        g.add_edge(e_id, h_id, EdgeType.SUPPORTS, weight=0.8)

        before = g._nodes[h_id].confidence
        g.propagate_confidence()
        after = g._nodes[h_id].confidence

        assert after > before

    def test_contradicting_evidence_lowers_hypothesis_confidence(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph, EdgeType
        g = ReasoningGraph("Test question")
        h_id = g.add_hypothesis("Big market", confidence=0.8)
        e_id = g.add_evidence("Market is shrinking", confidence=0.9)
        g.add_edge(e_id, h_id, EdgeType.CONTRADICTS, weight=0.8)

        g.propagate_confidence()

        assert g._nodes[h_id].confidence < 0.8

    def test_dominant_hypothesis_returns_highest_confidence(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph
        g = ReasoningGraph("Which strategy?")
        h1 = g.add_hypothesis("Strategy A", confidence=0.8)
        h2 = g.add_hypothesis("Strategy B", confidence=0.3)
        h3 = g.add_hypothesis("Strategy C", confidence=0.6)

        dominant = g.dominant_hypothesis()
        assert dominant is not None
        assert dominant.id == h1

    def test_prune_removes_low_confidence_hypotheses(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph
        g = ReasoningGraph("Test")
        h1 = g.add_hypothesis("Strong hypothesis", confidence=0.8)
        h2 = g.add_hypothesis("Weak hypothesis", confidence=0.1)

        pruned = g.prune_weak_branches(threshold=0.2)

        assert pruned == 1
        assert h2 not in g._nodes
        assert h1 in g._nodes

    def test_promote_to_conclusion(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph, NodeType
        g = ReasoningGraph("Test")
        h_id = g.add_hypothesis("Winner", confidence=0.9)
        conc_id = g.promote_to_conclusion(h_id)

        assert conc_id in g._nodes
        assert g._nodes[conc_id].node_type == NodeType.CONCLUSION

    def test_hypotheses_sorted_by_confidence(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph
        g = ReasoningGraph("Sort test")
        g.add_hypothesis("Mid", confidence=0.5)
        g.add_hypothesis("High", confidence=0.9)
        g.add_hypothesis("Low", confidence=0.2)

        hyps = g.hypotheses()
        confidences = [h.confidence for h in hyps]
        assert confidences == sorted(confidences, reverse=True)

    def test_evidence_for_returns_supporting_evidence(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph, EdgeType
        g = ReasoningGraph("Test")
        h_id = g.add_hypothesis("Hypothesis", confidence=0.7)
        e_id = g.add_evidence("Supporting fact", confidence=0.9)
        g.add_edge(e_id, h_id, EdgeType.SUPPORTS, weight=0.8)

        ev_for = g.evidence_for(h_id)
        assert len(ev_for) == 1
        assert ev_for[0].id == e_id

    def test_to_dict_is_serializable(self):
        import json
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph, EdgeType
        g = ReasoningGraph("Serialization test")
        h_id = g.add_hypothesis("Test hyp", confidence=0.6)
        e_id = g.add_evidence("Test evidence", confidence=0.8)
        g.add_edge(e_id, h_id, EdgeType.SUPPORTS, weight=0.7)

        d = g.to_dict()
        serialized = json.dumps(d)  # must not raise
        assert isinstance(json.loads(serialized), dict)

    def test_sub_hypothesis_has_increased_depth(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph
        g = ReasoningGraph("Deep test")
        h1_id = g.add_hypothesis("Top level", confidence=0.7)
        sh_id = g.add_sub_hypothesis(h1_id, "Sub hypothesis", confidence=0.6)

        assert g._nodes[sh_id].depth > g._nodes[h1_id].depth

    def test_summary_contains_question(self):
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph
        q = "What is the best strategy?"
        g = ReasoningGraph(q)
        g.add_hypothesis("Strategy A", confidence=0.7)
        summary = g.summary()
        assert q in summary


class TestHypothesisManager:
    @pytest.fixture
    def mock_ai(self):
        ai = AsyncMock()
        call_count = 0

        async def complete_json_side(**kwargs):
            nonlocal call_count
            call_count += 1
            system = kwargs.get("system", "")
            if "competing hypotheses" in system.lower() or "competing" in system.lower():
                return {"hypotheses": ["Content marketing drives revenue", "Shopify products work better"]}
            elif "evidence" in system.lower():
                return {"evidence": [
                    {"content": "Blog traffic converts at 2%", "confidence": 0.8, "relation": "supports"},
                    {"content": "Shopify stores need SEO", "confidence": 0.7, "relation": "contradicts"},
                ]}
            else:
                return {}

        ai.complete_json = AsyncMock(side_effect=lambda **kw: complete_json_side(**kw))
        ai.complete = AsyncMock()
        ai.complete.return_value = AsyncMock(success=True, content="Content marketing wins.")
        return ai

    @pytest.mark.asyncio
    async def test_compete_returns_competition(self, mock_ai):
        from apps.core.cognition.hypothesis_engine.hypothesis_manager import HypothesisManager
        manager = HypothesisManager(mock_ai)
        competition = await manager.compete(
            "What income strategy should ARIA use?",
            context={"revenue": 0},
            n_hypotheses=2,
        )
        assert competition.id
        assert competition.question
        assert len(competition.branches) > 0
        assert competition.winner is not None

    @pytest.mark.asyncio
    async def test_compete_without_ai_returns_fallback(self):
        from apps.core.cognition.hypothesis_engine.hypothesis_manager import HypothesisManager
        manager = HypothesisManager(ai_client=None)
        competition = await manager.compete("Test question")

        assert competition.winner is not None
        assert competition.winner.final_confidence <= 0.2  # fallback is low confidence

    @pytest.mark.asyncio
    async def test_winner_is_highest_scored_branch(self, mock_ai):
        from apps.core.cognition.hypothesis_engine.hypothesis_manager import HypothesisManager
        manager = HypothesisManager(mock_ai)
        competition = await manager.compete("Best strategy?", n_hypotheses=2)

        if len(competition.branches) >= 2:
            winner_score = competition.winner.score()
            for branch in competition.branches:
                assert branch.score() <= winner_score + 0.001  # winner is best

    @pytest.mark.asyncio
    async def test_losing_branches_marked_archived(self, mock_ai):
        from apps.core.cognition.hypothesis_engine.hypothesis_manager import HypothesisManager
        manager = HypothesisManager(mock_ai)
        competition = await manager.compete("Best strategy?", n_hypotheses=2)

        if len(competition.branches) >= 2:
            non_winners = [b for b in competition.branches if b.id != competition.winner.id]
            assert all(b.archived for b in non_winners)

    def test_branch_score_incorporates_evidence(self):
        from apps.core.cognition.hypothesis_engine.hypothesis_manager import HypothesisBranch
        from apps.core.cognition.graph_runtime.reasoning_graph import ReasoningGraph

        g = ReasoningGraph("Test")
        b_rich = HypothesisBranch(
            id="rich", hypothesis="A", graph=g,
            final_confidence=0.7, evidence_count=6,
        )
        b_poor = HypothesisBranch(
            id="poor", hypothesis="B", graph=g,
            final_confidence=0.7, evidence_count=0,
        )
        assert b_rich.score() > b_poor.score()

    @pytest.mark.asyncio
    async def test_archive_is_maintained(self, mock_ai):
        from apps.core.cognition.hypothesis_engine.hypothesis_manager import HypothesisManager
        manager = HypothesisManager(mock_ai)
        await manager.compete("Question 1")
        await manager.compete("Question 2")

        archive = manager.get_archive()
        assert len(archive) == 2
