"""
Tests for the Entity Registry (World Model).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


class TestEntityRegistry:
    @pytest.fixture
    def registry(self):
        from apps.core.world_model.entity_registry import EntityRegistry
        return EntityRegistry()

    @pytest.mark.asyncio
    async def test_register_returns_entity_id(self, registry):
        from apps.core.world_model.entity_registry import EntityType
        with patch.object(registry, "_persist_entity", new=AsyncMock()):
            eid = await registry.register("Geremy", EntityType.USER)
        assert isinstance(eid, str)
        assert eid.startswith("user_")

    @pytest.mark.asyncio
    async def test_register_custom_id(self, registry):
        from apps.core.world_model.entity_registry import EntityType
        with patch.object(registry, "_persist_entity", new=AsyncMock()):
            eid = await registry.register("Shopify", EntityType.TOOL, entity_id="tool_shopify")
        assert eid == "tool_shopify"

    @pytest.mark.asyncio
    async def test_get_entity_returns_registered(self, registry):
        from apps.core.world_model.entity_registry import EntityType
        with patch.object(registry, "_persist_entity", new=AsyncMock()):
            eid = await registry.register("ARIA", EntityType.AGENT, properties={"version": "2.0"})
        entity = registry.get_entity(eid)
        assert entity is not None
        assert entity.name == "ARIA"
        assert entity.properties["version"] == "2.0"

    @pytest.mark.asyncio
    async def test_get_entity_unknown_returns_none(self, registry):
        assert registry.get_entity("nonexistent-id") is None

    @pytest.mark.asyncio
    async def test_relate_creates_relationship(self, registry):
        from apps.core.world_model.entity_registry import EntityType, RelationType
        with patch.object(registry, "_persist_entity", new=AsyncMock()), \
             patch.object(registry, "_persist_relationships", new=AsyncMock()):
            uid = await registry.register("User", EntityType.USER)
            tid = await registry.register("Tool", EntityType.TOOL)
            await registry.relate(uid, tid, RelationType.USES)

        assert len(registry._relationships) == 1
        assert registry._relationships[0].source_id == uid
        assert registry._relationships[0].target_id == tid

    @pytest.mark.asyncio
    async def test_relate_no_duplicates(self, registry):
        from apps.core.world_model.entity_registry import EntityType, RelationType
        with patch.object(registry, "_persist_entity", new=AsyncMock()), \
             patch.object(registry, "_persist_relationships", new=AsyncMock()):
            uid = await registry.register("User", EntityType.USER)
            tid = await registry.register("Tool", EntityType.TOOL)
            await registry.relate(uid, tid, RelationType.USES)
            await registry.relate(uid, tid, RelationType.USES)  # duplicate

        assert len(registry._relationships) == 1

    @pytest.mark.asyncio
    async def test_get_neighbors_returns_related(self, registry):
        from apps.core.world_model.entity_registry import EntityType, RelationType
        with patch.object(registry, "_persist_entity", new=AsyncMock()), \
             patch.object(registry, "_persist_relationships", new=AsyncMock()):
            uid = await registry.register("Owner", EntityType.USER)
            pid = await registry.register("Project", EntityType.PROJECT)
            await registry.relate(uid, pid, RelationType.OWNS)

            neighbors = await registry.get_neighbors(uid, RelationType.OWNS)

        assert len(neighbors) == 1
        assert neighbors[0].id == pid

    @pytest.mark.asyncio
    async def test_get_neighbors_by_type_filter(self, registry):
        from apps.core.world_model.entity_registry import EntityType, RelationType
        with patch.object(registry, "_persist_entity", new=AsyncMock()), \
             patch.object(registry, "_persist_relationships", new=AsyncMock()):
            uid = await registry.register("User", EntityType.USER)
            p1 = await registry.register("Project1", EntityType.PROJECT)
            t1 = await registry.register("Tool1", EntityType.TOOL)
            await registry.relate(uid, p1, RelationType.OWNS)
            await registry.relate(uid, t1, RelationType.USES)

            owned = await registry.get_neighbors(uid, RelationType.OWNS)
            used = await registry.get_neighbors(uid, RelationType.USES)

        assert len(owned) == 1 and owned[0].id == p1
        assert len(used) == 1 and used[0].id == t1

    @pytest.mark.asyncio
    async def test_unrelate_removes_relationship(self, registry):
        from apps.core.world_model.entity_registry import EntityType, RelationType
        with patch.object(registry, "_persist_entity", new=AsyncMock()), \
             patch.object(registry, "_persist_relationships", new=AsyncMock()):
            uid = await registry.register("User", EntityType.USER)
            tid = await registry.register("Tool", EntityType.TOOL)
            await registry.relate(uid, tid, RelationType.USES)
            removed = await registry.unrelate(uid, tid, RelationType.USES)

        assert removed
        assert len(registry._relationships) == 0

    @pytest.mark.asyncio
    async def test_get_by_type(self, registry):
        from apps.core.world_model.entity_registry import EntityType
        with patch.object(registry, "_persist_entity", new=AsyncMock()):
            await registry.register("Tool1", EntityType.TOOL)
            await registry.register("Tool2", EntityType.TOOL)
            await registry.register("User1", EntityType.USER)

        tools = registry.get_by_type(EntityType.TOOL)
        users = registry.get_by_type(EntityType.USER)
        assert len(tools) == 2
        assert len(users) == 1

    @pytest.mark.asyncio
    async def test_deactivate_hides_entity(self, registry):
        from apps.core.world_model.entity_registry import EntityType
        with patch.object(registry, "_persist_entity", new=AsyncMock()):
            eid = await registry.register("Old Project", EntityType.PROJECT)
            await registry.deactivate(eid)

        active = registry.get_by_type(EntityType.PROJECT)
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_update_entity_changes_properties(self, registry):
        from apps.core.world_model.entity_registry import EntityType
        with patch.object(registry, "_persist_entity", new=AsyncMock()):
            eid = await registry.register("Tool", EntityType.TOOL, properties={"v": 1})
            await registry.update_entity(eid, v=2, new_prop="hello")

        entity = registry.get_entity(eid)
        assert entity.properties["v"] == 2
        assert entity.properties["new_prop"] == "hello"

    def test_entity_serialization_roundtrip(self):
        from apps.core.world_model.entity_registry import Entity, EntityType
        entity = Entity(
            id="test_id", name="TestTool",
            entity_type=EntityType.TOOL,
            properties={"api_available": True},
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        d = entity.to_dict()
        restored = Entity.from_dict(d)
        assert restored.id == entity.id
        assert restored.entity_type == EntityType.TOOL
        assert restored.properties["api_available"] is True

    def test_summary_counts_active_entities(self):
        from apps.core.world_model.entity_registry import EntityRegistry, Entity, EntityType
        from datetime import datetime, timezone
        reg = EntityRegistry()
        now = datetime.now(timezone.utc).isoformat()
        for et in [EntityType.USER, EntityType.TOOL, EntityType.TOOL]:
            eid = f"test_{et.value}_{len(reg._entities)}"
            reg._entities[eid] = Entity(
                id=eid, name="x", entity_type=et,
                properties={}, created_at=now, updated_at=now,
            )
        summary = reg.summary()
        assert summary["total_entities"] == 3
        assert summary["by_type"]["tool"] == 2
        assert summary["by_type"]["user"] == 1
