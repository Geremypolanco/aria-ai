"""
ARIA Graph-Based Reasoning — Competing hypothesis exploration over a directed reasoning graph.

Architecture:
  - Reasoning is a GRAPH, not a list. Nodes are claims; edges are logical relationships.
  - Multiple hypotheses compete simultaneously — the strongest wins by evidence weight.
  - Confidence PROPAGATES through edges: strong evidence lifts all hypotheses it supports.
  - Weak branches are pruned early; dominant paths are explored deeper.
  - The final answer is the highest-scoring path from ROOT to a CONCLUSION node.

Node types:
  ROOT        — the original question (exactly one per graph)
  HYPOTHESIS  — a candidate answer (multiple, competing)
  EVIDENCE    — a fact that supports or contradicts a hypothesis
  CONCLUSION  — a synthesized final claim (promoted from best hypothesis)

Edge types:
  SUPPORTS    — weight +confidence  (evidence lifts hypothesis)
  CONTRADICTS — weight -confidence  (evidence weakens hypothesis)
  DERIVED     — weight neutral      (logical derivation)
  REFINES     — weight small +      (sub-hypothesis of parent)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

try:
    import networkx as nx

    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False
    nx = None


class NodeType(StrEnum):
    ROOT = "root"
    HYPOTHESIS = "hypothesis"
    EVIDENCE = "evidence"
    CONCLUSION = "conclusion"


class EdgeType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DERIVED = "derived"
    REFINES = "refines"


@dataclass
class ReasoningNode:
    id: str
    content: str
    node_type: NodeType
    confidence: float  # 0.0–1.0; updated by propagation
    raw_confidence: float  # original LLM-assigned confidence (immutable)
    depth: int = 0  # 0 = root, 1 = first-order hypotheses, etc.
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "node_type": self.node_type.value,
            "confidence": round(self.confidence, 4),
            "raw_confidence": round(self.raw_confidence, 4),
            "depth": self.depth,
            "metadata": self.metadata,
        }


@dataclass
class ReasoningEdge:
    source: str
    target: str
    edge_type: EdgeType
    weight: float  # 0.0–1.0; how strong is this relationship


class ReasoningGraph:
    """
    Directed graph of reasoning nodes.

    Build via:
        g = ReasoningGraph(question="Should I launch a Shopify store?")
        h1 = g.add_hypothesis("Market demand is high", confidence=0.7)
        h2 = g.add_hypothesis("Competition is too fierce", confidence=0.5)
        e1 = g.add_evidence("Google Trends shows 40% growth in AI tools", confidence=0.9)
        g.add_edge(e1, h1, EdgeType.SUPPORTS, weight=0.8)
        g.add_edge(e1, h2, EdgeType.CONTRADICTS, weight=0.4)
        g.propagate_confidence()
        winner = g.dominant_hypothesis()
    """

    def __init__(self, question: str) -> None:
        self.question = question
        self._nodes: dict[str, ReasoningNode] = {}
        self._edges: list[ReasoningEdge] = []
        self._graph = nx.DiGraph() if _NX_AVAILABLE else None

        # Root node
        root_id = "root"
        self._add_node(
            ReasoningNode(
                id=root_id,
                content=question,
                node_type=NodeType.ROOT,
                confidence=1.0,
                raw_confidence=1.0,
                depth=0,
            )
        )
        self._root_id = root_id

    # ── Node Operations ──────────────────────────────────────────────────

    def add_hypothesis(self, content: str, confidence: float = 0.5) -> str:
        node_id = f"h_{uuid.uuid4().hex[:8]}"
        node = ReasoningNode(
            id=node_id,
            content=content,
            node_type=NodeType.HYPOTHESIS,
            confidence=confidence,
            raw_confidence=confidence,
            depth=1,
        )
        self._add_node(node)
        self.add_edge(self._root_id, node_id, EdgeType.DERIVED, weight=0.5)
        return node_id

    def add_evidence(
        self,
        content: str,
        confidence: float = 0.8,
        depth: int = 2,
    ) -> str:
        node_id = f"e_{uuid.uuid4().hex[:8]}"
        node = ReasoningNode(
            id=node_id,
            content=content,
            node_type=NodeType.EVIDENCE,
            confidence=confidence,
            raw_confidence=confidence,
            depth=depth,
        )
        self._add_node(node)
        return node_id

    def add_sub_hypothesis(self, parent_id: str, content: str, confidence: float = 0.5) -> str:
        parent = self._nodes.get(parent_id)
        node_id = f"sh_{uuid.uuid4().hex[:8]}"
        depth = (parent.depth + 1) if parent else 2
        node = ReasoningNode(
            id=node_id,
            content=content,
            node_type=NodeType.HYPOTHESIS,
            confidence=confidence,
            raw_confidence=confidence,
            depth=depth,
        )
        self._add_node(node)
        self.add_edge(parent_id, node_id, EdgeType.REFINES, weight=0.6)
        return node_id

    def promote_to_conclusion(self, hypothesis_id: str) -> str:
        """Elevate the strongest hypothesis to a CONCLUSION node."""
        node = self._nodes.get(hypothesis_id)
        if not node:
            raise ValueError(f"Node {hypothesis_id} not found")
        conc_id = f"conc_{uuid.uuid4().hex[:6]}"
        conc = ReasoningNode(
            id=conc_id,
            content=node.content,
            node_type=NodeType.CONCLUSION,
            confidence=node.confidence,
            raw_confidence=node.raw_confidence,
            depth=node.depth + 1,
        )
        self._add_node(conc)
        self.add_edge(hypothesis_id, conc_id, EdgeType.DERIVED, weight=1.0)
        return conc_id

    # ── Edge Operations ──────────────────────────────────────────────────

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        weight: float = 0.5,
    ) -> None:
        edge = ReasoningEdge(source=source_id, target=target_id, edge_type=edge_type, weight=weight)
        self._edges.append(edge)
        if self._graph is not None:
            self._graph.add_edge(
                source_id,
                target_id,
                edge_type=edge_type.value,
                weight=weight,
            )

    # ── Confidence Propagation ────────────────────────────────────────────

    def propagate_confidence(self) -> None:
        """
        Propagate confidence through the reasoning graph.

        Algorithm:
          1. Start with raw_confidence on all nodes.
          2. For each SUPPORTS edge: target.confidence += source.confidence * weight * 0.3
          3. For each CONTRADICTS edge: target.confidence -= source.confidence * weight * 0.3
          4. Clamp all confidences to [0.05, 0.99].
          5. Repeat for 2 iterations (most graphs converge fast).
        """
        # Reset to raw values
        for node in self._nodes.values():
            node.confidence = node.raw_confidence

        for _ in range(2):
            for edge in self._edges:
                source = self._nodes.get(edge.source)
                target = self._nodes.get(edge.target)
                if not source or not target:
                    continue

                delta = source.confidence * edge.weight * 0.3
                if edge.edge_type == EdgeType.SUPPORTS:
                    target.confidence = min(0.99, target.confidence + delta)
                elif edge.edge_type == EdgeType.CONTRADICTS:
                    target.confidence = max(0.05, target.confidence - delta)

    def prune_weak_branches(self, threshold: float = 0.2) -> int:
        """Remove hypothesis nodes below confidence threshold. Returns count pruned."""
        to_remove = [
            nid
            for nid, node in self._nodes.items()
            if node.node_type == NodeType.HYPOTHESIS and node.confidence < threshold
        ]
        for nid in to_remove:
            del self._nodes[nid]
            self._edges = [e for e in self._edges if e.source != nid and e.target != nid]
            if self._graph is not None and self._graph.has_node(nid):
                self._graph.remove_node(nid)
        return len(to_remove)

    # ── Query ────────────────────────────────────────────────────────────

    def hypotheses(self) -> list[ReasoningNode]:
        return sorted(
            [n for n in self._nodes.values() if n.node_type == NodeType.HYPOTHESIS],
            key=lambda n: n.confidence,
            reverse=True,
        )

    def dominant_hypothesis(self) -> ReasoningNode | None:
        hyps = self.hypotheses()
        return hyps[0] if hyps else None

    def evidence_for(self, hypothesis_id: str) -> list[ReasoningNode]:
        supporting = []
        for edge in self._edges:
            if edge.target == hypothesis_id and edge.edge_type == EdgeType.SUPPORTS:
                node = self._nodes.get(edge.source)
                if node and node.node_type == NodeType.EVIDENCE:
                    supporting.append(node)
        return supporting

    def evidence_against(self, hypothesis_id: str) -> list[ReasoningNode]:
        contradicting = []
        for edge in self._edges:
            if edge.target == hypothesis_id and edge.edge_type == EdgeType.CONTRADICTS:
                node = self._nodes.get(edge.source)
                if node and node.node_type == NodeType.EVIDENCE:
                    contradicting.append(node)
        return contradicting

    def best_path(self, to_id: str | None = None) -> list[ReasoningNode]:
        """Return the highest-confidence reasoning path from root to a node."""
        if not _NX_AVAILABLE or self._graph is None:
            return list(self._nodes.values())

        target = to_id or (self.dominant_hypothesis().id if self.dominant_hypothesis() else None)
        if not target:
            return []

        try:
            path_ids = nx.shortest_path(
                self._graph,
                source=self._root_id,
                target=target,
                weight=lambda u, v, d: 1.0 - d.get("weight", 0.5),
            )
            return [self._nodes[nid] for nid in path_ids if nid in self._nodes]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def centrality_scores(self) -> dict[str, float]:
        """PageRank-like centrality — most-referenced nodes are most important."""
        if not _NX_AVAILABLE or self._graph is None:
            return {nid: n.confidence for nid, n in self._nodes.items()}
        try:
            return nx.pagerank(self._graph, weight="weight")
        except Exception:
            return {}

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "edge_type": e.edge_type.value,
                    "weight": e.weight,
                }
                for e in self._edges
            ],
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
        }

    def summary(self) -> str:
        winner = self.dominant_hypothesis()
        hyps = self.hypotheses()
        lines = [
            f"Question: {self.question}",
            f"Hypotheses explored: {len(hyps)}",
            f"Evidence nodes: {sum(1 for n in self._nodes.values() if n.node_type == NodeType.EVIDENCE)}",
        ]
        if winner:
            lines.append(f"Dominant: [{winner.confidence:.0%}] {winner.content}")
            for e in self.evidence_for(winner.id):
                lines.append(f"  + {e.content}")
            for e in self.evidence_against(winner.id):
                lines.append(f"  - {e.content}")
        return "\n".join(lines)

    # ── Internal ─────────────────────────────────────────────────────────

    def _add_node(self, node: ReasoningNode) -> None:
        self._nodes[node.id] = node
        if self._graph is not None:
            self._graph.add_node(
                node.id,
                content=node.content,
                node_type=node.node_type.value,
                confidence=node.confidence,
            )
