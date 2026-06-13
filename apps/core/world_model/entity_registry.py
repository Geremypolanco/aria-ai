"""
ARIA World Model — Entity Registry and Relationship Graph.

ARIA maintains a persistent model of reality:
  - Entities: the things that exist (users, projects, tools, goals, constraints)
  - Relationships: how entities connect (owns, uses, depends_on, conflicts_with)
  - Topology: the full graph of how ARIA's world is structured

This is NOT a knowledge base. It is ARIA's self-model:
  - "I know user X owns project Y"
  - "Project Y uses tool Z"
  - "Goal A blocks Goal B"
  - "Tool Z has constraint: max 100 calls/day"

Without this, ARIA makes the same strategic mistakes repeatedly.
With this, ARIA reasons about consequences before acting.

Design:
  - Entities live in a typed registry (Redis-backed)
  - Relationships form a NetworkX graph for traversal and path-finding
  - The world model is updated by agents as they learn new facts
  - Queries return subgraphs, shortest paths, dependency chains
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("aria.world_model")

ENTITY_TTL = 86400 * 90  # 90 days


class EntityType(str, Enum):
    USER = "user"
    PROJECT = "project"
    TOOL = "tool"
    GOAL = "goal"
    CONSTRAINT = "constraint"
    INFRASTRUCTURE = "infrastructure"
    AGENT = "agent"
    INTEGRATION = "integration"
    REVENUE_STREAM = "revenue_stream"


class RelationType(str, Enum):
    OWNS = "owns"
    USES = "uses"
    DEPENDS_ON = "depends_on"
    CONFLICTS_WITH = "conflicts_with"
    RUNS_ON = "runs_on"
    IMPLEMENTS = "implements"
    BLOCKS = "blocks"
    ENABLES = "enables"
    MONITORS = "monitors"
    PRODUCES = "produces"


@dataclass
class Entity:
    id: str
    name: str
    entity_type: EntityType
    properties: dict[str, Any]
    created_at: str
    updated_at: str
    confidence: float = 1.0       # how certain ARIA is this entity exists
    active: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entity_type"] = self.entity_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Entity":
        d = dict(d)
        d["entity_type"] = EntityType(d["entity_type"])
        return cls(**d)

    def update(self, **props) -> None:
        self.properties.update(props)
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class Relationship:
    source_id: str
    target_id: str
    relation_type: RelationType
    weight: float = 1.0          # strength of relationship
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["relation_type"] = self.relation_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Relationship":
        d = dict(d)
        d["relation_type"] = RelationType(d["relation_type"])
        return cls(**d)


class EntityRegistry:
    """
    ARIA's world model — entity storage, relationship graph, topology queries.

    Usage:
        registry = EntityRegistry()

        # Register ARIA's owner
        user_id = await registry.register(
            name="Geremy", entity_type=EntityType.USER,
            properties={"timezone": "EST", "language": "es"}
        )

        # Register a tool
        tool_id = await registry.register(
            name="Shopify", entity_type=EntityType.TOOL,
            properties={"api_available": True}
        )

        # Link them
        await registry.relate(user_id, tool_id, RelationType.USES)

        # Query
        tools = await registry.get_neighbors(user_id, RelationType.USES)
    """

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._relationships: list[Relationship] = []
        self._graph = None
        self._loaded = False
        self._init_graph()

    def _init_graph(self) -> None:
        try:
            import networkx as nx
            self._graph = nx.DiGraph()
        except ImportError:
            logger.warning("[WorldModel] NetworkX not available — graph traversal disabled")

    # ── Registration ─────────────────────────────────────────────────────

    async def register(
        self,
        name: str,
        entity_type: EntityType,
        properties: dict[str, Any] | None = None,
        entity_id: str | None = None,
    ) -> str:
        eid = entity_id or f"{entity_type.value}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        entity = Entity(
            id=eid, name=name, entity_type=entity_type,
            properties=properties or {},
            created_at=now, updated_at=now,
        )
        self._entities[eid] = entity
        if self._graph is not None:
            self._graph.add_node(eid, name=name, entity_type=entity_type.value)

        await self._persist_entity(entity)
        logger.debug("[WorldModel] Registered %s: %s (%s)", entity_type.value, name, eid)
        return eid

    async def update_entity(self, entity_id: str, **props) -> bool:
        entity = self._entities.get(entity_id)
        if not entity:
            return False
        entity.update(**props)
        if self._graph is not None:
            for k, v in props.items():
                self._graph.nodes[entity_id][k] = v
        await self._persist_entity(entity)
        return True

    async def deactivate(self, entity_id: str) -> bool:
        entity = self._entities.get(entity_id)
        if not entity:
            return False
        entity.active = False
        entity.updated_at = datetime.now(timezone.utc).isoformat()
        await self._persist_entity(entity)
        return True

    # ── Relationships ─────────────────────────────────────────────────────

    async def relate(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        weight: float = 1.0,
        **props,
    ) -> None:
        # Avoid duplicates
        existing = any(
            r.source_id == source_id and r.target_id == target_id
            and r.relation_type == relation_type
            for r in self._relationships
        )
        if existing:
            return

        rel = Relationship(
            source_id=source_id, target_id=target_id,
            relation_type=relation_type, weight=weight,
            properties=props,
        )
        self._relationships.append(rel)
        if self._graph is not None:
            self._graph.add_edge(
                source_id, target_id,
                relation_type=relation_type.value, weight=weight,
            )
        await self._persist_relationships()

    async def unrelate(self, source_id: str, target_id: str, relation_type: RelationType) -> bool:
        before = len(self._relationships)
        self._relationships = [
            r for r in self._relationships
            if not (r.source_id == source_id and r.target_id == target_id
                    and r.relation_type == relation_type)
        ]
        if self._graph is not None and self._graph.has_edge(source_id, target_id):
            self._graph.remove_edge(source_id, target_id)
        return len(self._relationships) < before

    # ── Queries ───────────────────────────────────────────────────────────

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def get_by_name(self, name: str, entity_type: EntityType | None = None) -> list[Entity]:
        return [
            e for e in self._entities.values()
            if e.name.lower() == name.lower() and e.active
            and (entity_type is None or e.entity_type == entity_type)
        ]

    def get_by_type(self, entity_type: EntityType) -> list[Entity]:
        return [e for e in self._entities.values() if e.entity_type == entity_type and e.active]

    async def get_neighbors(
        self, entity_id: str,
        relation_type: RelationType | None = None,
        direction: str = "out",  # "out", "in", "both"
    ) -> list[Entity]:
        if direction in ("out", "both"):
            targets = [
                r.target_id for r in self._relationships
                if r.source_id == entity_id
                and (relation_type is None or r.relation_type == relation_type)
            ]
        else:
            targets = []

        if direction in ("in", "both"):
            sources = [
                r.source_id for r in self._relationships
                if r.target_id == entity_id
                and (relation_type is None or r.relation_type == relation_type)
            ]
            targets.extend(sources)

        return [self._entities[tid] for tid in set(targets) if tid in self._entities]

    async def find_path(
        self, source_id: str, target_id: str
    ) -> list[Entity]:
        """Shortest path between two entities through the relationship graph."""
        if not self._graph:
            return []
        try:
            import networkx as nx
            path_ids = nx.shortest_path(self._graph, source=source_id, target=target_id)
            return [self._entities[eid] for eid in path_ids if eid in self._entities]
        except Exception:
            return []

    async def get_subgraph(self, entity_id: str, depth: int = 2) -> dict:
        """Return ego graph (entity + N-hop neighborhood)."""
        if not self._graph:
            return {"entity": self._entities.get(entity_id, {}).to_dict() if entity_id in self._entities else {}}
        try:
            import networkx as nx
            ego = nx.ego_graph(self._graph, entity_id, radius=depth)
            nodes = {nid: self._entities[nid].to_dict() for nid in ego.nodes if nid in self._entities}
            edges = [
                {"source": u, "target": v, **data}
                for u, v, data in ego.edges(data=True)
            ]
            return {"nodes": nodes, "edges": edges}
        except Exception:
            return {}

    async def dependency_chain(self, entity_id: str) -> list[Entity]:
        """All entities that entity_id depends on (transitively)."""
        result = []
        visited = set()
        queue = [entity_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            deps = await self.get_neighbors(current, RelationType.DEPENDS_ON, direction="out")
            result.extend(deps)
            queue.extend(d.id for d in deps)
        return result

    def summary(self) -> dict:
        by_type: dict[str, int] = {}
        for e in self._entities.values():
            if e.active:
                t = e.entity_type.value
                by_type[t] = by_type.get(t, 0) + 1
        return {
            "total_entities": sum(by_type.values()),
            "by_type": by_type,
            "total_relationships": len(self._relationships),
        }

    # ── Persistence ───────────────────────────────────────────────────────

    async def _persist_entity(self, entity: Entity) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                await cache.set(
                    f"aria:world:entity:{entity.id}",
                    json.dumps(entity.to_dict()),
                    ttl_seconds=ENTITY_TTL,
                )
        except Exception as exc:
            logger.debug("[WorldModel] Entity persist failed: %s", exc)

    async def _persist_relationships(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                data = [r.to_dict() for r in self._relationships[-200:]]  # keep last 200
                await cache.set(
                    "aria:world:relationships",
                    json.dumps(data),
                    ttl_seconds=ENTITY_TTL,
                )
        except Exception as exc:
            logger.debug("[WorldModel] Relationships persist failed: %s", exc)

    async def load(self) -> None:
        """Load entities and relationships from Redis on startup."""
        if self._loaded:
            return
        self._loaded = True
        # In production: scan Redis for aria:world:entity:* keys
        # For now, entities accumulate in-process
        logger.debug("[WorldModel] World model initialized")


_registry: Optional[EntityRegistry] = None


def get_entity_registry() -> EntityRegistry:
    global _registry
    if _registry is None:
        _registry = EntityRegistry()
    return _registry
