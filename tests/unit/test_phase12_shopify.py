"""Phase 12 tests — Shopify Growth Engine (ProductSEOOptimizer, ShopifyFunnelEngine)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="SEO Title: Best Fitness Equipment — Shop Premium Quality Online\nMeta: Shop the best fitness equipment. Fast shipping. Order now!\nOptimized description follows with keyword-rich content."):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── Product SEO Optimizer ─────────────────────────────────────────────────────

class TestProductSEOOptimizer:
    @pytest.fixture
    def optimizer(self):
        with patch("apps.shopify.seo.product_seo.get_cache", return_value=_mock_cache()):
            with patch("apps.shopify.seo.product_seo.get_ai_client",
                       return_value=_mock_ai()):
                from apps.shopify.seo.product_seo import ProductSEOOptimizer
                return ProductSEOOptimizer()

    @pytest.mark.asyncio
    async def test_optimize_product_returns_seo(self, optimizer):
        from apps.shopify.seo.product_seo import ProductSEO
        seo = await optimizer.optimize_product("p1", "Fitness Band", "Fitness Band", "Great band", "fitness")
        assert isinstance(seo, ProductSEO)
        assert seo.seo_id

    @pytest.mark.asyncio
    async def test_optimize_product_has_optimized_title(self, optimizer):
        seo = await optimizer.optimize_product("p2", "Running Shoes", "Running Shoes", "Good shoes", "footwear")
        assert len(seo.optimized_title) > 0
        assert len(seo.optimized_title) <= 70

    @pytest.mark.asyncio
    async def test_optimize_product_has_meta_description(self, optimizer):
        seo = await optimizer.optimize_product("p3", "Protein Powder", "Protein", "Tasty", "supplements")
        assert len(seo.meta_description) > 0
        assert len(seo.meta_description) <= 160

    @pytest.mark.asyncio
    async def test_optimize_product_has_target_keywords(self, optimizer):
        seo = await optimizer.optimize_product("p4", "Yoga Mat", "Yoga Mat", "Non-slip", "sports")
        assert isinstance(seo.target_keywords, list)
        assert len(seo.target_keywords) >= 3

    @pytest.mark.asyncio
    async def test_optimize_product_has_secondary_keywords(self, optimizer):
        seo = await optimizer.optimize_product("p5", "Dumbbell Set", "Dumbbell", "Heavy", "fitness")
        assert isinstance(seo.secondary_keywords, list)
        assert len(seo.secondary_keywords) >= 5

    @pytest.mark.asyncio
    async def test_optimize_product_seo_score_in_range(self, optimizer):
        seo = await optimizer.optimize_product("p6", "Jump Rope", "Jump Rope", "Speed rope", "fitness")
        assert 0.0 < seo.seo_score <= 1.0

    @pytest.mark.asyncio
    async def test_optimize_product_has_traffic_boost_estimate(self, optimizer):
        seo = await optimizer.optimize_product("p7", "Resistance Bands", "Bands", "Elastic bands", "fitness")
        assert seo.estimated_traffic_boost_pct >= 0.0

    @pytest.mark.asyncio
    async def test_optimize_stores_in_memory(self, optimizer):
        await optimizer.optimize_product("p8", "Water Bottle", "Bottle", "BPA-free", "hydration")
        assert len(optimizer._optimizations) == 1

    @pytest.mark.asyncio
    async def test_bulk_optimize_returns_list(self, optimizer):
        products = [
            {"product_id": "a", "name": "Kettlebell", "title": "Kettlebell", "description": "Heavy", "category": "fitness"},
            {"product_id": "b", "name": "Pull-up Bar", "title": "Pull-up Bar", "description": "Steel", "category": "fitness"},
        ]
        results = await optimizer.bulk_optimize(products)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_bulk_optimize_each_item_is_seo(self, optimizer):
        from apps.shopify.seo.product_seo import ProductSEO
        products = [{"product_id": "x", "name": "Treadmill", "title": "", "description": "", "category": "cardio"}]
        results = await optimizer.bulk_optimize(products)
        assert all(isinstance(r, ProductSEO) for r in results)

    @pytest.mark.asyncio
    async def test_audit_keywords_returns_dict(self, optimizer):
        result = await optimizer.audit_keywords("fitness equipment")
        assert "commercial_keywords" in result
        assert "comparison_keywords" in result
        assert "long_tail" in result

    @pytest.mark.asyncio
    async def test_audit_keywords_has_niche(self, optimizer):
        result = await optimizer.audit_keywords("supplements")
        assert result["niche"] == "supplements"

    def test_seo_stats_empty(self, optimizer):
        stats = optimizer.seo_stats()
        assert "total_optimized" in stats
        assert stats["total_optimized"] == 0

    @pytest.mark.asyncio
    async def test_seo_stats_after_optimization(self, optimizer):
        await optimizer.optimize_product("s1", "Test Product", "Test", "Desc", "general")
        stats = optimizer.seo_stats()
        assert stats["total_optimized"] == 1
        assert stats["avg_seo_score"] > 0.0

    @pytest.mark.asyncio
    async def test_recent_optimizations_returns_list(self, optimizer):
        await optimizer.optimize_product("r1", "Product A", "A", "Desc A", "general")
        result = optimizer.recent_optimizations(limit=5)
        assert isinstance(result, list)
        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_multiple_optimizations_accumulate(self, optimizer):
        await optimizer.optimize_product("m1", "A", "A", "Desc", "general")
        await optimizer.optimize_product("m2", "B", "B", "Desc", "general")
        await optimizer.optimize_product("m3", "C", "C", "Desc", "general")
        assert len(optimizer._optimizations) == 3

    @pytest.mark.asyncio
    async def test_product_id_preserved(self, optimizer):
        seo = await optimizer.optimize_product("product-123", "Test", "Test", "Desc", "cat")
        assert seo.product_id == "product-123"


# ── Shopify Funnel Engine ─────────────────────────────────────────────────────

class TestShopifyFunnelEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.shopify.funnels.shopify_funnels.get_cache", return_value=_mock_cache()):
            with patch("apps.shopify.funnels.shopify_funnels.get_ai_client",
                       return_value=_mock_ai("EXCLUSIVE UPGRADE: Complete Your Bundle — Save 30% When You Add This Now!")):
                from apps.shopify.funnels.shopify_funnels import ShopifyFunnelEngine
                return ShopifyFunnelEngine()

    @pytest.mark.asyncio
    async def test_create_upsell_flow_returns_offer(self, engine):
        from apps.shopify.funnels.shopify_funnels import UpsellOffer
        offer = await engine.create_upsell_flow("Protein Powder", 39.99, "Premium Bundle", 79.99)
        assert isinstance(offer, UpsellOffer)
        assert offer.offer_id

    @pytest.mark.asyncio
    async def test_upsell_offer_has_headline(self, engine):
        offer = await engine.create_upsell_flow("Shoes", 89.0, "Insoles", 29.0)
        assert len(offer.headline) > 0

    @pytest.mark.asyncio
    async def test_upsell_offer_has_urgency_trigger(self, engine):
        offer = await engine.create_upsell_flow("Book", 19.0, "Audio Book", 29.0)
        assert len(offer.urgency_trigger) > 0

    @pytest.mark.asyncio
    async def test_upsell_offer_has_acceptance_rate(self, engine):
        offer = await engine.create_upsell_flow("Widget", 50.0, "Premium Widget", 80.0)
        assert 0 < offer.acceptance_rate_pct <= 35.0

    @pytest.mark.asyncio
    async def test_create_abandoned_cart_sequence_returns_funnel(self, engine):
        from apps.shopify.funnels.shopify_funnels import ShopifyFunnel
        funnel = await engine.create_abandoned_cart_sequence("Fitness Course", 197.0, 15.0)
        assert isinstance(funnel, ShopifyFunnel)
        assert funnel.funnel_id

    @pytest.mark.asyncio
    async def test_abandoned_cart_has_3_stages(self, engine):
        funnel = await engine.create_abandoned_cart_sequence("Watch", 299.0, 10.0)
        assert len(funnel.stages) == 3

    @pytest.mark.asyncio
    async def test_abandoned_cart_type_is_correct(self, engine):
        funnel = await engine.create_abandoned_cart_sequence("Supplement", 49.0, 20.0)
        assert funnel.funnel_type == "abandoned_cart"

    @pytest.mark.asyncio
    async def test_abandoned_cart_has_discount_stage(self, engine):
        funnel = await engine.create_abandoned_cart_sequence("Bag", 79.0, 10.0)
        final_stage = funnel.stages[-1]
        assert final_stage.get("discount") is True

    @pytest.mark.asyncio
    async def test_abandoned_cart_expected_cvr(self, engine):
        funnel = await engine.create_abandoned_cart_sequence("Gadget", 99.0, 15.0)
        assert funnel.expected_cvr_pct > 0.0

    @pytest.mark.asyncio
    async def test_create_landing_page_returns_funnel(self, engine):
        from apps.shopify.funnels.shopify_funnels import ShopifyFunnel
        funnel = await engine.create_landing_page("AI Tool", "Get 10x Results", "entrepreneurs", 99.0)
        assert isinstance(funnel, ShopifyFunnel)
        assert funnel.funnel_id

    @pytest.mark.asyncio
    async def test_landing_page_type_is_landing(self, engine):
        funnel = await engine.create_landing_page("Course", "Learn Fast", "beginners", 197.0)
        assert funnel.funnel_type == "landing"

    @pytest.mark.asyncio
    async def test_landing_page_has_headline(self, engine):
        funnel = await engine.create_landing_page("Membership", "Join Today", "creators")
        assert len(funnel.headline) > 0

    @pytest.mark.asyncio
    async def test_landing_page_has_stages(self, engine):
        funnel = await engine.create_landing_page("Software", "Free Trial", "developers")
        assert isinstance(funnel.stages, list)
        assert len(funnel.stages) >= 3

    @pytest.mark.asyncio
    async def test_optimize_checkout_returns_dict(self, engine):
        result = await engine.optimize_checkout("Running Shoes", ["high shipping cost", "confusing layout"])
        assert "fixes" in result
        assert "expected_cvr_lift_pct" in result

    @pytest.mark.asyncio
    async def test_optimize_checkout_has_fixes_list(self, engine):
        result = await engine.optimize_checkout("Widget", [])
        assert isinstance(result["fixes"], list)
        assert len(result["fixes"]) >= 3

    @pytest.mark.asyncio
    async def test_create_post_purchase_flow_returns_funnel(self, engine):
        from apps.shopify.funnels.shopify_funnels import ShopifyFunnel
        funnel = await engine.create_post_purchase_flow("Protein Bar", "health")
        assert isinstance(funnel, ShopifyFunnel)

    @pytest.mark.asyncio
    async def test_post_purchase_type(self, engine):
        funnel = await engine.create_post_purchase_flow("Book", "education")
        assert funnel.funnel_type == "post_purchase"

    @pytest.mark.asyncio
    async def test_post_purchase_has_3_emails(self, engine):
        funnel = await engine.create_post_purchase_flow("Course", "education")
        assert len(funnel.stages) == 3

    @pytest.mark.asyncio
    async def test_post_purchase_has_aov_lift(self, engine):
        funnel = await engine.create_post_purchase_flow("Membership", "fitness")
        assert funnel.expected_aov_lift_pct > 0.0

    def test_funnel_stats_has_required_keys(self, engine):
        stats = engine.funnel_stats()
        assert "total_funnels" in stats
        assert "total_upsells" in stats
        assert "by_type" in stats
        assert "avg_expected_cvr_pct" in stats

    @pytest.mark.asyncio
    async def test_funnels_accumulate(self, engine):
        await engine.create_abandoned_cart_sequence("A", 50.0)
        await engine.create_landing_page("B", "Offer", "audience")
        assert len(engine._funnels) == 2

    @pytest.mark.asyncio
    async def test_upsells_accumulate(self, engine):
        await engine.create_upsell_flow("A", 50.0, "B", 80.0)
        await engine.create_upsell_flow("C", 100.0, "D", 150.0)
        assert len(engine._upsells) == 2

    @pytest.mark.asyncio
    async def test_recent_funnels_returns_list(self, engine):
        await engine.create_landing_page("X", "Offer X", "audience")
        result = engine.recent_funnels(limit=5)
        assert isinstance(result, list)
        assert len(result) <= 5
