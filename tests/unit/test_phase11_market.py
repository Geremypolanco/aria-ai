"""Phase 11 tests — Market (PricingIntelligence, LinkingOptimizer, DistributionEngine)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Market average: $79. Recommended price: $75"):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── Pricing Intelligence ──────────────────────────────────────────────────────

class TestPricingIntelligence:
    @pytest.fixture
    def intel(self):
        with patch("apps.market.pricing.pricing_intelligence.get_cache", return_value=_mock_cache()):
            with patch("apps.market.pricing.pricing_intelligence.get_ai_client",
                       return_value=_mock_ai("Market average: $79. Recommended price: $75")):
                from apps.market.pricing.pricing_intelligence import PricingIntelligence
                return PricingIntelligence()

    @pytest.mark.asyncio
    async def test_analyze_pricing_returns_price_point(self, intel):
        from apps.market.pricing.pricing_intelligence import PricePoint
        pp = await intel.analyze_pricing("Fitness Course", "online_courses", 97.0)
        assert isinstance(pp, PricePoint)
        assert pp.price_id

    @pytest.mark.asyncio
    async def test_analyze_pricing_sets_recommended_price(self, intel):
        pp = await intel.analyze_pricing("SEO Tool", "software", 49.0)
        assert pp.recommended_price > 0.0

    @pytest.mark.asyncio
    async def test_analyze_pricing_with_competitor_data(self, intel):
        competitors = [
            {"competitor": "CompA", "price": 59.0},
            {"competitor": "CompB", "price": 79.0},
            {"competitor": "CompC", "price": 99.0},
        ]
        pp = await intel.analyze_pricing("AI Writing Tool", "software", 69.0, competitor_data=competitors)
        assert pp.market_avg > 0.0
        assert pp.market_min > 0.0
        assert pp.market_max > 0.0

    @pytest.mark.asyncio
    async def test_market_avg_calculated_from_competitors(self, intel):
        competitors = [
            {"competitor": "A", "price": 60.0},
            {"competitor": "B", "price": 80.0},
            {"competitor": "C", "price": 100.0},
        ]
        pp = await intel.analyze_pricing("Product", "category", 70.0, competitor_data=competitors)
        assert abs(pp.market_avg - 80.0) < 0.01

    @pytest.mark.asyncio
    async def test_positioning_premium_when_overpriced(self, intel):
        competitors = [{"competitor": "A", "price": 50.0}]
        pp = await intel.analyze_pricing("Luxury Product", "luxury", 80.0, competitor_data=competitors)
        assert pp.positioning == "premium"

    @pytest.mark.asyncio
    async def test_positioning_budget_when_underpriced(self, intel):
        competitors = [{"competitor": "A", "price": 100.0}]
        pp = await intel.analyze_pricing("Budget Product", "general", 50.0, competitor_data=competitors)
        assert pp.positioning == "budget"

    @pytest.mark.asyncio
    async def test_build_strategy_returns_strategy(self, intel):
        from apps.market.pricing.pricing_intelligence import PricingStrategy
        strategy = await intel.build_strategy("fitness", "online_course", 60.0)
        assert isinstance(strategy, PricingStrategy)
        assert strategy.strategy_id

    @pytest.mark.asyncio
    async def test_strategy_has_initial_and_target_price(self, intel):
        strategy = await intel.build_strategy("health", "supplement", 50.0)
        assert strategy.initial_price >= 0.0
        assert strategy.target_price >= 0.0

    @pytest.mark.asyncio
    async def test_strategy_has_type(self, intel):
        strategy = await intel.build_strategy("tech", "saas", 70.0)
        assert isinstance(strategy.strategy_type, str)
        assert len(strategy.strategy_type) > 0

    @pytest.mark.asyncio
    async def test_detect_price_elasticity_returns_valid_value(self, intel):
        elasticity = await intel.detect_price_elasticity("fitness supplement", (30, 70))
        assert elasticity in ("low", "medium", "high")

    @pytest.mark.asyncio
    async def test_dynamic_price_suggestion_returns_dict(self, intel):
        await intel.analyze_pricing("Protein Powder", "supplements", 49.0)
        result = await intel.dynamic_price_suggestion("Protein Powder", "low", "high")
        assert "suggested_price" in result
        assert "adjustment_pct" in result
        assert "reasoning" in result

    @pytest.mark.asyncio
    async def test_dynamic_price_high_demand_low_inventory(self, intel):
        await intel.analyze_pricing("Widget", "gadgets", 100.0)
        result = await intel.dynamic_price_suggestion("Widget", "low", "high")
        assert result["adjustment_pct"] >= 0

    def test_pricing_dashboard_has_required_keys(self, intel):
        dash = intel.pricing_dashboard()
        assert "total_price_points" in dash
        assert "by_positioning" in dash
        assert "strategies_built" in dash

    @pytest.mark.asyncio
    async def test_recent_analyses_returns_list(self, intel):
        await intel.analyze_pricing("Product A", "cat", 50.0)
        result = intel.recent_analyses(limit=5)
        assert isinstance(result, list)
        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_competitive_gaps_returns_overpriced(self, intel):
        intel._price_points = [
            {"product_name": "P1", "our_price": 150.0, "recommended_price": 80.0, "positioning": "premium"},
            {"product_name": "P2", "our_price": 50.0, "recommended_price": 60.0, "positioning": "budget"},
        ]
        gaps = intel.competitive_gaps()
        assert len(gaps) == 1
        assert gaps[0]["product_name"] == "P1"

    @pytest.mark.asyncio
    async def test_multiple_price_points_accumulate(self, intel):
        await intel.analyze_pricing("A", "cat", 50.0)
        await intel.analyze_pricing("B", "cat", 70.0)
        assert len(intel._price_points) == 2


# ── Linking Optimizer ─────────────────────────────────────────────────────────

class TestLinkingOptimizer:
    @pytest.fixture
    def optimizer(self):
        with patch("apps.content.internal_linking.linking_optimizer.get_cache", return_value=_mock_cache()):
            with patch("apps.content.internal_linking.linking_optimizer.get_ai_client",
                       return_value=_mock_ai("Pillar: Complete Guide to Fitness\nCluster: Nutrition, Workouts, Recovery")):
                from apps.content.internal_linking.linking_optimizer import LinkingOptimizer
                return LinkingOptimizer()

    @pytest.mark.asyncio
    async def test_audit_site_returns_audit(self, optimizer):
        from apps.content.internal_linking.linking_optimizer import LinkingAudit
        pages = [
            {"url": "/fitness-guide", "title": "Fitness Guide", "keywords": ["fitness", "workout"], "word_count": 1200},
            {"url": "/nutrition", "title": "Nutrition Basics", "keywords": ["nutrition", "fitness"], "word_count": 800},
        ]
        audit = await optimizer.audit_site("fitness", pages)
        assert isinstance(audit, LinkingAudit)
        assert audit.audit_id

    @pytest.mark.asyncio
    async def test_audit_detects_orphan_pages(self, optimizer):
        pages = [
            {"url": "/guide", "title": "Main Guide", "keywords": ["fitness"], "word_count": 1500},
            {"url": "/stub", "title": "Short Page", "keywords": ["workout"], "word_count": 100},
        ]
        audit = await optimizer.audit_site("fitness", pages)
        assert isinstance(audit.orphan_pages, list)
        assert len(audit.orphan_pages) >= 1

    @pytest.mark.asyncio
    async def test_audit_has_pages_analyzed_count(self, optimizer):
        pages = [
            {"url": "/a", "title": "A", "keywords": ["fitness"], "word_count": 500},
            {"url": "/b", "title": "B", "keywords": ["health"], "word_count": 600},
            {"url": "/c", "title": "C", "keywords": ["fitness", "health"], "word_count": 700},
        ]
        audit = await optimizer.audit_site("health", pages)
        assert audit.pages_analyzed == 3

    @pytest.mark.asyncio
    async def test_suggest_links_returns_list(self, optimizer):
        source = {"url": "/seo-guide", "title": "SEO Guide", "keywords": ["seo", "content"]}
        library = [
            {"url": "/content-tips", "title": "Content Tips", "keywords": ["content", "writing"]},
            {"url": "/keyword-research", "title": "Keyword Research", "keywords": ["seo", "keywords"]},
        ]
        suggestions = await optimizer.suggest_links(source, library)
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 1

    @pytest.mark.asyncio
    async def test_suggest_links_have_anchor_text(self, optimizer):
        source = {"url": "/main", "title": "Main", "keywords": ["fitness", "health"]}
        library = [{"url": "/sub", "title": "Sub", "keywords": ["fitness"]}]
        suggestions = await optimizer.suggest_links(source, library)
        for s in suggestions:
            assert s.anchor_text

    @pytest.mark.asyncio
    async def test_optimize_anchor_text_returns_string(self, optimizer):
        from apps.content.internal_linking.linking_optimizer import LinkSuggestion
        link = LinkSuggestion(
            source_url="/from", source_title="Source", target_url="/to",
            target_title="Target", anchor_text="old anchor"
        )
        result = await optimizer.optimize_anchor_text(link, "fitness tips")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_generate_pillar_strategy_returns_dict(self, optimizer):
        result = await optimizer.generate_pillar_strategy(
            "fitness", ["workout routines", "nutrition guide", "recovery methods"]
        )
        assert "pillar_pages" in result
        assert "cluster_pages" in result

    def test_linking_stats_has_required_keys(self, optimizer):
        stats = optimizer.linking_stats()
        assert "total_suggestions" in stats
        assert "audits_completed" in stats
        assert "avg_relevance_score" in stats


# ── Distribution Engine ───────────────────────────────────────────────────────

class TestDistributionEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.content.distribution.distribution_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.content.distribution.distribution_engine.get_ai_client",
                       return_value=_mock_ai("🧵 Thread: 5 ways to grow your business with AI...\n\n1/ Start with content marketing")):
                from apps.content.distribution.distribution_engine import DistributionEngine
                return DistributionEngine()

    @pytest.mark.asyncio
    async def test_adapt_for_channel_returns_string(self, engine):
        result = await engine.adapt_for_channel("Long form article about AI marketing", "twitter", "blog_post")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_adapt_for_linkedin_returns_string(self, engine):
        result = await engine.adapt_for_channel("Article content here", "linkedin", "article")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_prepare_distribution_returns_job(self, engine):
        from apps.content.distribution.distribution_engine import DistributionJob
        job = await engine.prepare_distribution(
            "5 AI Tips", "Here are 5 tips...", "blog_post",
            ["twitter", "linkedin", "email"]
        )
        assert isinstance(job, DistributionJob)
        assert job.job_id

    @pytest.mark.asyncio
    async def test_distribution_job_has_adaptations(self, engine):
        job = await engine.prepare_distribution(
            "Content Title", "Content body here", "article",
            ["twitter", "linkedin"]
        )
        assert "twitter" in job.adaptations
        assert "linkedin" in job.adaptations

    @pytest.mark.asyncio
    async def test_distribution_job_has_reach_estimate(self, engine):
        job = await engine.prepare_distribution(
            "My Post", "Some content", "blog_post",
            ["twitter", "linkedin", "email"]
        )
        assert job.reach_estimate > 0

    @pytest.mark.asyncio
    async def test_schedule_distribution_returns_true(self, engine):
        import time
        job = await engine.prepare_distribution("Title", "Content", "blog_post", ["twitter"])
        result = await engine.schedule_distribution(job.job_id, time.time() + 3600)
        assert result is True

    @pytest.mark.asyncio
    async def test_distribute_now_returns_dict(self, engine):
        job = await engine.prepare_distribution("Now Post", "Content now", "article", ["linkedin"])
        result = await engine.distribute_now(job.job_id)
        assert result.get("status") == "distributed"

    @pytest.mark.asyncio
    async def test_distribute_now_has_channels_reached(self, engine):
        job = await engine.prepare_distribution("Post", "Content", "blog_post", ["twitter", "reddit"])
        result = await engine.distribute_now(job.job_id)
        assert "channels_reached" in result

    @pytest.mark.asyncio
    async def test_cross_post_strategy_returns_dict(self, engine):
        result = await engine.cross_post_strategy("fitness", "blog_post")
        assert "primary_channel" in result
        assert "channel_mix" in result

    def test_distribution_stats_has_required_keys(self, engine):
        stats = engine.distribution_stats()
        assert "total_jobs" in stats
        assert "distributed" in stats
        assert "by_channel" in stats

    def test_recent_distributions_returns_list(self, engine):
        result = engine.recent_distributions(limit=10)
        assert isinstance(result, list)
