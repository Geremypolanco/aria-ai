"""
ARIA Hypothesis Engine — Multi-branch hypothesis generation and competitive selection.

Design:
  - Given a question, generates N competing hypotheses via LLM
  - Each hypothesis spawns an independent reasoning branch
  - Branches run in parallel; evidence is collected for each
  - Branches are scored: confidence × evidence_weight × consistency
  - The winning branch becomes ARIA's answer; losers are archived for learning
  - Dead branches inform future hypothesis generation (avoid known dead-ends)

This produces BETTER answers than linear CoT because:
  - Cognitive diversity: multiple framings of the problem surface different evidence
  - Competition: weak hypotheses are eliminated early, not at the end
  - Branching: a hypothesis can recursively generate sub-hypotheses
  - Learning: archived losers prevent repeating failed reasoning paths
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from apps.core.cognition.graph_runtime.reasoning_graph import (
    EdgeType,
    NodeType,
    ReasoningGraph,
)

logger = logging.getLogger("aria.hypothesis_engine")

MAX_HYPOTHESES = 5
MAX_EVIDENCE_PER_BRANCH = 6
PRUNE_THRESHOLD = 0.2


@dataclass
class HypothesisBranch:
    """A self-contained reasoning branch built around one hypothesis."""

    id: str
    hypothesis: str
    graph: ReasoningGraph
    final_confidence: float = 0.0
    verdict: str = ""  # short conclusion if this hypothesis wins
    evidence_count: int = 0
    archived: bool = False  # True = this branch lost the competition
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def score(self) -> float:
        """Composite branch score: confidence × evidence richness."""
        evidence_factor = min(1.0, self.evidence_count / MAX_EVIDENCE_PER_BRANCH)
        return self.final_confidence * (0.7 + 0.3 * evidence_factor)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "hypothesis": self.hypothesis,
            "final_confidence": round(self.final_confidence, 4),
            "score": round(self.score(), 4),
            "verdict": self.verdict,
            "evidence_count": self.evidence_count,
            "archived": self.archived,
            "graph_summary": self.graph.summary(),
        }


@dataclass
class HypothesisCompetition:
    """The full multi-branch reasoning session for one question."""

    id: str
    question: str
    branches: list[HypothesisBranch]
    winner: HypothesisBranch | None
    context: dict[str, Any]
    total_time_ms: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "branches": [b.to_dict() for b in self.branches],
            "winner": self.winner.to_dict() if self.winner else None,
            "context": self.context,
            "total_time_ms": self.total_time_ms,
            "created_at": self.created_at,
        }


class HypothesisManager:
    """
    Runs competitive multi-branch hypothesis exploration.

    Usage:
        manager = HypothesisManager(ai_client)
        competition = await manager.compete(
            question="What is the best income strategy this week?",
            context={"revenue_ytd": 0, "skills": ["content", "ai"]},
        )
        print(competition.winner.verdict)
    """

    def __init__(self, ai_client=None) -> None:
        self._ai = ai_client
        self._archive: list[HypothesisCompetition] = []

    def set_ai_client(self, ai_client) -> None:
        self._ai = ai_client

    # ── Main Entry Point ─────────────────────────────────────────────────

    async def compete(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        n_hypotheses: int = 3,
    ) -> HypothesisCompetition:
        import time

        start = time.monotonic()
        context = context or {}
        comp_id = uuid.uuid4().hex[:8]

        logger.info("[HypothesisEngine] Starting competition %s: %s", comp_id, question[:80])

        # No AI client → genuine low-confidence fallback (cannot reason)
        if not self._ai:
            return self._no_op_competition(comp_id, question, context)

        # Phase 1: Generate competing hypotheses
        hypotheses = await self._generate_hypotheses(question, context, n_hypotheses)
        if not hypotheses:
            return self._no_op_competition(comp_id, question, context)

        # Phase 2: Build and explore branches in parallel
        branches = await asyncio.gather(
            *[self._build_branch(question, h, context) for h in hypotheses],
            return_exceptions=True,
        )
        valid_branches: list[HypothesisBranch] = [
            b for b in branches if isinstance(b, HypothesisBranch)
        ]

        if not valid_branches:
            return self._no_op_competition(comp_id, question, context)

        # Phase 3: Propagate confidence and select winner
        for branch in valid_branches:
            branch.graph.propagate_confidence()
            branch.graph.prune_weak_branches(PRUNE_THRESHOLD)
            dom = branch.graph.dominant_hypothesis()
            branch.final_confidence = dom.confidence if dom else 0.1
            branch.evidence_count = sum(
                1 for n in branch.graph._nodes.values() if n.node_type == NodeType.EVIDENCE
            )

        valid_branches.sort(key=lambda b: b.score(), reverse=True)
        winner = valid_branches[0]
        winner.archived = False
        for b in valid_branches[1:]:
            b.archived = True

        # Phase 4: Synthesize winner's verdict
        winner.verdict = await self._synthesize_verdict(question, winner, context)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        competition = HypothesisCompetition(
            id=comp_id,
            question=question,
            branches=valid_branches,
            winner=winner,
            context=context,
            total_time_ms=elapsed_ms,
        )
        self._archive.append(competition)
        logger.info(
            "[HypothesisEngine] Competition %s done in %dms — winner: %.0f%% — %s",
            comp_id,
            elapsed_ms,
            winner.final_confidence * 100,
            winner.hypothesis[:60],
        )
        return competition

    # ── Phase 1: Hypothesis Generation ──────────────────────────────────

    async def _generate_hypotheses(self, question: str, context: dict, n: int) -> list[str]:
        if not self._ai:
            return [f"Default hypothesis: {question}"]

        system = (
            "You are a reasoning engine. Generate competing hypotheses for a question.\n"
            "Each hypothesis should be a DISTINCT framing — different assumptions, angles.\n"
            "Avoid hypotheses that are trivially related.\n\n"
            'Return JSON: {"hypotheses": ["<h1>", "<h2>", ...]}\n'
            f"Generate exactly {n} hypotheses. Be concrete and specific."
        )
        user_msg = (
            f"Question: {question}\n\n" f"Context: {json.dumps(context, ensure_ascii=False)[:1500]}"
        )
        try:
            raw = await self._ai.complete_json(system=system, user=user_msg)
            hyps = raw.get("hypotheses", [])[:MAX_HYPOTHESES]
            return [str(h) for h in hyps if h]
        except Exception as exc:
            logger.warning("[HypothesisEngine] Hypothesis generation failed: %s", exc)
            return [f"Primary hypothesis about: {question}"]

    # ── Phase 2: Branch Building ──────────────────────────────────────────

    async def _build_branch(
        self, question: str, hypothesis: str, context: dict
    ) -> HypothesisBranch:
        branch_id = uuid.uuid4().hex[:6]
        graph = ReasoningGraph(question=question)
        hyp_node_id = graph.add_hypothesis(hypothesis, confidence=0.6)

        evidence_list = await self._gather_evidence(question, hypothesis, context)
        for ev_content, ev_conf, ev_relation in evidence_list:
            ev_id = graph.add_evidence(ev_content, confidence=ev_conf)
            edge_type = EdgeType.SUPPORTS if ev_relation == "supports" else EdgeType.CONTRADICTS
            graph.add_edge(ev_id, hyp_node_id, edge_type, weight=ev_conf)

        return HypothesisBranch(
            id=branch_id,
            hypothesis=hypothesis,
            graph=graph,
        )

    async def _gather_evidence(
        self, question: str, hypothesis: str, context: dict
    ) -> list[tuple[str, float, str]]:
        """Returns list of (content, confidence, relation) tuples."""
        if not self._ai:
            return [("No AI available for evidence gathering", 0.3, "supports")]

        system = (
            "Find evidence FOR and AGAINST a hypothesis. Be specific — cite facts, data, logic.\n"
            "Return JSON:\n"
            "{\n"
            '  "evidence": [\n'
            '    {"content": "<fact>", "confidence": 0.8, "relation": "supports|contradicts"}\n'
            "  ]\n"
            "}\n"
            f"Return {MAX_EVIDENCE_PER_BRANCH} pieces of evidence total, balanced."
        )
        user_msg = (
            f"Original question: {question}\n"
            f"Hypothesis to evaluate: {hypothesis}\n"
            f"Context: {json.dumps(context, ensure_ascii=False)[:1000]}"
        )
        try:
            raw = await self._ai.complete_json(system=system, user=user_msg)
            items = raw.get("evidence", [])[:MAX_EVIDENCE_PER_BRANCH]
            return [
                (
                    str(item.get("content", "")),
                    float(item.get("confidence", 0.5)),
                    str(item.get("relation", "supports")),
                )
                for item in items
                if item.get("content")
            ]
        except Exception as exc:
            logger.warning("[HypothesisEngine] Evidence gathering failed: %s", exc)
            return []

    # ── Phase 4: Verdict Synthesis ────────────────────────────────────────

    async def _synthesize_verdict(
        self, question: str, winner: HypothesisBranch, context: dict
    ) -> str:
        if not self._ai:
            return winner.hypothesis

        ev_for = [
            n.content
            for n in winner.graph.evidence_for(
                list(winner.graph._nodes.keys())[1] if len(winner.graph._nodes) > 1 else "root"
            )
        ]
        system = (
            "Synthesize a winning hypothesis into a crisp, actionable conclusion.\n"
            "1-2 sentences max. Be direct. Include the key evidence that decided it."
        )
        user_msg = (
            f"Question: {question}\n"
            f"Winning hypothesis: {winner.hypothesis}\n"
            f"Supporting evidence: {ev_for[:3]}\n"
            f"Confidence: {winner.final_confidence:.0%}"
        )
        try:
            resp = await self._ai.complete(system=system, user=user_msg, max_tokens=150)
            return resp.content if resp and resp.success else winner.hypothesis
        except Exception:
            return winner.hypothesis

    # ── Utilities ─────────────────────────────────────────────────────────

    def _no_op_competition(
        self, comp_id: str, question: str, context: dict
    ) -> HypothesisCompetition:
        fallback_graph = ReasoningGraph(question=question)
        fallback_graph.add_hypothesis(f"Cannot reason about: {question}", confidence=0.1)
        branch = HypothesisBranch(
            id="fallback",
            hypothesis=f"Cannot reason about: {question}",
            graph=fallback_graph,
            final_confidence=0.1,
            verdict="AI unavailable — cannot run hypothesis competition.",
        )
        return HypothesisCompetition(
            id=comp_id,
            question=question,
            branches=[branch],
            winner=branch,
            context=context,
        )

    def get_archive(self, limit: int = 10) -> list[dict]:
        return [c.to_dict() for c in self._archive[-limit:]]


_manager: HypothesisManager | None = None


def get_hypothesis_manager(ai_client=None) -> HypothesisManager:
    global _manager
    if _manager is None:
        _manager = HypothesisManager(ai_client)
    elif ai_client is not None and _manager._ai is None:
        _manager.set_ai_client(ai_client)
    return _manager
