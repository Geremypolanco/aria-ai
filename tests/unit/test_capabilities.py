"""Unit tests for the Capability Registry and catalog."""

from __future__ import annotations

import pytest

from apps.core.capabilities.catalog import seed_registry
from apps.core.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    CapabilityStatus,
    Quality,
    get_capability_registry,
)


def _fresh() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    seed_registry(reg)
    return reg


class TestRegistryCore:
    def test_register_and_get(self):
        reg = CapabilityRegistry()
        reg.register(Capability(key="x.y", category="x", provider="p"))
        assert reg.get("x.y") is not None
        assert reg.get("x.y").provider == "p"

    def test_by_category(self):
        reg = CapabilityRegistry()
        reg.register(Capability(key="a.1", category="a", provider="p1"))
        reg.register(Capability(key="a.2", category="a", provider="p2"))
        reg.register(Capability(key="b.1", category="b", provider="p3"))
        assert len(reg.by_category("a")) == 2
        assert len(reg.by_category("b")) == 1

    def test_select_prefers_verified_and_quality(self):
        reg = CapabilityRegistry()
        reg.register(Capability(key="pub.low", category="pub", provider="low", quality=Quality.LOW))
        reg.register(
            Capability(
                key="pub.best",
                category="pub",
                provider="best",
                quality=Quality.HIGH,
                verified=True,
            )
        )
        best = reg.select("pub")
        assert best is not None
        assert best.key == "pub.best"

    def test_select_ignores_non_active(self):
        reg = CapabilityRegistry()
        reg.register(
            Capability(key="p.down", category="p", provider="d", status=CapabilityStatus.DOWN)
        )
        assert reg.select("p") is None

    def test_rank_returns_fallbacks(self):
        reg = CapabilityRegistry()
        reg.register(Capability(key="c.a", category="c", provider="a", quality=Quality.HIGH))
        reg.register(Capability(key="c.b", category="c", provider="b", quality=Quality.LOW))
        ranked = reg.rank("c")
        assert [r.key for r in ranked] == ["c.a", "c.b"]


class TestHealth:
    async def test_check_none_when_no_healthcheck(self):
        reg = CapabilityRegistry()
        reg.register(Capability(key="n.h", category="n", provider="p"))
        assert await reg.check("n.h") is None

    async def test_check_runs_healthcheck(self):
        async def ok():
            return True

        reg = CapabilityRegistry()
        reg.register(Capability(key="h.ok", category="h", provider="p", health_check=ok))
        assert await reg.check("h.ok") is True

    async def test_check_handles_raising_healthcheck(self):
        async def boom():
            raise RuntimeError("x")

        reg = CapabilityRegistry()
        reg.register(Capability(key="h.bad", category="h", provider="p", health_check=boom))
        assert await reg.check("h.bad") is False


class TestCatalog:
    def test_catalog_seeds_real_capabilities(self):
        reg = _fresh()
        # Revenue-critical capabilities must be present
        assert reg.get("payments.stripe") is not None
        assert reg.get("publishing.linkedin") is not None
        assert reg.get("fulfillment.digital_delivery") is not None

    def test_catalog_has_explicit_gaps(self):
        reg = _fresh()
        gaps = reg.missing()
        gap_keys = {g["key"] for g in gaps}
        assert "media.image_generation" in gap_keys
        assert "ads.paid_traffic" in gap_keys
        # every gap must be PLANNED
        assert all(g["status"] == "planned" for g in gaps)

    def test_matrix_and_summary_shapes(self):
        reg = _fresh()
        matrix = reg.matrix()
        assert isinstance(matrix, list) and len(matrix) > 5
        summary = reg.summary()
        assert summary["total"] == len(matrix)
        assert "active" in summary and "gaps" in summary

    def test_no_secret_values_leak(self):
        # requires must list NAMES, never look like actual secret values
        reg = _fresh()
        for c in reg.all():
            for r in c.requires:
                assert not r.startswith("sk_")
                assert not r.startswith("Bearer ")


class TestSingleton:
    def test_singleton_seeded(self):
        reg = get_capability_registry()
        assert reg.get("payments.stripe") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
