"""
Phase 6 tests — Autonomous Media + Creative Infrastructure.
Covers: BrandEngine, SocialPublisher, GPUOrchestrator, MediaPipeline.

(ImageGenerator, ThumbnailOptimizer, VideoGenerator, VideoEditor, ContentFactory,
AdFactory, VisualAnalyzer, and ScreenAnalyzer coverage was removed along with
apps/multimodal/ and apps/factory/, which duplicated live functionality already
covered by apps/core/tools/multimodal.py, video_engine.py, multimedia_engine.py,
creative_engine.py, and apps/core/tools/income_loop.py, and had zero callers
outside this test file. RevenueTracker/RevenueOptimizer coverage was removed
along with apps/revenue/, which duplicated the live
apps/core/engines/revenue_attribution.py.)
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
# 1. BRAND ENGINE
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
# 2. SOCIAL PUBLISHER
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
# 3. GPU ORCHESTRATOR
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
# 4. MEDIA PIPELINE
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
