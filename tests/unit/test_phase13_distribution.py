"""Phase 13 tests — Distribution Engines (LinkedInPublisher, TwitterEngine, TikTokEngine, BlogPublisher)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="..."):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── LinkedIn Publisher ────────────────────────────────────────────────────────

_LINKEDIN_AI_CONTENT = (
    "🚀 5 Lessons from Building an AI Business\n\n"
    "1. Start before you're ready\n"
    "2. Ship every day\n\n"
    "#AI #business #entrepreneurship"
)


class TestLinkedInPublisher:
    @pytest.fixture
    def publisher(self):
        with patch("apps.distribution.linkedin.linkedin_publisher.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.distribution.linkedin.linkedin_publisher.get_ai_client",
                return_value=_mock_ai(_LINKEDIN_AI_CONTENT),
            ):
                from apps.distribution.linkedin.linkedin_publisher import LinkedInPublisher
                return LinkedInPublisher()

    @pytest.mark.asyncio
    async def test_create_post_returns_post(self, publisher):
        from apps.distribution.linkedin.linkedin_publisher import LinkedInPost
        post = await publisher.create_post("AI business lessons")
        assert isinstance(post, LinkedInPost)
        assert post.post_id

    @pytest.mark.asyncio
    async def test_create_post_has_content(self, publisher):
        post = await publisher.create_post("AI business lessons")
        assert len(post.content) > 0

    @pytest.mark.asyncio
    async def test_create_post_has_hook(self, publisher):
        post = await publisher.create_post("AI business lessons")
        assert len(post.hook) > 0

    @pytest.mark.asyncio
    async def test_create_post_engagement_score_in_range(self, publisher):
        post = await publisher.create_post("AI business lessons")
        assert 0 < post.engagement_score <= 1

    @pytest.mark.asyncio
    async def test_create_post_has_estimated_impressions(self, publisher):
        post = await publisher.create_post("AI business lessons")
        assert post.estimated_impressions > 0

    @pytest.mark.asyncio
    async def test_generate_hook_variants_returns_list(self, publisher):
        hooks = await publisher.generate_hook_variants("AI business")
        assert isinstance(hooks, list)
        assert len(hooks) >= 1

    @pytest.mark.asyncio
    async def test_generate_carousel_outline_returns_dict(self, publisher):
        result = await publisher.generate_carousel_outline("AI business lessons")
        assert "slides" in result

    @pytest.mark.asyncio
    async def test_optimize_for_algorithm_returns_post(self, publisher):
        from apps.distribution.linkedin.linkedin_publisher import LinkedInPost
        original = await publisher.create_post("AI business lessons")
        optimized = await publisher.optimize_for_algorithm(original)
        assert isinstance(optimized, LinkedInPost)

    @pytest.mark.asyncio
    async def test_post_analytics_has_required_keys(self, publisher):
        await publisher.create_post("AI business lessons")
        analytics = publisher.post_analytics()
        assert "total_posts" in analytics
        assert "avg_engagement_score" in analytics
        assert "avg_impressions" in analytics

    @pytest.mark.asyncio
    async def test_posts_accumulate(self, publisher):
        await publisher.create_post("AI business lessons")
        await publisher.create_post("Entrepreneurship tips")
        assert len(publisher._posts) == 2


# ── Twitter Engine ────────────────────────────────────────────────────────────

_TWITTER_AI_CONTENT = (
    "The secret to building wealth with AI\n\n"
    "Most people are thinking about this wrong.\n\n"
    "Here's the truth:\n\n"
    "Thread 🧵\n\n"
    "1/ Start with distribution\n\n"
    "2/ Build systems not tasks\n\n"
    "3/ Compound daily\n\n"
    "Follow for more AI business insights 👇"
)


class TestTwitterEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.distribution.twitter.twitter_engine.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.distribution.twitter.twitter_engine.get_ai_client",
                return_value=_mock_ai(_TWITTER_AI_CONTENT),
            ):
                from apps.distribution.twitter.twitter_engine import TwitterEngine
                return TwitterEngine()

    @pytest.mark.asyncio
    async def test_create_thread_returns_thread(self, engine):
        from apps.distribution.twitter.twitter_engine import TwitterThread
        thread = await engine.create_thread("building wealth with AI")
        assert isinstance(thread, TwitterThread)
        assert thread.thread_id

    @pytest.mark.asyncio
    async def test_thread_has_tweets(self, engine):
        thread = await engine.create_thread("building wealth with AI")
        assert len(thread.tweets) >= 1

    @pytest.mark.asyncio
    async def test_thread_has_hook(self, engine):
        thread = await engine.create_thread("building wealth with AI")
        assert len(thread.hook) > 0

    @pytest.mark.asyncio
    async def test_thread_viral_score_in_range(self, engine):
        thread = await engine.create_thread("building wealth with AI")
        assert 0 < thread.viral_score <= 1

    @pytest.mark.asyncio
    async def test_thread_has_estimated_reach(self, engine):
        thread = await engine.create_thread("building wealth with AI")
        assert thread.estimated_reach > 0

    @pytest.mark.asyncio
    async def test_optimize_hook_returns_string(self, engine):
        hook = await engine.optimize_hook("building wealth with AI")
        assert isinstance(hook, str)
        assert len(hook) > 0

    @pytest.mark.asyncio
    async def test_generate_tweet_returns_tweet(self, engine):
        from apps.distribution.twitter.twitter_engine import Tweet
        tweet = await engine.generate_tweet("AI productivity")
        assert isinstance(tweet, Tweet)

    @pytest.mark.asyncio
    async def test_generate_tweet_content_under_280(self, engine):
        tweet = await engine.generate_tweet("AI productivity")
        assert len(tweet.content) <= 280

    @pytest.mark.asyncio
    async def test_repurpose_to_thread_returns_thread(self, engine):
        from apps.distribution.twitter.twitter_engine import TwitterThread
        long_content = (
            "Building wealth with AI is not about replacing humans — it's about leveraging "
            "systems that compound over time. Start with distribution, then build automation "
            "layers, and finally create scalable assets that work while you sleep."
        )
        thread = await engine.repurpose_to_thread(long_content, "AI wealth building")
        assert isinstance(thread, TwitterThread)

    @pytest.mark.asyncio
    async def test_twitter_analytics_has_required_keys(self, engine):
        await engine.create_thread("building wealth with AI")
        analytics = engine.twitter_analytics()
        assert "total_threads" in analytics
        assert "total_tweets" in analytics
        assert "avg_viral_score" in analytics


# ── TikTok Engine ─────────────────────────────────────────────────────────────

_TIKTOK_AI_CONTENT = (
    "HOOK: Wait— you're still doing this manually? Stop.\n"
    "MAIN: Here's the 3-step system every creator uses to 10x their content. "
    "Step 1: batch create. Step 2: auto-schedule. Step 3: analyze and double down.\n"
    "CTA: Follow for more AI automation tips!\n"
    "HASHTAGS: #aitools #contentcreator #productivity #automation #tiktok\n"
    "SOUND: upbeat motivational"
)


class TestTikTokEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.distribution.tiktok.tiktok_engine.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.distribution.tiktok.tiktok_engine.get_ai_client",
                return_value=_mock_ai(_TIKTOK_AI_CONTENT),
            ):
                from apps.distribution.tiktok.tiktok_engine import TikTokEngine
                return TikTokEngine()

    @pytest.mark.asyncio
    async def test_generate_script_returns_script(self, engine):
        from apps.distribution.tiktok.tiktok_engine import TikTokScript
        script = await engine.generate_script("content automation", "AI tools")
        assert isinstance(script, TikTokScript)
        assert script.script_id

    @pytest.mark.asyncio
    async def test_script_has_hook(self, engine):
        script = await engine.generate_script("content automation", "AI tools")
        assert len(script.hook) > 0

    @pytest.mark.asyncio
    async def test_script_has_main_content(self, engine):
        script = await engine.generate_script("content automation", "AI tools")
        assert len(script.main_content) > 0

    @pytest.mark.asyncio
    async def test_script_has_cta(self, engine):
        script = await engine.generate_script("content automation", "AI tools")
        assert len(script.cta) > 0

    @pytest.mark.asyncio
    async def test_script_has_hashtags(self, engine):
        script = await engine.generate_script("content automation", "AI tools")
        assert isinstance(script.hashtags, list)
        assert len(script.hashtags) >= 1

    @pytest.mark.asyncio
    async def test_script_viral_potential_in_range(self, engine):
        script = await engine.generate_script("content automation", "AI tools")
        assert 0 < script.viral_potential <= 1

    @pytest.mark.asyncio
    async def test_script_estimated_views_positive(self, engine):
        script = await engine.generate_script("content automation", "AI tools")
        assert script.estimated_views > 0

    @pytest.mark.asyncio
    async def test_batch_generate_returns_list(self, engine):
        topics = ["batch creating content", "auto-scheduling posts", "analyzing metrics"]
        results = await engine.batch_generate(topics, "AI tools")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_generate_trend_hooks_returns_list(self, engine):
        from apps.distribution.tiktok.tiktok_engine import TrendHook
        hooks = await engine.generate_trend_hooks("AI tools")
        assert len(hooks) >= 1
        assert all(isinstance(h, TrendHook) for h in hooks)

    @pytest.mark.asyncio
    async def test_tiktok_analytics_has_required_keys(self, engine):
        await engine.generate_script("content automation", "AI tools")
        analytics = engine.tiktok_analytics()
        assert "total_scripts" in analytics
        assert "avg_viral_potential" in analytics
        assert "avg_estimated_views" in analytics


# ── Blog Publisher ────────────────────────────────────────────────────────────

_BLOG_AI_CONTENT = (
    "5 Ways AI Is Transforming Small Business Revenue in 2024\n\n"
    "Artificial intelligence is no longer just for big corporations. Small businesses are now "
    "leveraging AI tools to automate operations, generate content, and scale revenue without "
    "hiring large teams.\n\n"
    "H2: 1. Automated Content Creation\n\n"
    "AI tools like Claude can generate blog posts, social media content, and email sequences "
    "in minutes...\n\n"
    "H2: 2. Customer Service Automation\n\n"
    "Chatbots powered by AI handle 80% of customer inquiries automatically..."
)


class TestBlogPublisher:
    @pytest.fixture
    def publisher(self):
        with patch("apps.distribution.blog.blog_publisher.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.distribution.blog.blog_publisher.get_ai_client",
                return_value=_mock_ai(_BLOG_AI_CONTENT),
            ):
                from apps.distribution.blog.blog_publisher import BlogPublisher
                return BlogPublisher()

    @pytest.mark.asyncio
    async def test_write_post_returns_blog_post(self, publisher):
        from apps.distribution.blog.blog_publisher import BlogPost
        post = await publisher.write_post("AI for small business", "AI small business revenue")
        assert isinstance(post, BlogPost)
        assert post.post_id

    @pytest.mark.asyncio
    async def test_post_has_title(self, publisher):
        post = await publisher.write_post("AI for small business", "AI small business revenue")
        assert len(post.title) > 0

    @pytest.mark.asyncio
    async def test_post_has_body(self, publisher):
        post = await publisher.write_post("AI for small business", "AI small business revenue")
        assert len(post.body) > 0

    @pytest.mark.asyncio
    async def test_post_has_target_keyword(self, publisher):
        post = await publisher.write_post("AI for small business", "AI small business revenue")
        assert len(post.target_keyword) > 0

    @pytest.mark.asyncio
    async def test_post_seo_score_in_range(self, publisher):
        post = await publisher.write_post("AI for small business", "AI small business revenue")
        assert 0 < post.seo_score <= 1

    @pytest.mark.asyncio
    async def test_post_has_secondary_keywords(self, publisher):
        post = await publisher.write_post("AI for small business", "AI small business revenue")
        assert isinstance(post.secondary_keywords, list)
        assert len(post.secondary_keywords) >= 2

    @pytest.mark.asyncio
    async def test_post_has_slug(self, publisher):
        post = await publisher.write_post("AI for small business", "AI small business revenue")
        assert len(post.slug) > 0
        assert " " not in post.slug

    @pytest.mark.asyncio
    async def test_generate_outline_returns_list(self, publisher):
        outline = await publisher.generate_outline("AI for small business", "AI small business revenue")
        assert len(outline) >= 1

    @pytest.mark.asyncio
    async def test_generate_topic_cluster_returns_list(self, publisher):
        cluster = await publisher.generate_topic_cluster("AI for small business")
        assert len(cluster) >= 1

    @pytest.mark.asyncio
    async def test_blog_stats_has_required_keys(self, publisher):
        await publisher.write_post("AI for small business", "AI small business revenue")
        stats = publisher.blog_stats()
        assert "total_posts" in stats
        assert "avg_seo_score" in stats
        assert "avg_word_count" in stats
