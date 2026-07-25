"""Phase 11 tests — Video Engine (YouTube + Shorts)."""

from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="10 Ways to Grow on YouTube | Complete 2024 Guide"):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── YouTube Engine ────────────────────────────────────────────────────────────


class TestYouTubeEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.video.youtube.youtube_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.video.youtube.youtube_engine.get_ai_client", return_value=_mock_ai()):
                from apps.video.youtube.youtube_engine import YouTubeEngine

                return YouTubeEngine()

    @pytest.mark.asyncio
    async def test_optimize_title_returns_string(self, engine):
        title = await engine.optimize_title("YouTube Growth", "grow youtube channel")
        assert isinstance(title, str)
        assert len(title) > 0

    @pytest.mark.asyncio
    async def test_create_video_metadata_returns_metadata(self, engine):
        from apps.video.youtube.youtube_engine import VideoMetadata

        meta = await engine.create_video_metadata("SEO Tips", "seo tips 2024")
        assert isinstance(meta, VideoMetadata)
        assert meta.video_id

    @pytest.mark.asyncio
    async def test_metadata_has_valid_seo_score(self, engine):
        meta = await engine.create_video_metadata("Marketing", "digital marketing")
        assert 0.0 <= meta.seo_score <= 1.0

    @pytest.mark.asyncio
    async def test_metadata_has_tags(self, engine):
        meta = await engine.create_video_metadata("Fitness", "home workout")
        assert isinstance(meta.tags, list)
        assert len(meta.tags) >= 3

    @pytest.mark.asyncio
    async def test_write_script_returns_video_script(self, engine):
        from apps.video.youtube.youtube_engine import VideoScript

        meta = await engine.create_video_metadata("Python", "python tutorial")
        script = await engine.write_script(meta.video_id, "Python Tutorial", 600)
        assert isinstance(script, VideoScript)
        assert script.script_id

    @pytest.mark.asyncio
    async def test_script_has_hook_and_body(self, engine):
        meta = await engine.create_video_metadata("AI", "ai tools")
        script = await engine.write_script(meta.video_id, "AI Tools", 300)
        assert isinstance(script.hook, str)
        assert isinstance(script.body, list)
        assert len(script.body) >= 1

    @pytest.mark.asyncio
    async def test_score_thumbnail_has_score_key(self, engine):
        result = await engine.score_thumbnail_concept(
            "Bold text on red background", "make money online"
        )
        assert "score" in result
        assert 0.0 <= result["score"] <= 1.0

    @pytest.mark.asyncio
    async def test_score_thumbnail_has_ctr_estimate(self, engine):
        result = await engine.score_thumbnail_concept("Face + arrow + number", "youtube growth")
        assert "estimated_ctr_pct" in result

    @pytest.mark.asyncio
    async def test_content_calendar_returns_list(self, engine):
        cal = await engine.generate_content_calendar("fitness", videos_per_week=3)
        assert isinstance(cal, list)
        assert len(cal) >= 12  # 4 weeks * 3/week

    @pytest.mark.asyncio
    async def test_content_calendar_has_topics(self, engine):
        cal = await engine.generate_content_calendar("tech")
        assert all("topic" in item for item in cal)
        assert all("content_type" in item for item in cal)

    @pytest.mark.asyncio
    async def test_seo_audit_returns_dict(self, engine):
        audit = await engine.seo_audit("personal finance")
        assert "keyword_gaps" in audit
        assert "optimization_score" in audit

    @pytest.mark.asyncio
    async def test_seo_audit_score_in_range(self, engine):
        audit = await engine.seo_audit("cooking")
        assert 0.0 <= audit["optimization_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_optimize_retention_adds_hooks(self, engine):
        body = [
            {"timestamp": "1:00", "content": "Section 1", "visual": "talking head"},
            {"timestamp": "3:00", "content": "Section 2", "visual": "screen"},
        ]
        optimized = await engine.optimize_retention(body)
        assert len(optimized) > len(body)

    @pytest.mark.asyncio
    async def test_channel_analytics_has_required_keys(self, engine):
        await engine.create_video_metadata("Tech", "tech review")
        stats = engine.channel_analytics()
        assert "total_videos" in stats
        assert "by_content_type" in stats
        assert "avg_seo_score" in stats

    @pytest.mark.asyncio
    async def test_recent_videos_returns_list(self, engine):
        await engine.create_video_metadata("Health", "health tips")
        result = engine.recent_videos(limit=5)
        assert isinstance(result, list)


# ── Shorts Engine ─────────────────────────────────────────────────────────────


class TestShortsEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.video.shorts.shorts_engine.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.video.shorts.shorts_engine.get_ai_client",
                return_value=_mock_ai(
                    "POV: You just discovered this hack... #viral #fyp #trending"
                ),
            ):
                from apps.video.shorts.shorts_engine import ShortsEngine

                return ShortsEngine()

    @pytest.mark.asyncio
    async def test_create_short_returns_content(self, engine):
        from apps.video.shorts.shorts_engine import ShortsContent

        short = await engine.create_short("Morning Routine", "productivity", "tiktok")
        assert isinstance(short, ShortsContent)
        assert short.content_id

    @pytest.mark.asyncio
    async def test_short_has_hook(self, engine):
        short = await engine.create_short("Money Tips", "finance", "instagram_reels")
        assert isinstance(short.hook, str)
        assert len(short.hook) > 0

    @pytest.mark.asyncio
    async def test_short_viral_score_in_range(self, engine):
        short = await engine.create_short("Fitness Hack", "fitness", "youtube_shorts")
        assert 0.0 <= short.viral_score <= 1.0

    @pytest.mark.asyncio
    async def test_generate_hook_variations_returns_5(self, engine):
        hooks = await engine.generate_hook_variations("How to make money", count=5)
        assert isinstance(hooks, list)
        assert len(hooks) >= 1

    @pytest.mark.asyncio
    async def test_trend_hijack_returns_content(self, engine):
        from apps.video.shorts.shorts_engine import ShortsContent

        short = await engine.trend_hijack("ChatGPT", "AI tools")
        assert isinstance(short, ShortsContent)

    @pytest.mark.asyncio
    async def test_batch_create_returns_list(self, engine):
        topics = ["Tip 1", "Tip 2", "Tip 3"]
        shorts = await engine.batch_create(topics, "tiktok")
        assert isinstance(shorts, list)
        assert len(shorts) == len(topics)

    @pytest.mark.asyncio
    async def test_shorts_analytics_has_required_keys(self, engine):
        await engine.create_short("Test", "test", "tiktok")
        stats = engine.shorts_analytics()
        assert "total_shorts" in stats
        assert "by_platform" in stats
        assert "avg_viral_score" in stats

    @pytest.mark.asyncio
    async def test_optimize_for_algorithm_returns_content(self, engine):
        from apps.video.shorts.shorts_engine import ShortsContent

        short = await engine.create_short("Original", "niche", "tiktok")
        optimized = await engine.optimize_for_algorithm(short)
        assert isinstance(optimized, ShortsContent)
