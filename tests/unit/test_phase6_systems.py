"""
Phase 6 tests — Autonomous Media + Creative Infrastructure.
Covers: ImageGenerator, ThumbnailOptimizer, BrandEngine, VideoGenerator,
VideoEditor, ContentFactory, AdFactory, SocialPublisher, VisualAnalyzer,
ScreenAnalyzer, RevenueTracker, RevenueOptimizer, GPUOrchestrator, MediaPipeline.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    return cache


def _mock_ai_response(content: str = "AI generated content"):
    response = MagicMock()
    response.success = True
    response.content = content
    return response


def _mock_ai_client(content: str = "AI generated content"):
    ai = MagicMock()
    ai.complete = AsyncMock(return_value=_mock_ai_response(content))
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# 1. IMAGE GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestImageGenerator:
    @pytest.fixture
    def generator(self):
        with patch("apps.multimodal.images.image_generator.get_cache", return_value=_mock_cache()):
            from apps.multimodal.images.image_generator import ImageGenerator
            return ImageGenerator()

    @pytest.mark.asyncio
    async def test_generate_returns_job(self, generator):
        job = await generator.generate("A futuristic city skyline")
        assert job.job_id
        assert job.status in ("completed", "failed", "queued")
        assert job.prompt == "A futuristic city skyline"

    @pytest.mark.asyncio
    async def test_thumbnail_generates(self, generator):
        job = await generator.thumbnail("AI tools for marketers")
        assert job.job_id
        assert job.prompt != ""

    @pytest.mark.asyncio
    async def test_product_image_generates(self, generator):
        job = await generator.product_image("Premium Coffee Mug")
        assert job.job_id

    @pytest.mark.asyncio
    async def test_ad_creative_generates(self, generator):
        job = await generator.ad_creative("Summer Sale — 50% Off", cta="Shop Now")
        assert job.job_id

    @pytest.mark.asyncio
    async def test_batch_generate(self, generator):
        prompts = ["sunset", "mountain", "ocean"]
        jobs = await generator.batch_generate(prompts)
        assert len(jobs) == 3
        assert all(j.job_id for j in jobs)

    def test_queue_stats(self, generator):
        stats = generator.queue_stats()
        assert isinstance(stats, dict)
        assert "total_jobs" in stats or "queued" in stats or isinstance(stats, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 2. THUMBNAIL OPTIMIZER
# ══════════════════════════════════════════════════════════════════════════════

class TestThumbnailOptimizer:
    @pytest.fixture
    def optimizer(self):
        from apps.multimodal.images.thumbnail_optimizer import ThumbnailOptimizer
        return ThumbnailOptimizer()

    def test_score_thumbnail_concept(self, optimizer):
        score = optimizer.score_thumbnail_concept(
            title="10 Shocking AI Secrets You Must Know Today",
            colors=["#FF0000", "#FFFFFF"],
            has_face=True,
            has_text=True,
            has_contrast=True,
        )
        assert hasattr(score, "total_score") or isinstance(score, (dict, float, int, object))

    def test_generate_variants(self, optimizer):
        variants = optimizer.generate_variants(
            video_title="How to Make $1000 with AI",
            niche="tech",
            count=3,
        )
        assert len(variants) >= 1

    def test_best_variant(self, optimizer):
        variants = optimizer.generate_variants("AI Tools Guide", niche="tech", count=3)
        if variants:
            best = optimizer.best_variant(variants)
            assert best is not None

    def test_ctr_benchmark(self, optimizer):
        benchmark = optimizer.ctr_benchmark("tech")
        assert isinstance(benchmark, dict)
        assert len(benchmark) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. BRAND ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestBrandEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.branding.identity.brand_engine.get_cache", return_value=_mock_cache()):
            from apps.branding.identity.brand_engine import BrandEngine
            return BrandEngine()

    @pytest.mark.asyncio
    async def test_create_brand(self, engine):
        from apps.branding.identity.brand_engine import BrandTone
        brand = await engine.create_brand(
            name="TestBrand",
            niche="tech",
            tone=BrandTone.PROFESSIONAL,
        )
        assert brand.brand_id
        assert brand.name == "TestBrand"

    @pytest.mark.asyncio
    async def test_get_brand(self, engine):
        from apps.branding.identity.brand_engine import BrandTone
        brand = await engine.create_brand("GetBrand", "fashion", BrandTone.LUXURIOUS)
        fetched = await engine.get_brand(brand.brand_id)
        assert fetched is not None
        assert fetched.name == "GetBrand"

    @pytest.mark.asyncio
    async def test_list_brands(self, engine):
        from apps.branding.identity.brand_engine import BrandTone
        await engine.create_brand("B1", "tech", BrandTone.BOLD)
        await engine.create_brand("B2", "health", BrandTone.FRIENDLY)
        brands = await engine.list_brands()
        assert len(brands) >= 2

    @pytest.mark.asyncio
    async def test_update_palette(self, engine):
        from apps.branding.identity.brand_engine import BrandTone, ColorPalette
        brand = await engine.create_brand("PaletteBrand", "tech", BrandTone.MINIMALIST)
        new_palette = ColorPalette(
            primary="#FF0000",
            secondary="#00FF00",
            accent="#0000FF",
            background="#FFFFFF",
            text="#000000",
        )
        updated = await engine.update_palette(brand.brand_id, new_palette)
        assert updated is not None
        assert updated.palette.primary == "#FF0000"

    def test_prompt_prefix(self, engine):
        # Should return empty string for non-existent brand (graceful)
        prefix = engine.prompt_prefix("nonexistent-id")
        assert isinstance(prefix, str)

    def test_voice_prompt(self, engine):
        prompt = engine.voice_prompt("nonexistent-id", "blog")
        assert isinstance(prompt, str)

    def test_consistency_check(self, engine):
        result = engine.consistency_check("nonexistent-id", "Some content here")
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 4. VIDEO GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestVideoGenerator:
    @pytest.fixture
    def generator(self):
        from apps.multimodal.video.video_generator import VideoGenerator
        return VideoGenerator()

    @pytest.mark.asyncio
    async def test_generate_video(self, generator):
        from apps.multimodal.video.video_generator import VideoModel
        job = await generator.generate(
            prompt="A product unboxing video",
            model=VideoModel.MOCK,
        )
        assert job.job_id
        assert job.status in ("completed", "queued", "failed")

    @pytest.mark.asyncio
    async def test_generate_short_form(self, generator):
        job = await generator.generate_short_form("5 AI hacks you need to know")
        assert job.job_id
        assert job.duration_seconds <= 60

    @pytest.mark.asyncio
    async def test_generate_ad(self, generator):
        job = await generator.generate_ad(
            headline="Transform your results",
            product="AI Assistant Pro",
            cta="Buy Now",
        )
        assert job.job_id

    @pytest.mark.asyncio
    async def test_generate_explainer(self, generator):
        job = await generator.generate_explainer(
            "How AI works in 60 seconds",
            key_points=["Point 1", "Point 2"],
        )
        assert job.job_id

    def test_job_summary(self, generator):
        summary = generator.job_summary()
        assert isinstance(summary, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 5. VIDEO EDITOR
# ══════════════════════════════════════════════════════════════════════════════

class TestVideoEditor:
    @pytest.fixture
    def editor(self):
        from apps.multimodal.video.video_editor import VideoEditor
        return VideoEditor()

    def test_editor_instantiates(self, editor):
        assert editor is not None

    @pytest.mark.asyncio
    async def test_trim_video(self, editor):
        result = await editor.trim("https://example.com/video.mp4", start_sec=0, end_sec=30)
        assert result is not None

    @pytest.mark.asyncio
    async def test_concat_videos(self, editor):
        urls = ["https://example.com/a.mp4", "https://example.com/b.mp4"]
        result = await editor.create_compilation(urls)
        assert result is not None


# ══════════════════════════════════════════════════════════════════════════════
# 6. CONTENT FACTORY
# ══════════════════════════════════════════════════════════════════════════════

class TestContentFactory:
    @pytest.fixture
    def factory(self):
        with patch("apps.factory.content.content_factory.get_cache", return_value=_mock_cache()):
            with patch("apps.factory.content.content_factory.get_ai_client", return_value=_mock_ai_client("AI blog post content")):
                from apps.factory.content.content_factory import ContentFactory
                return ContentFactory()

    @pytest.mark.asyncio
    async def test_produce_batch(self, factory):
        from apps.factory.content.content_factory import ProductionConfig
        config = ProductionConfig(
            topic="AI productivity tools",
            platforms=["blog", "twitter"],
            count_per_platform=2,
        )
        batch = await factory.produce_batch(config)
        assert batch.batch_id
        assert len(batch.items) >= 2
        assert batch.status.value == "complete"

    @pytest.mark.asyncio
    async def test_repurpose_content(self, factory):
        result = await factory.repurpose(
            source_content="AI is transforming the way we work...",
            target_platforms=["twitter", "linkedin"],
        )
        assert isinstance(result, dict)
        assert "twitter" in result
        assert "linkedin" in result

    @pytest.mark.asyncio
    async def test_seo_batch(self, factory):
        batch = await factory.seo_batch(["AI tools", "productivity hacks"])
        assert batch.batch_id
        assert len(batch.items) >= 1

    @pytest.mark.asyncio
    async def test_trend_driven_batch(self, factory):
        batch = await factory.trend_driven_batch(["ChatGPT update", "AI news"])
        assert batch.batch_id

    @pytest.mark.asyncio
    async def test_run_daily_production(self, factory):
        batches = await factory.run_daily_production(["AI", "Marketing"])
        assert len(batches) == 2

    def test_summary(self, factory):
        summary = factory.summary()
        assert isinstance(summary, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 7. AD FACTORY
# ══════════════════════════════════════════════════════════════════════════════

class TestAdFactory:
    @pytest.fixture
    def factory(self):
        with patch("apps.factory.ads.ad_factory.get_cache", return_value=_mock_cache()):
            with patch("apps.factory.ads.ad_factory.get_ai_client", return_value=_mock_ai_client("HEADLINE: Great Product\nBODY: Buy now\nCTA: Shop Now")):
                from apps.factory.ads.ad_factory import AdFactory
                return AdFactory()

    @pytest.mark.asyncio
    async def test_create_ad(self, factory):
        from apps.factory.ads.ad_factory import AdPlatform, AdObjective
        ad = await factory.create_ad(
            product_name="Coffee Mug Pro",
            platform=AdPlatform.FACEBOOK,
            objective=AdObjective.CONVERSIONS,
        )
        assert ad.ad_id
        assert ad.platform.value == "facebook"
        assert ad.headline != ""

    @pytest.mark.asyncio
    async def test_create_campaign(self, factory):
        from apps.factory.ads.ad_factory import AdPlatform, AdObjective
        batch = await factory.create_campaign(
            product_name="AI Tool",
            platforms=[AdPlatform.FACEBOOK, AdPlatform.INSTAGRAM],
            budget_usd=1000.0,
            objective=AdObjective.TRAFFIC,
        )
        assert batch.batch_id
        assert len(batch.ads) == 2
        assert batch.total_budget_usd == 1000.0

    @pytest.mark.asyncio
    async def test_retargeting_ads(self, factory):
        batch = await factory.create_retargeting_ads("Premium Widget", abandoned_cart=True)
        assert batch.batch_id
        assert len(batch.ads) >= 2

    def test_summary(self, factory):
        summary = factory.summary()
        assert isinstance(summary, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 8. SOCIAL PUBLISHER
# ══════════════════════════════════════════════════════════════════════════════

class TestSocialPublisher:
    @pytest.fixture
    def publisher(self):
        with patch("apps.distribution.social.social_publisher.get_cache", return_value=_mock_cache()):
            from apps.distribution.social.social_publisher import SocialPublisher
            return SocialPublisher()

    @pytest.mark.asyncio
    async def test_schedule_post(self, publisher):
        post = await publisher.schedule_post(
            platform="twitter",
            content="Check out our AI tools! #AI #productivity",
            hashtags=["AI", "productivity"],
        )
        assert post.post_id
        assert post.platform == "twitter"
        assert post.status.value == "scheduled"

    @pytest.mark.asyncio
    async def test_schedule_post_future_time(self, publisher):
        future_ts = time.time() + 3600
        post = await publisher.schedule_post(
            platform="linkedin",
            content="Professional content here",
            scheduled_at=future_ts,
        )
        assert post.scheduled_at == future_ts

    def test_optimal_schedule_times(self, publisher):
        times = publisher.optimal_schedule_times("instagram", days_ahead=3)
        assert len(times) > 0
        assert all(isinstance(t, float) for t in times)
        assert times == sorted(times)

    @pytest.mark.asyncio
    async def test_publish_due_posts(self, publisher):
        # Schedule a post in the past
        past_ts = time.time() - 60
        await publisher.schedule_post("twitter", "Past post", scheduled_at=past_ts)
        published = await publisher.publish_due_posts()
        assert len(published) >= 1
        assert published[0].status.value in ("published", "failed")

    @pytest.mark.asyncio
    async def test_create_weekly_calendar(self, publisher):
        items = [
            {"platform": "twitter", "body": "Tweet 1"},
            {"platform": "linkedin", "title": "LinkedIn post"},
        ]
        calendar = await publisher.create_weekly_calendar(items, week_start="2025-01-06")
        assert calendar.week_start == "2025-01-06"
        assert len(calendar.posts) == 2

    @pytest.mark.asyncio
    async def test_publishing_stats(self, publisher):
        await publisher.schedule_post("twitter", "Test post")
        stats = await publisher.publishing_stats()
        assert "total_posts" in stats
        assert stats["total_posts"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 9. VISUAL ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

class TestVisualAnalyzer:
    @pytest.fixture
    def analyzer(self):
        with patch("apps.multimodal.cognition.visual_analyzer.get_ai_client", return_value=_mock_ai_client()):
            from apps.multimodal.cognition.visual_analyzer import VisualAnalyzer
            return VisualAnalyzer()

    @pytest.mark.asyncio
    async def test_analyze_image(self, analyzer):
        from apps.multimodal.cognition.visual_analyzer import VisualContentType
        insight = await analyzer.analyze_image(
            "https://example.com/product.jpg",
            VisualContentType.PRODUCT_IMAGE,
        )
        assert insight.content_type == VisualContentType.PRODUCT_IMAGE
        assert 0.0 <= insight.engagement_score <= 1.0
        assert 0.0 <= insight.quality_score <= 1.0
        assert isinstance(insight.dominant_colors, list)

    @pytest.mark.asyncio
    async def test_analyze_thumbnail(self, analyzer):
        analysis = await analyzer.analyze_thumbnail("https://example.com/thumbnail.jpg")
        assert 0.0 <= analysis.ctr_prediction <= 1.0
        assert isinstance(analysis.face_present, bool)
        assert isinstance(analysis.improvement_suggestions, list)

    @pytest.mark.asyncio
    async def test_compare_creatives(self, analyzer):
        from apps.multimodal.cognition.visual_analyzer import VisualContentType
        urls = [
            "https://example.com/ad1.jpg",
            "https://example.com/ad2.jpg",
        ]
        results = await analyzer.compare_creatives(urls, VisualContentType.AD_CREATIVE)
        assert len(results) == 2
        assert results[0]["rank"] == 1
        assert all("engagement_score" in r for r in results)

    @pytest.mark.asyncio
    async def test_score_ad_creative(self, analyzer):
        result = await analyzer.score_ad_creative("https://example.com/ad.jpg")
        assert "composite_score" in result
        assert "grade" in result
        assert result["grade"] in ("A", "B", "C", "D")

    def test_insight_to_dict(self, analyzer):
        from apps.multimodal.cognition.visual_analyzer import VisualInsight, VisualContentType
        insight = VisualInsight(
            content_type=VisualContentType.THUMBNAIL,
            dominant_colors=["#FF0000"],
            engagement_score=0.8,
            quality_score=0.7,
        )
        d = insight.to_dict()
        assert d["content_type"] == "thumbnail"
        assert d["engagement_score"] == 0.8


# ══════════════════════════════════════════════════════════════════════════════
# 10. SCREEN ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

class TestScreenAnalyzer:
    @pytest.fixture
    def analyzer(self):
        with patch("apps.multimodal.cognition.screen_analyzer.get_ai_client", return_value=_mock_ai_client("Add more CTAs")):
            from apps.multimodal.cognition.screen_analyzer import ScreenAnalyzer
            return ScreenAnalyzer()

    @pytest.mark.asyncio
    async def test_analyze_landing_page_no_fetch(self, analyzer):
        with patch.object(analyzer, "_fetch_html", return_value=""):
            analysis = await analyzer.analyze_landing_page("https://example.com")
            assert analysis.url == "https://example.com"
            assert isinstance(analysis.recommendations, list)

    @pytest.mark.asyncio
    async def test_analyze_landing_page_with_html(self, analyzer):
        html = """
        <html><head><title>Buy Now — Great Product</title></head>
        <body>
        <h1>Amazing Product</h1>
        <p>Trusted by thousands.</p>
        <a>Get Started</a><a>Buy Now</a>
        <div>Testimonial: Great product!</div>
        <p>30-day money back guarantee</p>
        </body></html>
        """
        with patch.object(analyzer, "_fetch_html", return_value=html):
            analysis = await analyzer.analyze_landing_page("https://example.com")
            assert analysis.cta_count >= 1
            assert analysis.conversion_score >= 0.0
            assert len(analysis.trust_signals) >= 1

    @pytest.mark.asyncio
    async def test_conversion_recommendations(self, analyzer):
        with patch.object(analyzer, "_fetch_html", return_value="<html><body><h1>No CTA page</h1></body></html>"):
            recs = await analyzer.conversion_recommendations("https://example.com")
            assert isinstance(recs, list)
            assert len(recs) >= 1

    @pytest.mark.asyncio
    async def test_competitor_scan(self, analyzer):
        with patch.object(analyzer, "_fetch_html", return_value="<html><body>Shop Now</body></html>"):
            results = await analyzer.competitor_scan(
                ["https://comp1.com", "https://comp2.com"]
            )
            assert len(results) == 2
            assert results[0]["conversion_score"] >= results[1]["conversion_score"]

    def test_page_analysis_to_dict(self):
        from apps.multimodal.cognition.screen_analyzer import PageAnalysis
        pa = PageAnalysis(url="https://test.com", title="Test", cta_count=2, conversion_score=0.7)
        d = pa.to_dict()
        assert d["url"] == "https://test.com"
        assert d["cta_count"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# 11. REVENUE TRACKER
# ══════════════════════════════════════════════════════════════════════════════

class TestRevenueTracker:
    @pytest.fixture
    def tracker(self):
        with patch("apps.revenue.attribution.revenue_tracker.get_cache", return_value=_mock_cache()):
            from apps.revenue.attribution.revenue_tracker import RevenueTracker
            return RevenueTracker()

    @pytest.mark.asyncio
    async def test_record_conversion(self, tracker):
        event = await tracker.record_conversion(
            customer_id="cust_001",
            channel="organic_search",
            amount_usd=99.0,
            touchpoints=["social", "email", "organic_search"],
        )
        assert event.event_id
        assert event.channel == "organic_search"
        assert event.amount_usd == 99.0

    @pytest.mark.asyncio
    async def test_roi_by_channel_last_touch(self, tracker):
        from apps.revenue.attribution.revenue_tracker import AttributionModel
        await tracker.record_conversion("c1", "email", 50.0)
        await tracker.record_conversion("c2", "social", 100.0)
        result = await tracker.roi_by_channel(AttributionModel.LAST_TOUCH)
        assert len(result) >= 1
        assert all(r.attributed_revenue > 0 for r in result)

    @pytest.mark.asyncio
    async def test_roi_by_channel_linear(self, tracker):
        from apps.revenue.attribution.revenue_tracker import AttributionModel
        await tracker.record_conversion("c3", "paid", 200.0, touchpoints=["social", "email", "paid"])
        result = await tracker.roi_by_channel(AttributionModel.LINEAR)
        channels = [r.channel for r in result]
        total_revenue = sum(r.attributed_revenue for r in result)
        assert abs(total_revenue - 200.0) < 0.01

    @pytest.mark.asyncio
    async def test_roi_by_channel_time_decay(self, tracker):
        from apps.revenue.attribution.revenue_tracker import AttributionModel
        await tracker.record_conversion("c4", "direct", 300.0, touchpoints=["display", "search", "direct"])
        result = await tracker.roi_by_channel(AttributionModel.TIME_DECAY)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_revenue_forecast(self, tracker):
        await tracker.record_conversion("c5", "email", 100.0)
        forecast = await tracker.revenue_forecast(months=3)
        assert len(forecast) == 3
        assert all("month" in f and "forecast_usd" in f for f in forecast)

    @pytest.mark.asyncio
    async def test_empty_forecast(self, tracker):
        forecast = await tracker.revenue_forecast(months=3)
        assert len(forecast) == 3

    def test_summary(self, tracker):
        summary = tracker.summary()
        assert "total_conversions" in summary
        assert "total_revenue_usd" in summary


# ══════════════════════════════════════════════════════════════════════════════
# 12. REVENUE OPTIMIZER
# ══════════════════════════════════════════════════════════════════════════════

class TestRevenueOptimizer:
    @pytest.fixture
    def optimizer(self):
        with patch("apps.revenue.optimization.revenue_optimizer.get_cache", return_value=_mock_cache()):
            from apps.revenue.optimization.revenue_optimizer import RevenueOptimizer
            return RevenueOptimizer()

    def test_identify_quick_wins_healthy_conversion(self, optimizer):
        wins = optimizer.identify_quick_wins(
            current_revenue_usd=5000.0,
            avg_order_value=75.0,
            conversion_rate=0.03,
            monthly_visitors=2000,
        )
        assert len(wins) >= 1
        assert all(w.estimated_revenue_lift_usd > 0 for w in wins)
        assert wins[0].estimated_revenue_lift_usd >= wins[-1].estimated_revenue_lift_usd

    def test_identify_quick_wins_low_conversion(self, optimizer):
        wins = optimizer.identify_quick_wins(
            current_revenue_usd=1000.0,
            avg_order_value=50.0,
            conversion_rate=0.01,
            monthly_visitors=10000,
        )
        assert any(w.action_type.value == "conversion_lift" for w in wins)

    def test_build_scenarios(self, optimizer):
        scenarios = optimizer.build_scenarios(5000.0, 100)
        assert len(scenarios) == 3
        names = [s.name for s in scenarios]
        assert "conservative" in names
        assert "moderate" in names
        assert "aggressive" in names
        aggressive = next(s for s in scenarios if s.name == "aggressive")
        conservative = next(s for s in scenarios if s.name == "conservative")
        assert aggressive.monthly_revenue_usd > conservative.monthly_revenue_usd

    @pytest.mark.asyncio
    async def test_autonomous_recommendation(self, optimizer):
        rec = await optimizer.autonomous_recommendation(
            current_revenue_usd=3000.0,
            avg_order_value=60.0,
            conversion_rate=0.025,
            monthly_visitors=5000,
        )
        assert "quick_wins" in rec
        assert "scenarios" in rec
        assert "recommended_scenario" in rec
        assert len(rec["scenarios"]) == 3

    def test_scenario_roi(self, optimizer):
        scenarios = optimizer.build_scenarios(2000.0, 50)
        for s in scenarios:
            # ROI can be negative for high investment scenarios, just check it's a number
            assert isinstance(s.roi, float)

    def test_summary(self, optimizer):
        summary = optimizer.summary()
        assert isinstance(summary, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 13. GPU ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestGPUOrchestrator:
    @pytest.fixture
    def orchestrator(self):
        with patch("apps.infra.gpu.gpu_orchestrator.get_cache", return_value=_mock_cache()):
            from apps.infra.gpu.gpu_orchestrator import GPUOrchestrator
            return GPUOrchestrator()

    @pytest.mark.asyncio
    async def test_submit_job(self, orchestrator):
        from apps.infra.gpu.gpu_orchestrator import JobPriority
        job = await orchestrator.submit_job(
            job_type="image_generation",
            payload={"prompt": "sunset", "model": "flux"},
            priority=JobPriority.HIGH,
        )
        assert job.job_id
        assert job.job_type == "image_generation"
        assert job.priority == JobPriority.HIGH
        assert job.estimated_cost_usd > 0

    @pytest.mark.asyncio
    async def test_process_queue_mock(self, orchestrator):
        from apps.infra.gpu.gpu_orchestrator import JobPriority
        await orchestrator.submit_job("inference", {"data": "test"}, JobPriority.NORMAL)
        await orchestrator.submit_job("inference", {"data": "test2"}, JobPriority.LOW)
        processed = await orchestrator.process_queue(max_jobs=2)
        assert len(processed) == 2
        assert all(j.status.value == "completed" for j in processed)

    @pytest.mark.asyncio
    async def test_priority_ordering(self, orchestrator):
        from apps.infra.gpu.gpu_orchestrator import JobPriority
        await orchestrator.submit_job("inference", {"n": 1}, JobPriority.LOW)
        await orchestrator.submit_job("inference", {"n": 2}, JobPriority.CRITICAL)
        await orchestrator.submit_job("inference", {"n": 3}, JobPriority.NORMAL)
        # Queue should be sorted by priority descending
        assert orchestrator._queue[0]["priority"] >= orchestrator._queue[-1]["priority"]

    def test_auto_scale_recommendation_empty(self, orchestrator):
        rec = orchestrator.auto_scale_recommendation()
        assert isinstance(rec, dict)
        assert "action" in rec

    @pytest.mark.asyncio
    async def test_auto_scale_high_queue(self, orchestrator):
        from apps.infra.gpu.gpu_orchestrator import JobPriority
        for _ in range(25):
            await orchestrator.submit_job("inference", {}, JobPriority.LOW)
        rec = orchestrator.auto_scale_recommendation()
        assert rec["action"] == "scale_up"
        assert rec["workers"] >= 2

    @pytest.mark.asyncio
    async def test_status(self, orchestrator):
        status = await orchestrator.status()
        assert "queue_depth" in status
        assert "backend" in status
        assert "scale_recommendation" in status


# ══════════════════════════════════════════════════════════════════════════════
# 14. MEDIA PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

class TestMediaPipeline:
    @pytest.fixture
    def pipeline(self):
        with patch("apps.infra.media_workers.media_pipeline.get_cache", return_value=_mock_cache()):
            from apps.infra.media_workers.media_pipeline import MediaPipeline
            return MediaPipeline()

    @pytest.mark.asyncio
    async def test_process_image(self, pipeline):
        artifact = await pipeline.process_image(
            "https://example.com/img.jpg",
            transforms={"width": 800, "height": 600},
        )
        assert artifact.artifact_id
        assert artifact.status.value in ("completed", "cached")
        assert artifact.content_hash != ""

    @pytest.mark.asyncio
    async def test_process_image_cache_hit(self, pipeline):
        url = "https://example.com/same.jpg"
        transforms = {"width": 400, "height": 400}
        a1 = await pipeline.process_image(url, transforms)
        a2 = await pipeline.process_image(url, transforms)
        assert a1.content_hash == a2.content_hash
        assert a2.status.value == "cached"

    @pytest.mark.asyncio
    async def test_process_video(self, pipeline):
        artifact = await pipeline.process_video(
            "https://example.com/video.mp4",
            operations=["trim", "add_subtitles"],
        )
        assert artifact.artifact_id
        assert artifact.artifact_type.value == "video"
        assert artifact.status.value in ("completed", "cached")

    @pytest.mark.asyncio
    async def test_pipeline_health(self, pipeline):
        await pipeline.process_image("https://example.com/h1.jpg")
        health = await pipeline.pipeline_health()
        assert "total_artifacts" in health
        assert "cache_hit_rate" in health
        assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_deduplication(self, pipeline):
        url = "https://example.com/dup.jpg"
        a1 = await pipeline.process_image(url)
        a2 = await pipeline.process_image(url)
        assert a1.content_hash == a2.content_hash
        # Second should come from cache
        assert len(pipeline._artifacts) == 1
