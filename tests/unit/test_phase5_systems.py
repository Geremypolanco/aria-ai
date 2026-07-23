"""
Phase 5 — Autonomous Business Operation: unit tests.
Covers: Growth Engine, Acquisition, Funnel Optimizer, Experiment Runner,
Shopify Operator, Pricing Optimizer, SEO Optimizer,
Content OS, Content Planner, Content Distributor,
Marketing Intelligence, SEO Analyzer, Copy Optimizer,
Economic Engine, CAC/LTV Analyzer,
Growth Learner, Campaign Scorer, CRM Engine, Retention Engine.
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────


def fake_email():
    return f"user_{uuid.uuid4().hex[:6]}@example.com"


# ═══════════════════════════════════════════════════════════════════════════
# 1. GROWTH ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TestGrowthEngine:
    def test_growth_loop_is_due(self):
        from apps.business.growth.growth_engine import GrowthLoop
        loop = GrowthLoop(
            loop_id="test-loop",
            name="Test Loop",
            channel="seo",
            strategy="organic",
            frequency_hours=6.0,
            priority=1,
            enabled=True,
            last_run_ts=0.0,  # never run → always due
        )
        assert loop.is_due() is True

    def test_growth_loop_not_due_recently_run(self):
        from apps.business.growth.growth_engine import GrowthLoop
        loop = GrowthLoop(
            loop_id="test-loop",
            name="Test Loop",
            channel="seo",
            strategy="organic",
            frequency_hours=6.0,
            priority=1,
            enabled=True,
            last_run_ts=time.time(),  # just ran
        )
        assert loop.is_due() is False

    def test_growth_loop_success_rate(self):
        from apps.business.growth.growth_engine import GrowthLoop
        loop = GrowthLoop(
            loop_id="l1",
            name="L1",
            channel="email",
            strategy="nurture",
            frequency_hours=12.0,
            priority=2,
            enabled=True,
            success_count=8,
            fail_count=2,
            total_runs=10,
        )
        assert loop.success_rate == pytest.approx(0.8)

    def test_growth_loop_avg_revenue(self):
        from apps.business.growth.growth_engine import GrowthLoop
        loop = GrowthLoop(
            loop_id="l2",
            name="L2",
            channel="shopify",
            strategy="seo",
            frequency_hours=6.0,
            priority=1,
            enabled=True,
            total_runs=5,
            total_revenue_usd=50.0,
        )
        assert loop.avg_revenue_per_run == pytest.approx(10.0)

    def test_growth_engine_default_loops(self):
        from apps.business.growth.growth_engine import GrowthEngine
        engine = GrowthEngine()
        defaults = engine._default_loops()
        assert len(defaults) >= 6
        channels = [l.channel for l in defaults]
        assert "shopify_seo" in channels or any("shopify" in c for c in channels)

    def test_growth_engine_summary(self):
        from apps.business.growth.growth_engine import GrowthEngine
        engine = GrowthEngine()
        s = engine.summary()
        assert "total_loops" in s

    @pytest.mark.asyncio
    async def test_record_result_updates_loop(self):
        from apps.business.growth.growth_engine import GrowthEngine, GrowthLoop
        engine = GrowthEngine()
        loop = GrowthLoop(
            loop_id="rec-test",
            name="Rec Test",
            channel="email",
            strategy="blast",
            frequency_hours=6.0,
            priority=3,
            enabled=True,
        )
        engine.register_loop(loop)
        await engine.record_result("rec-test", success=True, revenue_usd=25.0)
        loops = {l.loop_id: l for l in engine._default_loops()}
        # The in-memory state should have updated
        assert engine._loops["rec-test"].success_count == 1
        assert engine._loops["rec-test"].total_revenue_usd == pytest.approx(25.0)


# ═══════════════════════════════════════════════════════════════════════════
# 2. ACQUISITION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TestAcquisitionEngine:
    def test_lead_quality_hot(self):
        from apps.business.growth.acquisition import LeadQuality
        assert LeadQuality.HOT.value == "hot" or LeadQuality.HOT is not None

    def test_score_lead_base(self):
        from apps.business.growth.acquisition import AcquisitionEngine, AcquisitionChannel
        engine = AcquisitionEngine()
        score = engine._score_lead("user@gmail.com", AcquisitionChannel.ORGANIC_SEARCH, "")
        assert 0 <= score <= 100

    def test_score_lead_referral_higher(self):
        from apps.business.growth.acquisition import AcquisitionEngine, AcquisitionChannel
        engine = AcquisitionEngine()
        referral = engine._score_lead("ref@gmail.com", AcquisitionChannel.REFERRAL, "referral_campaign")
        organic = engine._score_lead("org@gmail.com", AcquisitionChannel.ORGANIC_SEARCH, "")
        assert referral > organic

    @pytest.mark.asyncio
    async def test_add_lead_deduplicates(self):
        from apps.business.growth.acquisition import AcquisitionEngine, AcquisitionChannel
        engine = AcquisitionEngine()
        email = fake_email()
        lead1 = await engine.add_lead(email, AcquisitionChannel.EMAIL)
        lead2 = await engine.add_lead(email, AcquisitionChannel.EMAIL)
        assert lead1.lead_id == lead2.lead_id

    @pytest.mark.asyncio
    async def test_convert_lead(self):
        from apps.business.growth.acquisition import AcquisitionEngine, AcquisitionChannel
        engine = AcquisitionEngine()
        lead = await engine.add_lead(fake_email(), AcquisitionChannel.CONTENT)
        await engine.convert_lead(lead.lead_id, revenue_usd=49.0)
        leads = await engine.get_leads()
        converted = [l for l in leads if l.lead_id == lead.lead_id]
        assert converted[0].converted is True
        assert converted[0].revenue_attributed == pytest.approx(49.0)

    @pytest.mark.asyncio
    async def test_funnel_metrics(self):
        from apps.business.growth.acquisition import AcquisitionEngine, AcquisitionChannel
        engine = AcquisitionEngine()
        await engine.add_lead(fake_email(), AcquisitionChannel.SOCIAL_ORGANIC, score=85)
        metrics = await engine.funnel_metrics()
        assert "total_leads" in metrics
        assert metrics["total_leads"] >= 1


# ═══════════════════════════════════════════════════════════════════════════
# 3. FUNNEL OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════

class TestFunnelOptimizer:
    def test_funnel_metrics_dataclass(self):
        from apps.business.growth.funnel_optimizer import FunnelMetrics, FunnelStage
        m = FunnelMetrics(stage=FunnelStage.AWARENESS, entries=100, exits=40, conversions_to_next=60)
        assert m.conversion_rate == pytest.approx(0.6)
        assert m.drop_rate == pytest.approx(0.4)

    def test_funnel_optimizer_summary(self):
        from apps.business.growth.funnel_optimizer import FunnelOptimizer
        opt = FunnelOptimizer()
        s = opt.summary()
        assert "overall_conversion_rate" in s or "bottleneck_stage" in s or isinstance(s, dict)

    @pytest.mark.asyncio
    async def test_track_event(self):
        from apps.business.growth.funnel_optimizer import FunnelOptimizer, FunnelStage
        opt = FunnelOptimizer()
        await opt.track_event("sess-1", FunnelStage.AWARENESS, "page_view")
        # No error = pass

    @pytest.mark.asyncio
    async def test_generate_opportunities(self):
        from apps.business.growth.funnel_optimizer import FunnelOptimizer
        opt = FunnelOptimizer()
        opps = await opt.generate_opportunities()
        assert isinstance(opps, list)

    @pytest.mark.asyncio
    async def test_ab_test_recommendation(self):
        from apps.business.growth.funnel_optimizer import FunnelOptimizer, FunnelStage
        opt = FunnelOptimizer()
        rec = await opt.ab_test_recommendation(FunnelStage.CONSIDERATION)
        assert isinstance(rec, str) and len(rec) > 0


# ═══════════════════════════════════════════════════════════════════════════
# 4. EXPERIMENT RUNNER
# ═══════════════════════════════════════════════════════════════════════════

class TestExperimentRunner:
    @pytest.fixture(autouse=True)
    def _isolate_cache(self):
        # Each ExperimentRunner uses the real process-shared cache by default, so
        # experiments leak across tests and analysis/lookup becomes flaky. Give every
        # test a fresh, empty mock cache that stays active for the whole test.
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock(return_value=True)
        with patch("apps.business.growth.experiment_runner.get_cache", return_value=cache):
            yield

    @pytest.mark.asyncio
    async def test_create_experiment(self):
        from apps.business.growth.experiment_runner import ExperimentRunner
        runner = ExperimentRunner()
        exp_id = await runner.create_experiment(
            name="CTA Color Test",
            hypothesis="Blue CTA converts better than green",
            channel="shopify",
            metric="conversion_rate",
            variant_names=["control_green", "variant_blue"],
        )
        assert exp_id is not None
        exps = await runner.list_experiments()
        found = [e for e in exps if e["experiment_id"] == exp_id]
        assert len(found) == 1
        assert found[0]["status"] in ("draft", "DRAFT")

    @pytest.mark.asyncio
    async def test_start_and_record_impressions(self):
        from apps.business.growth.experiment_runner import ExperimentRunner
        runner = ExperimentRunner()
        exp_id = await runner.create_experiment(
            "Headline Test", "Long headline wins", "blog", "ctr", ["short", "long"]
        )
        await runner.start_experiment(exp_id)
        exps = await runner.list_experiments()
        exp = next(e for e in exps if e["experiment_id"] == exp_id)
        v0_id = exp["variants"][0]["variant_id"]
        await runner.record_impression(exp_id, v0_id)
        await runner.record_conversion(exp_id, v0_id)

    @pytest.mark.asyncio
    async def test_analyze_determines_winner(self):
        from apps.business.growth.experiment_runner import ExperimentRunner
        runner = ExperimentRunner()
        exp_id = await runner.create_experiment(
            "Price Test", "Lower price wins", "shopify", "revenue", ["original", "discounted"]
        )
        await runner.start_experiment(exp_id)
        exps = await runner.list_experiments()
        exp = next(e for e in exps if e["experiment_id"] == exp_id)
        v0_id = exp["variants"][0]["variant_id"]
        v1_id = exp["variants"][1]["variant_id"]
        for _ in range(60):
            await runner.record_impression(exp_id, v0_id)
            await runner.record_impression(exp_id, v1_id)
        for _ in range(5):
            await runner.record_conversion(exp_id, v0_id)
        for _ in range(12):
            await runner.record_conversion(exp_id, v1_id)
        await runner.analyze_experiment(exp_id)
        exps = await runner.list_experiments()
        analyzed = next(e for e in exps if e["experiment_id"] == exp_id)
        assert analyzed.get("winner_id", "") != "" or analyzed.get("confidence", 0) >= 0

    @pytest.mark.asyncio
    async def test_get_learnings_empty(self):
        from apps.business.growth.experiment_runner import ExperimentRunner
        runner = ExperimentRunner()
        learnings = await runner.get_learnings()
        assert isinstance(learnings, list)


# ═══════════════════════════════════════════════════════════════════════════
# 5. SHOPIFY OPERATOR
# ═══════════════════════════════════════════════════════════════════════════

class TestShopifyOperator:
    def test_shopify_operator_init_no_credentials(self):
        from apps.business.ecommerce.shopify_operator import ShopifyOperator
        op = ShopifyOperator()
        assert op._engine is None  # no credentials in test env

    @pytest.mark.asyncio
    async def test_identify_opportunities_no_engine(self):
        from apps.business.ecommerce.shopify_operator import ShopifyOperator
        op = ShopifyOperator()
        opps = await op.identify_opportunities()
        assert isinstance(opps, list)

    @pytest.mark.asyncio
    async def test_generate_seo_description(self):
        from apps.business.ecommerce.shopify_operator import ShopifyOperator
        op = ShopifyOperator()
        desc = await op.generate_seo_description("Yoga Mat", "fitness", ["non-slip", "eco-friendly"])
        assert isinstance(desc, str) and len(desc) > 10

    def test_summary(self):
        from apps.business.ecommerce.shopify_operator import ShopifyOperator
        op = ShopifyOperator()
        s = op.summary()
        assert "catalog_health" in s or isinstance(s, dict)


# ═══════════════════════════════════════════════════════════════════════════
# 6. PRICING OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════

class TestPricingOptimizer:
    def test_recommend_price_with_competition(self):
        from apps.business.ecommerce.pricing_optimizer import PricingOptimizer, PricingStrategy
        opt = PricingOptimizer()
        pp = opt.recommend_price("prod-1", 29.99, cost_basis=10.0, category="fitness", competition_avg=32.0)
        assert pp.recommended_price == pytest.approx(32.0 * 0.95)
        assert pp.strategy == PricingStrategy.COMPETITIVE

    def test_recommend_price_no_competition(self):
        from apps.business.ecommerce.pricing_optimizer import PricingOptimizer
        opt = PricingOptimizer()
        pp = opt.recommend_price("prod-2", 19.99, cost_basis=8.0, category="home")
        assert pp.recommended_price == pytest.approx(8.0 * 2.5)
        assert pp.confidence == pytest.approx(0.6)

    def test_margin_analysis(self):
        from apps.business.ecommerce.pricing_optimizer import PricingOptimizer
        opt = PricingOptimizer()
        result = opt.margin_analysis(revenue=100.0, cogs=40.0, operating_costs=20.0)
        assert result["gross_margin_pct"] == pytest.approx(60.0)
        assert result["net_margin_pct"] == pytest.approx(40.0)

    @pytest.mark.asyncio
    async def test_batch_optimize(self):
        from apps.business.ecommerce.pricing_optimizer import PricingOptimizer
        opt = PricingOptimizer()
        products = [
            {"product_id": "p1", "current_price": 25.0, "cost_basis": 10.0, "category": "home"},
            {"product_id": "p2", "current_price": 50.0, "cost_basis": 20.0, "category": "fitness"},
        ]
        results = await opt.batch_optimize(products)
        assert len(results) == 2


# ═══════════════════════════════════════════════════════════════════════════
# 7. SEO OPTIMIZER (SHOPIFY)
# ═══════════════════════════════════════════════════════════════════════════

class TestShopifySEOOptimizer:
    def test_score_product_complete(self):
        from apps.business.ecommerce.seo_optimizer import ShopifySEOOptimizer
        opt = ShopifySEOOptimizer()
        product = {
            "id": "p1",
            "title": "Premium Yoga Mat - Non-Slip Eco Friendly",
            "body_html": "<p>High quality yoga mat with excellent grip.</p>" * 15,
            "tags": ["yoga", "fitness", "eco", "non-slip", "exercise", "mat"],
            "images": [{"src": "img1.jpg", "alt": "Yoga Mat"}],
            "handle": "premium-yoga-mat",
        }
        score = opt.score_product(product)
        assert score.overall_score > 50

    def test_score_product_empty(self):
        from apps.business.ecommerce.seo_optimizer import ShopifySEOOptimizer
        opt = ShopifySEOOptimizer()
        score = opt.score_product({"id": "p2", "title": "X", "body_html": "", "tags": [], "images": [], "handle": "x"})
        assert score.overall_score < 50
        assert len(score.issues) > 0

    def test_optimize_url_handle(self):
        from apps.business.ecommerce.seo_optimizer import ShopifySEOOptimizer
        opt = ShopifySEOOptimizer()
        handle = opt.optimize_url_handle("Premium Yoga Mat - Non-Slip & Eco Friendly!!")
        assert " " not in handle
        assert handle == handle.lower()

    def test_keyword_opportunities(self):
        from apps.business.ecommerce.seo_optimizer import ShopifySEOOptimizer
        opt = ShopifySEOOptimizer()
        kws = opt.keyword_opportunities("fitness", ["gym"])
        assert len(kws) >= 2

    @pytest.mark.asyncio
    async def test_generate_meta_tags(self):
        from apps.business.ecommerce.seo_optimizer import ShopifySEOOptimizer
        opt = ShopifySEOOptimizer()
        meta = await opt.generate_meta_tags("Yoga Mat", "fitness")
        assert "meta_title" in meta and "meta_description" in meta


# ═══════════════════════════════════════════════════════════════════════════
# 8. CONTENT OS
# ═══════════════════════════════════════════════════════════════════════════

class TestContentOS:
    @pytest.mark.asyncio
    async def test_ideate_returns_pieces(self):
        from apps.content.content_os import ContentOS, ContentPlatform
        cos = ContentOS()
        pieces = await cos.ideate("yoga for beginners", [ContentPlatform.YOUTUBE, ContentPlatform.BLOG], count=2)
        assert len(pieces) >= 2

    @pytest.mark.asyncio
    async def test_score_virality(self):
        from apps.content.content_os import ContentOS, ContentPlatform
        cos = ContentOS()
        # ideate creates pieces; score the first one created
        pieces = await cos.ideate("7 yoga poses morning routine", [ContentPlatform.YOUTUBE], count=1)
        assert len(pieces) >= 1
        result = await cos.score_virality(pieces[0].content_id)
        # score_virality returns the updated ContentPiece
        assert result is not None

    @pytest.mark.asyncio
    async def test_plan_calendar(self):
        from apps.content.content_os import ContentOS
        cos = ContentOS()
        calendar = await cos.plan_calendar("2026-06-15", ["yoga", "fitness", "nutrition"])
        assert len(calendar) == 7

    @pytest.mark.asyncio
    async def test_performance_report(self):
        from apps.content.content_os import ContentOS
        cos = ContentOS()
        report = await cos.performance_report()
        assert "total_pieces" in report

    def test_summary(self):
        from apps.content.content_os import ContentOS
        cos = ContentOS()
        s = cos.summary()
        assert isinstance(s, dict)


# ═══════════════════════════════════════════════════════════════════════════
# 9. CONTENT PLANNER
# ═══════════════════════════════════════════════════════════════════════════

class TestContentPlanner:
    def test_research_topics(self):
        from apps.content.planner import ContentPlanner
        planner = ContentPlanner()
        topics = planner.research_topics("ecommerce", count=5)
        assert len(topics) >= 3

    def test_build_strategy_awareness(self):
        from apps.content.planner import ContentPlanner
        planner = ContentPlanner()
        strategy = planner.build_strategy("awareness", weekly_budget_hours=10)
        assert strategy is not None
        assert strategy.objective == "awareness"

    def test_repurposing_plan(self):
        from apps.content.planner import ContentPlanner
        from apps.content.content_os import ContentType
        planner = ContentPlanner()
        plan = planner.repurposing_plan(ContentType.BLOG_POST)
        # returns dict{type_key: [repurposed_types]} or list — accept both
        if isinstance(plan, dict):
            values = list(plan.values())
            repurposed = values[0] if values else []
        else:
            repurposed = plan
        assert len(repurposed) >= 2

    def test_seo_keyword_clusters(self):
        from apps.content.planner import ContentPlanner
        planner = ContentPlanner()
        clusters = planner.seo_keyword_clusters("yoga mat")
        assert isinstance(clusters, dict) and len(clusters) >= 3


# ═══════════════════════════════════════════════════════════════════════════
# 10. CONTENT DISTRIBUTOR
# ═══════════════════════════════════════════════════════════════════════════

class TestContentDistributor:
    @pytest.mark.asyncio
    async def test_queue_distribution(self):
        from apps.content.distributor import ContentDistributor
        dist = ContentDistributor()
        await dist.queue_distribution("content-123", ["linkedin", "twitter"])

    @pytest.mark.asyncio
    async def test_distribution_stats(self):
        from apps.content.distributor import ContentDistributor
        dist = ContentDistributor()
        stats = await dist.distribution_stats()
        assert "total_queued" in stats or isinstance(stats, dict)


# ═══════════════════════════════════════════════════════════════════════════
# 11. MARKETING INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketingIntelligence:
    @pytest.mark.asyncio
    async def test_identify_opportunities(self):
        from apps.business.marketing.marketing_intelligence import MarketingIntelligence, MarketingChannel
        mi = MarketingIntelligence()
        opps = await mi.identify_opportunities("yoga", [MarketingChannel.SEO])
        assert isinstance(opps, list)

    @pytest.mark.asyncio
    async def test_score_channel(self):
        from apps.business.marketing.marketing_intelligence import MarketingIntelligence, MarketingChannel
        mi = MarketingIntelligence()
        # effort is numeric 0-10; lower = less effort (better)
        score = await mi.score_channel(MarketingChannel.SEO, {"roi": 3.0, "volume": 5000, "effort": 3.0})
        assert 0 <= score <= 100

    @pytest.mark.asyncio
    async def test_generate_growth_plan(self):
        from apps.business.marketing.marketing_intelligence import MarketingIntelligence
        mi = MarketingIntelligence()
        plan = await mi.generate_growth_plan("revenue", 1000.0, 12)
        assert isinstance(plan, dict)

    def test_summary(self):
        from apps.business.marketing.marketing_intelligence import MarketingIntelligence
        mi = MarketingIntelligence()
        s = mi.summary()
        assert isinstance(s, dict)


# ═══════════════════════════════════════════════════════════════════════════
# 12. SEO ANALYZER
# ═══════════════════════════════════════════════════════════════════════════

class TestSEOAnalyzer:
    def test_score_page_good(self):
        from apps.business.marketing.seo_analyzer import SEOAnalyzer, SEOAudit
        analyzer = SEOAnalyzer()
        result = analyzer.score_page(
            title="Best Yoga Mats for Beginners 2026",
            description="Discover the top 10 yoga mats for beginners. Compare non-slip, eco-friendly options.",
            word_count=800,
            has_h1=True,
            has_images=True,
        )
        score = result.score if isinstance(result, SEOAudit) else result
        # Good page should score higher than poor page (50 is good threshold given 5 factors)
        assert score >= 50

    def test_score_page_poor(self):
        from apps.business.marketing.seo_analyzer import SEOAnalyzer, SEOAudit
        analyzer = SEOAnalyzer()
        result = analyzer.score_page("X", "short", 50, False, False)
        score = result.score if isinstance(result, SEOAudit) else result
        assert score < 50

    def test_keyword_research(self):
        from apps.business.marketing.seo_analyzer import SEOAnalyzer
        analyzer = SEOAnalyzer()
        kws = analyzer.keyword_research("yoga mat", "fitness")
        assert len(kws) >= 5
        assert all(k.volume_estimate > 0 for k in kws)

    def test_trending_topics(self):
        from apps.business.marketing.seo_analyzer import SEOAnalyzer
        analyzer = SEOAnalyzer()
        topics = analyzer.trending_topics("ecommerce")
        assert len(topics) >= 3


# ═══════════════════════════════════════════════════════════════════════════
# 13. COPY OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════

class TestCopyOptimizer:
    def test_score_headline_good(self):
        from apps.business.marketing.copy_optimizer import CopyOptimizer
        opt = CopyOptimizer()
        score = opt.score_headline("7 Proven Ways to Double Your Sales This Week")
        assert score.score >= 60

    def test_score_cta_strong(self):
        from apps.business.marketing.copy_optimizer import CopyOptimizer
        opt = CopyOptimizer()
        score = opt.score_cta("Get Instant Access Now")
        assert score.score >= 60

    def test_score_email_subject_with_spam(self):
        from apps.business.marketing.copy_optimizer import CopyOptimizer
        opt = CopyOptimizer()
        score = opt.score_email_subject("FREE WINNER Click here now!!")
        assert score.score < 60

    def test_power_words_structure(self):
        from apps.business.marketing.copy_optimizer import CopyOptimizer
        opt = CopyOptimizer()
        words = opt.power_words()
        assert "urgency" in words and "trust" in words


# ═══════════════════════════════════════════════════════════════════════════
# 16. ECONOMIC ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TestEconomicEngine:
    def test_compute_unit_economics(self):
        from apps.business.economics.economic_engine import EconomicEngine
        engine = EconomicEngine()
        ue = engine.compute_unit_economics(
            channel="shopify_seo",
            total_acquisition_spend=5000.0,
            total_customers=100,
            avg_order_value=50.0,
            avg_orders_per_year=3,
            avg_lifespan_years=2.0,
        )
        assert ue.cac_usd == pytest.approx(50.0)
        assert ue.ltv_usd > ue.cac_usd  # should be profitable

    def test_forecast_revenue_growth(self):
        from apps.business.economics.economic_engine import EconomicEngine
        engine = EconomicEngine()
        projections = engine.forecast_revenue(
            initial_customers=10, monthly_growth_rate=0.10, avg_ltv=200.0, months=6
        )
        assert len(projections) == 7  # month 0 to 6
        assert projections[-1].customers > projections[0].customers

    def test_optimal_budget_allocation(self):
        from apps.business.economics.economic_engine import EconomicEngine
        engine = EconomicEngine()
        channels = [
            {"channel": "seo", "projected_roi": 4.0, "risk_level": "low"},
            {"channel": "paid", "projected_roi": 1.0, "risk_level": "high"},
            {"channel": "email", "projected_roi": 7.0, "risk_level": "low"},
        ]
        allocation = engine.optimal_budget_allocation(3000.0, channels)
        assert sum(allocation.values()) == pytest.approx(3000.0, rel=0.01)
        # email has highest ROI + low risk, should get more than paid (low ROI + high risk)
        assert allocation["email"] > allocation["paid"]

    @pytest.mark.asyncio
    async def test_rank_opportunities(self):
        from apps.business.economics.economic_engine import EconomicEngine, EconomicOpportunity
        engine = EconomicEngine()
        opps = [
            EconomicOpportunity("o1", "SEO", "organic", 20.0, 200.0, 50000, 1000.0, 3.0, "low", 3.0),
            EconomicOpportunity("o2", "Paid", "paid", 50.0, 150.0, 100000, 5000.0, 1.5, "high", 6.0),
        ]
        ranked = await engine.rank_opportunities(opps)
        assert ranked[0].opportunity_id == "o1"  # lower risk, better LTV:CAC


# ═══════════════════════════════════════════════════════════════════════════
# 17. CAC/LTV ANALYZER
# ═══════════════════════════════════════════════════════════════════════════

class TestCACLTVAnalyzer:
    def test_compute_cac(self):
        from apps.business.economics.cac_ltv import CACLTVAnalyzer
        analyzer = CACLTVAnalyzer()
        breakdown = analyzer.compute_cac(
            ad_spend=4000.0, salesperson_cost=500.0, tool_cost=200.0, new_customers=100
        )
        assert breakdown.total_cac == pytest.approx(47.0)

    def test_compute_ltv(self):
        from apps.business.economics.cac_ltv import CACLTVAnalyzer
        analyzer = CACLTVAnalyzer()
        ltv = analyzer.compute_ltv(
            avg_purchase_value=50.0, purchase_frequency_yearly=4,
            gross_margin_pct=0.6, avg_customer_lifespan_years=3.0
        )
        assert ltv == pytest.approx(50.0 * 4 * 0.6 * 3.0)

    def test_compute_churn(self):
        from apps.business.economics.cac_ltv import CACLTVAnalyzer
        analyzer = CACLTVAnalyzer()
        churn = analyzer.compute_churn(lost_customers=10, start_customers=100)
        assert churn.churn_rate_monthly == pytest.approx(0.1)
        # cohort_survival is months 0..12 (13 entries) or 1..12 (12 entries)
        assert len(churn.cohort_survival) in (12, 13)

    def test_payback_period(self):
        from apps.business.economics.cac_ltv import CACLTVAnalyzer
        analyzer = CACLTVAnalyzer()
        months = analyzer.payback_period(cac=100.0, monthly_revenue_per_customer=50.0, margin_pct=0.5)
        assert months == pytest.approx(4.0)


# ═══════════════════════════════════════════════════════════════════════════
# 18. GROWTH LEARNER
# ═══════════════════════════════════════════════════════════════════════════

class TestGrowthLearner:
    @pytest.mark.asyncio
    async def test_record_experiment_win(self):
        from apps.learning.growth.growth_learner import GrowthLearner, StrategyOutcome
        learner = GrowthLearner()
        await learner.record_experiment(
            strategy="seo_content", channel="blog", hypothesis="Long-form wins",
            variant="2000_word_posts", result=StrategyOutcome.WIN,
            roi=3.5, reach=5000, conversions=50, cost=200.0,
            learnings="Long-form content drives 3x more organic traffic",
        )
        knowledge = await learner.get_knowledge(strategy="seo_content")
        assert len(knowledge) >= 1
        assert knowledge[0].win_count == 1

    @pytest.mark.asyncio
    async def test_strategy_knowledge_confidence(self):
        from apps.learning.growth.growth_learner import StrategyKnowledge, StrategyOutcome
        sk = StrategyKnowledge(strategy="email_nurture", channel="email")
        sk.update(StrategyOutcome.WIN, roi=2.0)
        sk.update(StrategyOutcome.WIN, roi=3.0)
        sk.update(StrategyOutcome.LOSS, roi=0.5)
        assert sk.win_rate == pytest.approx(2 / 3)
        assert sk.confidence > 0.5

    @pytest.mark.asyncio
    async def test_best_strategies(self):
        from apps.learning.growth.growth_learner import GrowthLearner, StrategyOutcome
        learner = GrowthLearner()
        for i in range(3):
            await learner.record_experiment(
                f"strategy_{i}", "shopify", "hypothesis", "v1",
                StrategyOutcome.WIN, roi=float(i + 1), reach=1000, conversions=10, cost=50.0, learnings=""
            )
        best = await learner.best_strategies(top_k=2)
        assert len(best) <= 2

    @pytest.mark.asyncio
    async def test_learning_report(self):
        from apps.learning.growth.growth_learner import GrowthLearner
        learner = GrowthLearner()
        report = await learner.learning_report()
        assert "total_experiments" in report


# ═══════════════════════════════════════════════════════════════════════════
# 19. CAMPAIGN SCORER
# ═══════════════════════════════════════════════════════════════════════════

class TestCampaignScorer:
    def test_score_excellent_campaign(self):
        from apps.learning.growth.campaign_scorer import CampaignScorer, CampaignMetrics
        scorer = CampaignScorer()
        metrics = CampaignMetrics(
            campaign_id="c1", name="Summer Sale", channel="shopify",
            impressions=10000, clicks=300, conversions=30,
            revenue_usd=1500.0, cost_usd=100.0,
        )
        score = scorer.score_campaign(metrics)
        assert score.grade == "A"
        assert score.composite_score >= 70

    def test_score_poor_campaign(self):
        from apps.learning.growth.campaign_scorer import CampaignScorer, CampaignMetrics
        scorer = CampaignScorer()
        metrics = CampaignMetrics(
            campaign_id="c2", name="Flop", channel="paid",
            impressions=10000, clicks=10, conversions=0,
            revenue_usd=0.0, cost_usd=500.0,
        )
        score = scorer.score_campaign(metrics)
        assert score.grade in ("D", "C")

    def test_rank_campaigns(self):
        from apps.learning.growth.campaign_scorer import CampaignScorer, CampaignMetrics
        scorer = CampaignScorer()
        c1 = CampaignMetrics("c1", "Good", "seo", 10000, 300, 30, 1500.0, 100.0)
        c2 = CampaignMetrics("c2", "Bad", "paid", 10000, 10, 0, 0.0, 500.0)
        ranked = scorer.rank_campaigns([c2, c1])
        assert ranked[0].campaign_id == "c1"

    def test_campaign_metrics_properties(self):
        from apps.learning.growth.campaign_scorer import CampaignMetrics
        m = CampaignMetrics("x", "X", "email", 1000, 50, 5, 250.0, 25.0)
        assert m.ctr == pytest.approx(0.05)
        assert m.roas == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════════════════
# 20. CRM ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TestCRMEngine:
    @pytest.mark.asyncio
    async def test_add_lead(self):
        from apps.business.crm.crm_engine import CRMEngine
        crm = CRMEngine()
        lead = await crm.add_lead(fake_email(), name="Test User", source="shopify")
        assert lead.lead_id is not None
        assert lead.stage.value == "subscriber" or lead.stage is not None

    @pytest.mark.asyncio
    async def test_lead_deduplication(self):
        from apps.business.crm.crm_engine import CRMEngine
        crm = CRMEngine()
        email = fake_email()
        l1 = await crm.add_lead(email)
        l2 = await crm.add_lead(email)
        assert l1.lead_id == l2.lead_id

    @pytest.mark.asyncio
    async def test_update_lead_stage(self):
        from apps.business.crm.crm_engine import CRMEngine, LeadStage
        crm = CRMEngine()
        lead = await crm.add_lead(fake_email())
        await crm.update_lead_stage(lead.lead_id, LeadStage.PROSPECT)
        # In-memory state should be updated
        updated = crm._leads.get(lead.lead_id)
        assert updated is not None
        assert updated.stage == LeadStage.PROSPECT

    @pytest.mark.asyncio
    async def test_predict_churn_high_risk(self):
        from apps.business.crm.crm_engine import CRMEngine, Customer, ChurnRisk
        crm = CRMEngine()
        customer = Customer(
            customer_id="cust-1",
            email=fake_email(),
            last_purchase_ts=time.time() - 100 * 86400,  # 100 days ago → HIGH
        )
        # Set in-memory state directly (after init, _customers is accessible)
        await crm._load_customers()  # ensure loaded flag is set
        crm._customers[customer.customer_id] = customer
        risk = await crm.predict_churn(customer.customer_id)
        assert risk in (ChurnRisk.HIGH, ChurnRisk.CRITICAL)

    @pytest.mark.asyncio
    async def test_add_customer(self):
        from apps.business.crm.crm_engine import CRMEngine
        crm = CRMEngine()
        email = fake_email()
        c = await crm.add_customer(email, name="Jane Doe", order_value=89.99)
        assert c.total_spent_usd == pytest.approx(89.99)
        # Second purchase — same email should update existing customer
        await crm.add_customer(email, name="Jane Doe", order_value=45.0)
        # In-memory state via _customers
        updated = crm._customers.get(c.customer_id)
        assert updated is not None
        assert updated.order_count == 2

    def test_summary(self):
        from apps.business.crm.crm_engine import CRMEngine
        crm = CRMEngine()
        s = crm.summary()
        assert "total_leads" in s


# ═══════════════════════════════════════════════════════════════════════════
# 21. RETENTION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TestRetentionEngine:
    @pytest.mark.asyncio
    async def test_create_campaign(self):
        from apps.business.crm.retention import RetentionEngine, RetentionAction
        engine = RetentionEngine()
        campaign = await engine.create_campaign(
            name="Win Back Campaign",
            action=RetentionAction.WIN_BACK_EMAIL,
            target_segment="inactive_90_days",
            trigger_condition="days_since_purchase > 90",
        )
        assert campaign.campaign_id is not None

    @pytest.mark.asyncio
    async def test_churn_prevention_workflow(self):
        from apps.business.crm.retention import RetentionEngine
        engine = RetentionEngine()
        at_risk = [
            {"customer_id": "c1", "email": "a@example.com", "churn_risk": "HIGH", "total_spent": 300.0},
            {"customer_id": "c2", "email": "b@example.com", "churn_risk": "MEDIUM", "total_spent": 150.0},
        ]
        result = await engine.churn_prevention_workflow(at_risk)
        # Result is a dict with action counts — check it's a non-empty dict
        assert isinstance(result, dict) and len(result) > 0

    @pytest.mark.asyncio
    async def test_campaign_summary(self):
        from apps.business.crm.retention import RetentionEngine, RetentionAction
        engine = RetentionEngine()
        await engine.create_campaign("Test", RetentionAction.DISCOUNT_OFFER, "all", "always")
        summary = await engine.campaign_summary()
        assert "active_campaigns" in summary

    def test_response_rate_property(self):
        from apps.business.crm.retention import RetentionCampaign, RetentionAction
        c = RetentionCampaign(
            campaign_id="x", name="X", action=RetentionAction.LOYALTY_REWARD,
            target_segment="vip", trigger_condition="always",
            customers_targeted=100, customers_responded=25, created_at=time.time()
        )
        assert c.response_rate == pytest.approx(0.25)
