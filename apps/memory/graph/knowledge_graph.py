"""
KnowledgeGraph — Relationship graph with Neo4j-compatible query interface.
Backend: NetworkX (in-process) with optional Neo4j cloud connection.
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

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


class RelationType(str, Enum):
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

    def add_entity(self, name: str, entity_type: str = "concept", properties: dict = {}) -> Entity:
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
        properties: dict = {},
    ) -> bool:
        if source_id not in self._entities or target_id not in self._entities:
            return False
        if self._graph is not None:
            self._graph.add_edge(
                source_id, target_id,
                relation=relation_type.value,
                weight=weight,
                **properties,
            )
        return True

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def find_by_name(self, name: str) -> list[Entity]:
        return [e for e in self._entities.values() if name.lower() in e.name.lower()]

    def neighbors(self, entity_id: str, relation_type: Optional[RelationType] = None) -> list[Entity]:
        if self._graph is None:
            return []
        neighbors = []
        for _, target, data in self._graph.out_edges(entity_id, data=True):
            if relation_type is None or data.get("relation") == relation_type.value:
                entity = self._entities.get(target)
                if entity:
                    neighbors.append(entity)
        return neighbors

    def shortest_path(self, source_id: str, target_id: str) -> list[Entity]:
        if self._graph is None:
            return []
        try:
            import networkx as nx
            path_ids = nx.shortest_path(self._graph, source_id, target_id)
            return [self._entities[nid] for nid in path_ids if nid in self._entities]
        except Exception:
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
        if self._graph is None:
            return []
        try:
            import networkx as nx
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

    def summary(self) -> dict:
        return {
            "backend": self._backend,
            "entity_count": len(self._entities),
            "relation_count": len(self._graph.edges()) if self._graph is not None else 0,
            "neo4j_connected": self._neo4j_driver is not None,
            "networkx_available": _NX_AVAILABLE,
        }

    def to_dict(self) -> dict:
        return {
            "entities": [e.to_dict() for e in self._entities.values()],
            "relations": [
                {
                    "source": str(u),
                    "target": str(v),
                    "relation": data.get("relation", ""),
                    "weight": data.get("weight", 1.0),
                }
                for u, v, data in (self._graph.edges(data=True) if self._graph else [])
            ],
        }


_kg_instance: Optional[KnowledgeGraph] = None


def get_knowledge_graph() -> KnowledgeGraph:
    global _kg_instance
    if _kg_instance is None:
        _kg_instance = KnowledgeGraph()
    return _kg_instance
