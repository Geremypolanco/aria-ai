"""
KnowledgeGraph — Relationship graph with Neo4j-compatible query interface.
Backend: NetworkX (in-process) with optional Neo4j cloud connection.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

try:
    import networkx as nx

    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False
    nx = None

try:
    from neo4j import GraphDatabase

    _NEO4J_AVAILABLE = True
except ImportError:
    _NEO4J_AVAILABLE = False

_KG_KEY = "memory:kg:v1"
_KG_TTL = 86400 * 90


class RelationType(StrEnum):
    IS_A = "IS_A"
    HAS = "HAS"
    USES = "USES"
    COMPETES_WITH = "COMPETES_WITH"
    TARGETS = "TARGETS"
    PRODUCES = "PRODUCES"
    INFLUENCES = "INFLUENCES"
    PART_OF = "PART_OF"
    RELATED_TO = "RELATED_TO"


@dataclass
class Entity:
    entity_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    entity_type: str = "concept"
    properties: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "entity_type": self.entity_type,
            "properties": self.properties,
            "created_at": self.created_at,
        }


@dataclass
class Relation:
    source_id: str
    target_id: str
    relation_type: RelationType
    weight: float = 1.0
    properties: dict = field(default_factory=dict)


class KnowledgeGraph:
    """
    In-process knowledge graph using NetworkX.
    Falls back gracefully when networkx not available.
    Can connect to Neo4j when NEO4J_URI env var is set.
    """

    def __init__(self):
        self._graph = nx.DiGraph() if _NX_AVAILABLE else None
        self._entities: dict[str, Entity] = {}
        # dict-backend fallback used when networkx isn't installed — keeps
        # the graph fully functional instead of silently returning empty
        # results (the "dict" backend name was previously aspirational only).
        self._relations: list[dict] = []
        self._neo4j_driver = None
        self._backend = "networkx" if _NX_AVAILABLE else "dict"
        self._init_neo4j()

    def _init_neo4j(self) -> None:
        if not _NEO4J_AVAILABLE:
            return
        import os

        uri = os.environ.get("NEO4J_URI", "")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "")
        if uri and password:
            try:
                self._neo4j_driver = GraphDatabase.driver(uri, auth=(user, password))
                self._backend = "neo4j"
            except Exception:
                self._neo4j_driver = None

    def add_entity(
        self, name: str, entity_type: str = "concept", properties: dict = None
    ) -> Entity:
        if properties is None:
            properties = {}
        entity = Entity(name=name, entity_type=entity_type, properties=properties)
        self._entities[entity.entity_id] = entity
        if self._graph is not None:
            self._graph.add_node(entity.entity_id, name=name, entity_type=entity_type, **properties)
        return entity

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        weight: float = 1.0,
        properties: dict = None,
    ) -> bool:
        if properties is None:
            properties = {}
        if source_id not in self._entities or target_id not in self._entities:
            return False
        if self._graph is not None:
            self._graph.add_edge(
                source_id,
                target_id,
                relation=relation_type.value,
                weight=weight,
                **properties,
            )
        else:
            self._relations.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "relation": relation_type.value,
                    "weight": weight,
                    **properties,
                }
            )
        return True

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def find_by_name(self, name: str) -> list[Entity]:
        return [e for e in self._entities.values() if name.lower() in e.name.lower()]

    def neighbors(self, entity_id: str, relation_type: RelationType | None = None) -> list[Entity]:
        if self._graph is not None:
            neighbors = []
            for _, target, data in self._graph.out_edges(entity_id, data=True):
                if relation_type is None or data.get("relation") == relation_type.value:
                    entity = self._entities.get(target)
                    if entity:
                        neighbors.append(entity)
            return neighbors
        neighbors = []
        for r in self._relations:
            if r["source"] == entity_id and (
                relation_type is None or r["relation"] == relation_type.value
            ):
                entity = self._entities.get(r["target"])
                if entity:
                    neighbors.append(entity)
        return neighbors

    def shortest_path(self, source_id: str, target_id: str) -> list[Entity]:
        if self._graph is not None:
            try:
                import networkx as nx

                path_ids = nx.shortest_path(self._graph, source_id, target_id)
                return [self._entities[nid] for nid in path_ids if nid in self._entities]
            except Exception:
                return []
        if source_id == target_id:
            return [self._entities[source_id]] if source_id in self._entities else []
        adjacency: dict[str, list[str]] = {}
        for r in self._relations:
            adjacency.setdefault(r["source"], []).append(r["target"])
        visited = {source_id}
        queue: deque[list[str]] = deque([[source_id]])
        while queue:
            path = queue.popleft()
            for neighbor in adjacency.get(path[-1], []):
                if neighbor == target_id:
                    full_path = [*path, neighbor]
                    return [self._entities[nid] for nid in full_path if nid in self._entities]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append([*path, neighbor])
        return []

    def central_entities(self, top_k: int = 10) -> list[tuple[Entity, float]]:
        """PageRank-based centrality."""
        if self._graph is None or not self._entities:
            return [(e, 1.0) for e in list(self._entities.values())[:top_k]]
        try:
            import networkx as nx

            scores = nx.pagerank(self._graph, weight="weight")
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
            return [(self._entities[nid], score) for nid, score in ranked if nid in self._entities]
        except Exception:
            return []

    def entity_cluster(self, entity_id: str, depth: int = 2) -> list[Entity]:
        """Get all entities within `depth` hops."""
        if self._graph is not None:
            try:
                subgraph_nodes = set()
                frontier = {entity_id}
                for _ in range(depth):
                    next_frontier = set()
                    for nid in frontier:
                        next_frontier.update(self._graph.successors(nid))
                        next_frontier.update(self._graph.predecessors(nid))
                    subgraph_nodes.update(frontier)
                    frontier = next_frontier
                subgraph_nodes.update(frontier)
                return [self._entities[nid] for nid in subgraph_nodes if nid in self._entities]
            except Exception:
                return []
        out_adj: dict[str, set[str]] = {}
        in_adj: dict[str, set[str]] = {}
        for r in self._relations:
            out_adj.setdefault(r["source"], set()).add(r["target"])
            in_adj.setdefault(r["target"], set()).add(r["source"])
        subgraph_nodes = set()
        frontier = {entity_id}
        for _ in range(depth):
            next_frontier = set()
            for nid in frontier:
                next_frontier.update(out_adj.get(nid, set()))
                next_frontier.update(in_adj.get(nid, set()))
            subgraph_nodes.update(frontier)
            frontier = next_frontier
        subgraph_nodes.update(frontier)
        return [self._entities[nid] for nid in subgraph_nodes if nid in self._entities]

    def summary(self) -> dict:
        if self._graph is not None:
            relation_count = len(self._graph.edges())
        else:
            relation_count = len(self._relations)
        return {
            "backend": self._backend,
            "entity_count": len(self._entities),
            "relation_count": relation_count,
            "neo4j_connected": self._neo4j_driver is not None,
            "networkx_available": _NX_AVAILABLE,
        }

    def to_dict(self) -> dict:
        if self._graph is not None:
            relations = [
                {
                    "source": str(u),
                    "target": str(v),
                    "relation": data.get("relation", ""),
                    "weight": data.get("weight", 1.0),
                }
                for u, v, data in self._graph.edges(data=True)
            ]
        else:
            relations = [
                {
                    "source": r["source"],
                    "target": r["target"],
                    "relation": r["relation"],
                    "weight": r["weight"],
                }
                for r in self._relations
            ]
        return {
            "entities": [e.to_dict() for e in self._entities.values()],
            "relations": relations,
        }


_kg_instance: KnowledgeGraph | None = None


def get_knowledge_graph() -> KnowledgeGraph:
    global _kg_instance
    if _kg_instance is None:
        _kg_instance = KnowledgeGraph()
    return _kg_instance
