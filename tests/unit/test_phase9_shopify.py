"""
Phase 9 tests — Shopify Revenue Engine.
Covers: FlashSaleEngine, BundleGenerator, PricingOptimizer,
        CartRecoveryEngine, ProductRecommender.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Bundle recommendation: Complete Starter Kit"):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ---------------------------------------------------------------------------
# 1. TestFlashSaleEngine  (8 tests)
# ---------------------------------------------------------------------------


class TestFlashSaleEngine:

    @pytest.fixture
    def engine(self):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            from apps.shopify.offers.flash_sale_engine import FlashSaleEngine

            e = FlashSaleEngine()
            e._loaded = True
            return e

    @pytest.mark.asyncio
    async def test_create_sale_returns_flash_sale(self, engine):
        from apps.shopify.offers.flash_sale_engine import FlashSale

        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            sale = await engine.create_sale(
                name="Summer Sale",
                product_ids=["p1", "p2"],
                discount_pct=0.20,
                duration_hours=24,
                prices={"p1": 100.0, "p2": 50.0},
            )
        assert isinstance(sale, FlashSale)
        assert sale.sale_id is not None
        assert sale.name == "Summer Sale"
        assert sale.discount_pct == 0.20

    @pytest.mark.asyncio
    async def test_is_active_returns_bool(self, engine):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            sale = await engine.create_sale(
                name="Active Sale",
                product_ids=["p1"],
                discount_pct=0.10,
                duration_hours=24,
            )
        # Status is "planned" — not active yet
        assert sale.is_active() is False
        # Manually set status to active
        sale.status = "active"
        assert sale.is_active() is True

    @pytest.mark.asyncio
    async def test_urgency_level_returns_string(self, engine):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            sale = await engine.create_sale(
                name="Urgency Test",
                product_ids=["p1"],
                discount_pct=0.15,
                duration_hours=1,  # less than 2h → critical
            )
        level = sale.urgency_level()
        assert isinstance(level, str)
        assert level in {"critical", "high", "medium", "low"}

    @pytest.mark.asyncio
    async def test_urgency_level_critical_when_less_than_2h(self, engine):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            sale = await engine.create_sale(
                name="Critical Sale",
                product_ids=["p1"],
                discount_pct=0.25,
                duration_hours=1,
            )
        assert sale.urgency_level() == "critical"

    @pytest.mark.asyncio
    async def test_create_urgency_copy_returns_string(self, engine):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            sale = await engine.create_sale(
                name="Flash Deal",
                product_ids=["p1"],
                discount_pct=0.30,
                duration_hours=6,
            )
        with patch("apps.shopify.offers.flash_sale_engine.get_ai_client", return_value=_mock_ai("Only 6h left! Save 30%")):
            copy = await engine.create_urgency_copy(sale)
        assert isinstance(copy, str)
        assert len(copy) > 0

    @pytest.mark.asyncio
    async def test_activate_sale_updates_status(self, engine):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            sale = await engine.create_sale(
                name="To Activate",
                product_ids=["p3"],
                discount_pct=0.10,
            )
            result = await engine.activate_sale(sale.sale_id)
        assert result is True
        stored = next((s for s in engine._sales if s["sale_id"] == sale.sale_id), None)
        assert stored is not None
        assert stored["status"] == "active"

    @pytest.mark.asyncio
    async def test_end_sale_records_revenue(self, engine):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            sale = await engine.create_sale(
                name="Ending Sale",
                product_ids=["p4"],
                discount_pct=0.20,
            )
            ended = await engine.end_sale(sale.sale_id, revenue=500.0, units=10)
        assert ended is True
        stored = next((s for s in engine._sales if s["sale_id"] == sale.sale_id), None)
        assert stored["status"] == "ended"
        assert stored["revenue_generated"] == 500.0
        assert stored["units_sold"] == 10

    @pytest.mark.asyncio
    async def test_sales_analytics_returns_dict(self, engine):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            await engine.create_sale("S1", ["p1"], 0.20)
            await engine.create_sale("S2", ["p2"], 0.30)
        stats = engine.sales_analytics()
        assert isinstance(stats, dict)
        assert "total_sales" in stats
        assert "total_revenue" in stats
        assert "avg_discount" in stats
        assert "active_count" in stats
        assert stats["total_sales"] == 2

    @pytest.mark.asyncio
    async def test_hours_remaining_positive(self, engine):
        with patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_mock_cache()):
            sale = await engine.create_sale(
                name="Long Sale",
                product_ids=["p5"],
                discount_pct=0.10,
                duration_hours=48,
            )
        assert sale.hours_remaining() > 0


# ---------------------------------------------------------------------------
# 2. TestBundleGenerator  (7 tests)
# ---------------------------------------------------------------------------


class TestBundleGenerator:

    @pytest.fixture
    def generator(self):
        with patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_mock_cache()):
            from apps.shopify.bundles.bundle_generator import BundleGenerator

            g = BundleGenerator()
            g._loaded = True
            return g

    @pytest.fixture
    def sample_products(self):
        return [
            {"id": "p1", "title": "Widget A", "price": 29.99, "category": "widgets"},
            {"id": "p2", "title": "Widget B", "price": 19.99, "category": "widgets"},
            {"id": "p3", "title": "Gadget C", "price": 49.99, "category": "gadgets"},
        ]

    @pytest.mark.asyncio
    async def test_create_bundle_returns_product_bundle(self, generator, sample_products):
        from apps.shopify.bundles.bundle_generator import ProductBundle

        with (
            patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_mock_cache()),
            patch("apps.shopify.bundles.bundle_generator.get_ai_client", return_value=_mock_ai("NAME: Super Bundle\nDESC: Great deal\nCTA: Buy Now")),
        ):
            bundle = await generator.create_bundle(sample_products[:2], bundle_type="complementary")

        assert isinstance(bundle, ProductBundle)
        assert bundle.bundle_id is not None
        assert len(bundle.product_ids) == 2

    @pytest.mark.asyncio
    async def test_create_bundle_savings_pct_positive(self, generator, sample_products):
        with (
            patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_mock_cache()),
            patch("apps.shopify.bundles.bundle_generator.get_ai_client", return_value=_mock_ai("NAME: Kit\nDESC: Save more\nCTA: Get It")),
        ):
            bundle = await generator.create_bundle(sample_products[:2], discount_pct=0.15)
        assert bundle.savings_pct > 0
        assert bundle.savings == round(bundle.individual_total - bundle.bundle_price, 2)

    @pytest.mark.asyncio
    async def test_bundle_type_in_valid_values(self, generator, sample_products):
        with (
            patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_mock_cache()),
            patch("apps.shopify.bundles.bundle_generator.get_ai_client", return_value=_mock_ai("NAME: Starter Kit\nDESC: Begin here\nCTA: Start Now")),
        ):
            bundle = await generator.create_bundle(
                sample_products[:2], bundle_type="starter"
            )
        assert bundle.bundle_type in {"complementary", "quantity", "starter", "premium"}

    @pytest.mark.asyncio
    async def test_generate_smart_bundles_returns_list(self, generator, sample_products):
        catalog = sample_products + [
            {"id": "p4", "title": "Tool D", "price": 39.99, "category": "tools"},
            {"id": "p5", "title": "Tool E", "price": 24.99, "category": "tools"},
        ]
        with (
            patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_mock_cache()),
            patch("apps.shopify.bundles.bundle_generator.get_ai_client", return_value=_mock_ai("NAME: Smart Bundle\nDESC: Perfect combo\nCTA: Bundle It")),
        ):
            bundles = await generator.generate_smart_bundles(catalog, count=3)
        assert isinstance(bundles, list)
        assert len(bundles) <= 3

    @pytest.mark.asyncio
    async def test_aov_optimization_bundles_returns_3(self, generator, sample_products):
        catalog = sample_products
        with (
            patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_mock_cache()),
            patch("apps.shopify.bundles.bundle_generator.get_ai_client", return_value=_mock_ai("NAME: AOV Bundle\nDESC: Boost your order\nCTA: Add to Cart")),
        ):
            bundles = await generator.aov_optimization_bundles(
                avg_order_value=50.0, catalog=catalog
            )
        assert isinstance(bundles, list)
        assert len(bundles) <= 3

    @pytest.mark.asyncio
    async def test_active_bundles_works(self, generator, sample_products):
        with (
            patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_mock_cache()),
            patch("apps.shopify.bundles.bundle_generator.get_ai_client", return_value=_mock_ai("NAME: B\nDESC: D\nCTA: C")),
        ):
            await generator.create_bundle(sample_products[:2])
        bundles = generator.active_bundles()
        assert isinstance(bundles, list)
        assert len(bundles) >= 1

    @pytest.mark.asyncio
    async def test_bundle_stats_returns_dict(self, generator, sample_products):
        with (
            patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_mock_cache()),
            patch("apps.shopify.bundles.bundle_generator.get_ai_client", return_value=_mock_ai("NAME: Stat Bundle\nDESC: Stats here\nCTA: Go")),
        ):
            await generator.create_bundle(sample_products[:2], bundle_type="starter")
        stats = generator.bundle_stats()
        assert isinstance(stats, dict)
        assert "total_bundles" in stats
        assert "avg_savings_pct" in stats
        assert "by_type" in stats
        assert stats["total_bundles"] >= 1


# ---------------------------------------------------------------------------
# 3. TestPricingOptimizer  (7 tests)
# ---------------------------------------------------------------------------


class TestPricingOptimizer:

    @pytest.fixture
    def optimizer(self):
        with patch("apps.shopify.revenue.pricing_optimizer.get_cache", return_value=_mock_cache()):
            from apps.shopify.revenue.pricing_optimizer import PricingOptimizer

            o = PricingOptimizer()
            o._loaded = True
            return o

    @pytest.mark.asyncio
    async def test_suggest_price_returns_dict_with_suggested_price(self, optimizer):
        with (
            patch("apps.shopify.revenue.pricing_optimizer.get_cache", return_value=_mock_cache()),
            patch(
                "apps.shopify.revenue.pricing_optimizer.get_ai_client",
                return_value=_mock_ai("PRICE: 29.99\nSTRATEGY: charm\nRATIONALE: .99 ending\nEXPECTED_CVR_CHANGE: 0.05"),
            ),
        ):
            result = await optimizer.suggest_price(
                product_id="p1", title="Widget", current_price=30.0
            )
        assert isinstance(result, dict)
        assert "suggested_price" in result
        assert isinstance(result["suggested_price"], (int, float))

    @pytest.mark.asyncio
    async def test_create_experiment_returns_pricing_experiment(self, optimizer):
        from apps.shopify.revenue.pricing_optimizer import PricingExperiment

        with patch("apps.shopify.revenue.pricing_optimizer.get_cache", return_value=_mock_cache()):
            exp = await optimizer.create_experiment(
                product_id="p1",
                title="Widget",
                control_price=30.0,
                strategy="charm",
            )
        assert isinstance(exp, PricingExperiment)
        assert exp.exp_id is not None
        assert exp.strategy == "charm"
        assert exp.status == "running"

    @pytest.mark.asyncio
    async def test_charm_price_has_99_ending(self, optimizer):
        with patch("apps.shopify.revenue.pricing_optimizer.get_cache", return_value=_mock_cache()):
            exp = await optimizer.create_experiment(
                product_id="p2",
                title="Gadget",
                control_price=50.0,
                strategy="charm",
            )
        # .99 ending
        assert str(exp.test_price).endswith(".99") or exp.test_price == pytest.approx(49.99, abs=0.01)

    @pytest.mark.asyncio
    async def test_conclude_experiment_records_conversions(self, optimizer):
        with patch("apps.shopify.revenue.pricing_optimizer.get_cache", return_value=_mock_cache()):
            exp = await optimizer.create_experiment("p3", "Tool", 20.0, "competitive")
            concluded = await optimizer.conclude_experiment(exp.exp_id, control_conv=10, test_conv=13)
        assert concluded.status == "concluded"
        assert concluded.control_conversions == 10
        assert concluded.test_conversions == 13
        assert concluded.winner != ""

    @pytest.mark.asyncio
    async def test_optimal_price_points_returns_5(self, optimizer):
        points = optimizer.optimal_price_points(100.0)
        assert isinstance(points, list)
        assert len(points) == 5

    @pytest.mark.asyncio
    async def test_pricing_insights_returns_dict(self, optimizer):
        insights = optimizer.pricing_insights()
        assert isinstance(insights, dict)
        assert "running_experiments" in insights
        assert "concluded_experiments" in insights
        assert "win_rate" in insights
        assert "avg_uplift" in insights

    @pytest.mark.asyncio
    async def test_experiment_has_valid_strategy(self, optimizer):
        valid_strategies = {"anchor", "charm", "premium", "competitive"}
        with patch("apps.shopify.revenue.pricing_optimizer.get_cache", return_value=_mock_cache()):
            for strat in valid_strategies:
                exp = await optimizer.create_experiment("px", "Product X", 40.0, strat)
                assert exp.strategy in valid_strategies


# ---------------------------------------------------------------------------
# 4. TestCartRecoveryEngine  (5 tests)
# ---------------------------------------------------------------------------


class TestCartRecoveryEngine:

    @pytest.fixture
    def engine(self):
        with patch("apps.shopify.revenue.cart_recovery.get_cache", return_value=_mock_cache()):
            from apps.shopify.revenue.cart_recovery import CartRecoveryEngine

            e = CartRecoveryEngine()
            e._loaded = True
            return e

    @pytest.fixture
    def sample_items(self):
        return [
            {"id": "p1", "title": "Widget A", "price": 29.99},
            {"id": "p2", "title": "Widget B", "price": 19.99},
        ]

    @pytest.mark.asyncio
    async def test_register_abandoned_cart_returns_cart(self, engine, sample_items):
        from apps.shopify.revenue.cart_recovery import AbandonedCart

        with patch("apps.shopify.revenue.cart_recovery.get_cache", return_value=_mock_cache()):
            cart = await engine.register_abandoned_cart(
                user_id="u1",
                email="user@example.com",
                items=sample_items,
                cart_value=49.98,
            )
        assert isinstance(cart, AbandonedCart)
        assert cart.cart_id is not None
        assert cart.user_id == "u1"
        assert cart.cart_value == 49.98

    @pytest.mark.asyncio
    async def test_generate_recovery_sequence_returns_3_emails(self, engine, sample_items):
        with (
            patch("apps.shopify.revenue.cart_recovery.get_cache", return_value=_mock_cache()),
            patch(
                "apps.shopify.revenue.cart_recovery.get_ai_client",
                return_value=_mock_ai("SUBJECT: Come back!\nBODY: Your cart is waiting."),
            ),
        ):
            cart = await engine.register_abandoned_cart(
                user_id="u2", email="u2@test.com", items=sample_items, cart_value=49.98
            )
            sequence = await engine.generate_recovery_sequence(cart)
        assert isinstance(sequence, list)
        assert len(sequence) == 3
        delays = [e["delay_hours"] for e in sequence]
        assert 1 in delays
        assert 24 in delays
        assert 72 in delays

    @pytest.mark.asyncio
    async def test_generate_sms_recovery_under_160_chars(self, engine, sample_items):
        with (
            patch("apps.shopify.revenue.cart_recovery.get_cache", return_value=_mock_cache()),
            patch(
                "apps.shopify.revenue.cart_recovery.get_ai_client",
                return_value=_mock_ai("Your cart is waiting! Complete your order: [link]"),
            ),
        ):
            cart = await engine.register_abandoned_cart(
                user_id="u3", email="u3@test.com", items=sample_items, cart_value=49.98
            )
            sms = await engine.generate_sms_recovery(cart)
        assert isinstance(sms, str)
        assert len(sms) <= 160

    @pytest.mark.asyncio
    async def test_recovery_stats_returns_dict_with_recovery_rate(self, engine, sample_items):
        with patch("apps.shopify.revenue.cart_recovery.get_cache", return_value=_mock_cache()):
            await engine.register_abandoned_cart(
                user_id="u4", email="u4@test.com", items=sample_items, cart_value=49.98
            )
        stats = engine.recovery_stats()
        assert isinstance(stats, dict)
        assert "total_abandoned" in stats
        assert "recovered" in stats
        assert "recovery_rate" in stats
        assert "revenue_recovered" in stats
        assert "avg_cart_value" in stats
        assert isinstance(stats["recovery_rate"], float)

    @pytest.mark.asyncio
    async def test_mark_recovered_updates_status(self, engine, sample_items):
        with patch("apps.shopify.revenue.cart_recovery.get_cache", return_value=_mock_cache()):
            cart = await engine.register_abandoned_cart(
                user_id="u5", email="u5@test.com", items=sample_items, cart_value=49.98
            )
            result = await engine.mark_recovered(cart.cart_id, revenue=49.98)
        assert result is True
        stored = next((c for c in engine._carts if c["cart_id"] == cart.cart_id), None)
        assert stored["status"] == "recovered"


# ---------------------------------------------------------------------------
# 5. TestProductRecommender  (5 tests)
# ---------------------------------------------------------------------------


class TestProductRecommender:

    @pytest.fixture
    def recommender(self):
        with patch("apps.shopify.revenue.product_recommender.get_cache", return_value=_mock_cache()):
            from apps.shopify.revenue.product_recommender import ProductRecommender

            r = ProductRecommender()
            r._loaded = True
            return r

    @pytest.fixture
    def catalog(self):
        return [
            {"id": "p1", "title": "Widget A", "price": 29.99, "category": "widgets", "tags": ["home", "lifestyle"]},
            {"id": "p2", "title": "Widget B", "price": 49.99, "category": "widgets", "tags": ["home"]},
            {"id": "p3", "title": "Gadget C", "price": 79.99, "category": "gadgets", "tags": ["tech"]},
            {"id": "p4", "title": "Gadget D", "price": 99.99, "category": "gadgets", "tags": ["tech", "premium"]},
            {"id": "p5", "title": "Tool E", "price": 19.99, "category": "tools", "tags": ["diy"]},
        ]

    @pytest.mark.asyncio
    async def test_record_interaction_updates_data(self, recommender):
        with patch("apps.shopify.revenue.product_recommender.get_cache", return_value=_mock_cache()):
            await recommender.record_interaction(user_id="u1", product_id="p1", interaction_type="view")
        assert "u1" in recommender._interaction_data
        assert "p1" in recommender._interaction_data["u1"]

    @pytest.mark.asyncio
    async def test_recommend_returns_recommendation_set(self, recommender, catalog):
        from apps.shopify.revenue.product_recommender import RecommendationSet

        with patch("apps.shopify.revenue.product_recommender.get_cache", return_value=_mock_cache()):
            result = await recommender.recommend(
                user_id="u2",
                context="homepage",
                catalog=catalog,
                limit=3,
            )
        assert isinstance(result, RecommendationSet)
        assert isinstance(result.recommended_ids, list)
        assert isinstance(result.scores, list)
        assert result.strategy in {"collaborative", "content", "trending", "upsell"}

    @pytest.mark.asyncio
    async def test_upsell_recommendations_returns_list(self, recommender, catalog):
        with patch("apps.shopify.revenue.product_recommender.get_cache", return_value=_mock_cache()):
            results = await recommender.upsell_recommendations(
                product_id="p1", product_price=29.99, catalog=catalog
            )
        assert isinstance(results, list)
        # All returned products should be in the 1.5x-2x price range
        for p in results:
            assert float(p.get("price", 0)) >= 29.99 * 1.5

    @pytest.mark.asyncio
    async def test_cross_sell_recommendations_returns_list(self, recommender, catalog):
        cart_items = [
            {"id": "p1", "title": "Widget A", "price": 29.99, "category": "widgets"}
        ]
        with patch("apps.shopify.revenue.product_recommender.get_cache", return_value=_mock_cache()):
            results = await recommender.cross_sell_recommendations(
                cart_items=cart_items, catalog=catalog
            )
        assert isinstance(results, list)
        # Should not include cart items or same category
        cart_ids = {i["id"] for i in cart_items}
        cart_categories = {i["category"] for i in cart_items}
        for p in results:
            assert p.get("id") not in cart_ids
            assert p.get("category") not in cart_categories

    @pytest.mark.asyncio
    async def test_recommendation_stats_returns_dict(self, recommender):
        with patch("apps.shopify.revenue.product_recommender.get_cache", return_value=_mock_cache()):
            await recommender.record_interaction("u1", "p1", "view")
            await recommender.record_interaction("u1", "p2", "purchase")
        stats = recommender.recommendation_stats()
        assert isinstance(stats, dict)
        assert "total_recommendations" in stats
        assert "users_tracked" in stats
        assert "top_recommended_products" in stats
        assert stats["users_tracked"] >= 1
