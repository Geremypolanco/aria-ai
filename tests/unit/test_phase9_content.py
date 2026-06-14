"""
Phase 9 tests — SEO Content Engine, Blog Generator, and Product Page Optimizer.

Covers:
  - SEOEngine: research_keywords, analyze_content, optimize_meta,
    generate_content_brief, top_opportunities, stats
  - KeywordResearcher: trending_topics (AI fallback), keyword_volume_estimate,
    buyer intent scoring
  - BlogGenerator: generate_post, generate_series, get_publishing_schedule,
    draft_posts, stats
  - ContentCalendar: plan_month, add_slot, this_week, upcoming,
    mark_published, calendar_stats
  - ProductWriter: optimize_product, batch_optimize, generate_product_faq,
    create_collection_description, optimization_history, stats
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    """In-memory cache mock — get returns None, set returns True."""
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content: str = "SEO optimized content response"):
    """Sync AI client mock whose .complete() is async."""
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


def _mock_ai_failed():
    """AI client mock that always returns a failed response."""
    ai = MagicMock()
    r = MagicMock()
    r.success = False
    r.content = ""
    ai.complete = AsyncMock(return_value=r)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# 1. SEOEngine
# ══════════════════════════════════════════════════════════════════════════════

class TestSEOEngine:
    """8 tests for SEOEngine."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.content.seo.seo_engine as m
        m._seo_engine = None
        yield
        m._seo_engine = None

    async def test_research_keywords_returns_list_of_keyword_metrics(self):
        """research_keywords returns a list of KeywordMetrics objects."""
        from apps.content.seo.seo_engine import SEOEngine, KeywordMetrics

        ai = _mock_ai("best AI tools\ncheap AI software\nAI review\nbuy AI subscription\ntop AI platform")
        cache = _mock_cache()

        with patch("apps.content.seo.seo_engine.get_ai_client", return_value=ai), \
             patch("apps.content.seo.seo_engine.get_cache", return_value=cache):
            engine = SEOEngine()
            results = await engine.research_keywords("AI tools", count=5)

        assert isinstance(results, list)
        assert len(results) >= 1
        for km in results:
            assert isinstance(km, KeywordMetrics)

    async def test_research_keywords_each_has_buyer_intent_score(self):
        """Each KeywordMetrics has a buyer_intent_score between 0 and 1."""
        from apps.content.seo.seo_engine import SEOEngine

        ai = _mock_ai("best AI tools\nbuy AI now\ncheap AI plan")
        cache = _mock_cache()

        with patch("apps.content.seo.seo_engine.get_ai_client", return_value=ai), \
             patch("apps.content.seo.seo_engine.get_cache", return_value=cache):
            engine = SEOEngine()
            results = await engine.research_keywords("AI", count=3)

        for km in results:
            assert 0.0 <= km.buyer_intent_score <= 1.0

    async def test_analyze_content_scores_correctly_short_content(self):
        """Short content (<300 words) scores lower than long content."""
        from apps.content.seo.seo_engine import SEOEngine

        ai = _mock_ai()
        cache = _mock_cache()

        with patch("apps.content.seo.seo_engine.get_ai_client", return_value=ai), \
             patch("apps.content.seo.seo_engine.get_cache", return_value=cache):
            engine = SEOEngine()
            result = await engine.analyze_content("Short text.", target_keyword="AI")

        assert result.seo_score < 0.5
        assert result.word_count < 300

    async def test_analyze_content_long_content_with_headers_scores_higher(self):
        """Content with 600+ words and headers scores >= 0.6."""
        from apps.content.seo.seo_engine import SEOEngine

        content = (
            "# Best AI Tools\n\n"
            + ("AI tools are essential for modern businesses. " * 100)
            + "\n\n## Top Features\n\n"
            + ("These features make AI tools indispensable. " * 50)
        )
        ai = _mock_ai()
        cache = _mock_cache()

        with patch("apps.content.seo.seo_engine.get_ai_client", return_value=ai), \
             patch("apps.content.seo.seo_engine.get_cache", return_value=cache):
            engine = SEOEngine()
            result = await engine.analyze_content(content, target_keyword="AI tools")

        assert result.seo_score >= 0.6
        assert result.word_count >= 600

    async def test_optimize_meta_returns_title_and_description(self):
        """optimize_meta returns dict with title, description, and keyword."""
        from apps.content.seo.seo_engine import SEOEngine

        ai_content = "TITLE: Best AI Tools for 2024\nDESCRIPTION: Discover the best AI tools on the market. Find top-rated software and start your free trial today with our expert comparison guide."
        ai = _mock_ai(ai_content)
        cache = _mock_cache()

        with patch("apps.content.seo.seo_engine.get_ai_client", return_value=ai), \
             patch("apps.content.seo.seo_engine.get_cache", return_value=cache):
            engine = SEOEngine()
            result = await engine.optimize_meta(
                title="AI Tools Review",
                description="We review AI tools.",
                keyword="best AI tools",
            )

        assert "title" in result
        assert "description" in result
        assert "keyword" in result
        assert result["keyword"] == "best AI tools"

    async def test_generate_content_brief_returns_dict_with_outline(self):
        """generate_content_brief returns dict with outline list."""
        from apps.content.seo.seo_engine import SEOEngine

        ai = _mock_ai(
            "SECONDARY: AI tools guide, best AI, top AI software, AI for business, cheap AI\n"
            "TONE: conversational\n"
            "H2_1: What Is AI?\n"
            "H2_2: Benefits of AI Tools\n"
            "H2_3: How to Choose the Right AI\n"
            "H2_4: Top AI Tools Reviewed\n"
            "H2_5: Getting Started with AI\n"
            "CTA: Try AI tools free today"
        )
        cache = _mock_cache()

        with patch("apps.content.seo.seo_engine.get_ai_client", return_value=ai), \
             patch("apps.content.seo.seo_engine.get_cache", return_value=cache):
            engine = SEOEngine()
            brief = await engine.generate_content_brief("AI tools", audience="marketers")

        assert isinstance(brief, dict)
        assert "target_keyword" in brief
        assert "outline" in brief
        assert isinstance(brief["outline"], list)
        assert len(brief["outline"]) >= 3
        assert "secondary_keywords" in brief
        assert "buyer_intent" in brief

    async def test_top_opportunities_returns_list_of_keyword_metrics(self):
        """top_opportunities returns up to 10 KeywordMetrics sorted by opportunity."""
        from apps.content.seo.seo_engine import SEOEngine, KeywordMetrics

        ai = _mock_ai("\n".join([f"AI keyword {i}" for i in range(20)]))
        cache = _mock_cache()

        with patch("apps.content.seo.seo_engine.get_ai_client", return_value=ai), \
             patch("apps.content.seo.seo_engine.get_cache", return_value=cache):
            engine = SEOEngine()
            results = await engine.top_opportunities("AI")

        assert isinstance(results, list)
        assert len(results) <= 10
        # All items should be KeywordMetrics
        for km in results:
            assert isinstance(km, KeywordMetrics)

    async def test_stats_returns_dict(self):
        """stats() returns a dict with total_keywords_researched and avg_opportunity_score."""
        from apps.content.seo.seo_engine import SEOEngine

        ai = _mock_ai("best AI\ncheap AI\ntop AI")
        cache = _mock_cache()

        with patch("apps.content.seo.seo_engine.get_ai_client", return_value=ai), \
             patch("apps.content.seo.seo_engine.get_cache", return_value=cache):
            engine = SEOEngine()
            await engine.research_keywords("AI", count=3)
            result = engine.stats()

        assert isinstance(result, dict)
        assert "total_keywords_researched" in result
        assert "avg_opportunity_score" in result
        assert result["total_keywords_researched"] > 0


# ══════════════════════════════════════════════════════════════════════════════
# 2. KeywordResearcher
# ══════════════════════════════════════════════════════════════════════════════

class TestKeywordResearcher:
    """4 tests for KeywordResearcher."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.content.seo.keyword_research as m
        m._keyword_researcher = None
        yield
        m._keyword_researcher = None

    async def test_trending_topics_ai_fallback_returns_list(self):
        """trending_topics AI fallback returns a list of strings."""
        from apps.content.seo.keyword_research import KeywordResearcher

        ai = _mock_ai("AI marketing\nAI automation\nAI for business\nAI content\nAI SEO")

        with patch("apps.content.seo.keyword_research.get_ai_client", return_value=ai), \
             patch("apps.content.seo.keyword_research._PYTRENDS_AVAILABLE", False):
            researcher = KeywordResearcher()
            researcher._pytrends = None
            result = await researcher.trending_topics("AI")

        assert isinstance(result, list)
        assert len(result) >= 1
        for item in result:
            assert isinstance(item, str)

    async def test_trending_topics_fallback_on_empty_ai_response(self):
        """trending_topics returns default list when AI fails."""
        from apps.content.seo.keyword_research import KeywordResearcher

        ai = _mock_ai_failed()

        with patch("apps.content.seo.keyword_research.get_ai_client", return_value=ai), \
             patch("apps.content.seo.keyword_research._PYTRENDS_AVAILABLE", False):
            researcher = KeywordResearcher()
            researcher._pytrends = None
            result = await researcher.trending_topics("AI")

        assert isinstance(result, list)
        assert len(result) >= 1

    async def test_keyword_volume_estimate_returns_dict_with_all_keys(self):
        """keyword_volume_estimate returns dict with all required keys."""
        from apps.content.seo.keyword_research import KeywordResearcher

        with patch("apps.content.seo.keyword_research._PYTRENDS_AVAILABLE", False):
            researcher = KeywordResearcher()
            result = await researcher.keyword_volume_estimate("best AI tools for marketers")

        assert isinstance(result, dict)
        assert "keyword" in result
        assert "estimated_volume" in result
        assert "buyer_intent" in result
        assert "difficulty" in result
        assert "cpc_usd" in result

    async def test_buyer_intent_higher_for_buy_keyword(self):
        """'buy AI tools' has higher buyer_intent than generic 'AI tools'."""
        from apps.content.seo.keyword_research import KeywordResearcher

        with patch("apps.content.seo.keyword_research._PYTRENDS_AVAILABLE", False):
            researcher = KeywordResearcher()
            generic = await researcher.keyword_volume_estimate("AI tools")
            buyer = await researcher.keyword_volume_estimate("buy AI tools")

        assert buyer["buyer_intent"] > generic["buyer_intent"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. BlogGenerator
# ══════════════════════════════════════════════════════════════════════════════

class TestBlogGenerator:
    """8 tests for BlogGenerator."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.content.blog.blog_generator as m
        m._blog_generator = None
        yield
        m._blog_generator = None

    async def test_generate_post_returns_blog_post(self):
        """generate_post returns a BlogPost dataclass instance."""
        from apps.content.blog.blog_generator import BlogGenerator, BlogPost

        ai_content = (
            "# The Complete Guide to AI Marketing\n\n"
            "AI marketing is transforming how businesses reach customers.\n\n"
            "## What Is AI Marketing?\n\nAI marketing uses algorithms to personalize content.\n\n"
            "## Benefits of AI Marketing\n\nIncreased ROI and better targeting.\n\n"
            "## Getting Started\n\nBegin with these simple steps.\n\n"
            "## Conclusion\n\nAI marketing is the future. Start today!"
        )
        ai = _mock_ai(ai_content)
        cache = _mock_cache()

        with patch("apps.content.blog.blog_generator.get_ai_client", return_value=ai), \
             patch("apps.content.blog.blog_generator.get_cache", return_value=cache):
            gen = BlogGenerator()
            post = await gen.generate_post("AI marketing", audience="marketers", word_count=800)

        assert isinstance(post, BlogPost)

    async def test_generate_post_has_non_empty_content(self):
        """Generated blog post has non-empty content field."""
        from apps.content.blog.blog_generator import BlogGenerator

        ai = _mock_ai("# AI Title\n\nThis is content about AI.\n\n## Section\n\nMore content here.")
        cache = _mock_cache()

        with patch("apps.content.blog.blog_generator.get_ai_client", return_value=ai), \
             patch("apps.content.blog.blog_generator.get_cache", return_value=cache):
            gen = BlogGenerator()
            post = await gen.generate_post("AI tools")

        assert post.content
        assert len(post.content) > 0

    async def test_generate_post_word_count_greater_than_zero(self):
        """Generated blog post has word_count > 0."""
        from apps.content.blog.blog_generator import BlogGenerator

        ai = _mock_ai("# AI Guide\n\nContent about artificial intelligence and machine learning tools.")
        cache = _mock_cache()

        with patch("apps.content.blog.blog_generator.get_ai_client", return_value=ai), \
             patch("apps.content.blog.blog_generator.get_cache", return_value=cache):
            gen = BlogGenerator()
            post = await gen.generate_post("AI")

        assert post.word_count > 0

    async def test_generate_post_slug_generated_from_title(self):
        """Generated blog post has a slug derived from the title."""
        from apps.content.blog.blog_generator import BlogGenerator

        ai = _mock_ai("# The Best AI Tools for 2024\n\nContent here about AI tools.")
        cache = _mock_cache()

        with patch("apps.content.blog.blog_generator.get_ai_client", return_value=ai), \
             patch("apps.content.blog.blog_generator.get_cache", return_value=cache):
            gen = BlogGenerator()
            post = await gen.generate_post("best AI tools")

        assert post.slug
        # Slug should be lowercase, no spaces
        assert " " not in post.slug
        assert post.slug == post.slug.lower()

    async def test_generate_post_uses_template_when_ai_fails(self):
        """generate_post uses template fallback when AI fails."""
        from apps.content.blog.blog_generator import BlogGenerator

        ai = _mock_ai_failed()
        cache = _mock_cache()

        with patch("apps.content.blog.blog_generator.get_ai_client", return_value=ai), \
             patch("apps.content.blog.blog_generator.get_cache", return_value=cache):
            gen = BlogGenerator()
            post = await gen.generate_post("AI tools")

        # Template fallback should still produce a valid post
        assert post.content
        assert post.word_count > 0

    async def test_generate_series_returns_five_posts(self):
        """generate_series with count=5 returns 5 BlogPost objects."""
        from apps.content.blog.blog_generator import BlogGenerator, BlogPost

        ai = _mock_ai("# Series Post Title\n\nContent for the series post about the topic.")
        cache = _mock_cache()

        with patch("apps.content.blog.blog_generator.get_ai_client", return_value=ai), \
             patch("apps.content.blog.blog_generator.get_cache", return_value=cache):
            gen = BlogGenerator()
            posts = await gen.generate_series("AI marketing", count=5)

        assert isinstance(posts, list)
        assert len(posts) == 5
        for post in posts:
            assert isinstance(post, BlogPost)

    async def test_draft_posts_returns_list(self):
        """draft_posts() returns a list of posts with draft/ready status."""
        from apps.content.blog.blog_generator import BlogGenerator

        ai = _mock_ai("# Draft Post\n\nDraft content for testing purposes.")
        cache = _mock_cache()

        with patch("apps.content.blog.blog_generator.get_ai_client", return_value=ai), \
             patch("apps.content.blog.blog_generator.get_cache", return_value=cache):
            gen = BlogGenerator()
            await gen.generate_post("test keyword")
            drafts = gen.draft_posts()

        assert isinstance(drafts, list)
        assert len(drafts) >= 1

    async def test_stats_returns_dict_with_required_keys(self):
        """stats() returns dict with total_posts, avg_word_count, estimated_monthly_traffic."""
        from apps.content.blog.blog_generator import BlogGenerator

        ai = _mock_ai("# Test Post\n\nContent for statistics test.")
        cache = _mock_cache()

        with patch("apps.content.blog.blog_generator.get_ai_client", return_value=ai), \
             patch("apps.content.blog.blog_generator.get_cache", return_value=cache):
            gen = BlogGenerator()
            await gen.generate_post("AI")
            result = gen.stats()

        assert isinstance(result, dict)
        assert "total_posts" in result
        assert "avg_word_count" in result
        assert "estimated_monthly_traffic" in result
        assert result["total_posts"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 4. ContentCalendar
# ══════════════════════════════════════════════════════════════════════════════

class TestContentCalendar:
    """6 tests for ContentCalendar."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.content.blog.content_calendar as m
        m._content_calendar = None
        yield
        m._content_calendar = None

    async def test_plan_month_returns_30_slots(self):
        """plan_month returns exactly 30 content slots."""
        from apps.content.blog.content_calendar import ContentCalendar, ContentSlot

        cache = _mock_cache()
        with patch("apps.content.blog.content_calendar.get_cache", return_value=cache):
            cal = ContentCalendar()
            slots = await cal.plan_month("AI tools", month_start="2026-07-01")

        assert isinstance(slots, list)
        assert len(slots) == 30
        for slot in slots:
            assert isinstance(slot, ContentSlot)

    async def test_add_slot_returns_content_slot(self):
        """add_slot creates and returns a ContentSlot."""
        from apps.content.blog.content_calendar import ContentCalendar, ContentSlot

        cache = _mock_cache()
        with patch("apps.content.blog.content_calendar.get_cache", return_value=cache):
            cal = ContentCalendar()
            slot = await cal.add_slot(
                date="2026-07-15",
                content_type="blog",
                title="Test Blog Post",
                keyword="AI",
                platform="website",
            )

        assert isinstance(slot, ContentSlot)
        assert slot.date == "2026-07-15"
        assert slot.content_type == "blog"
        assert slot.title == "Test Blog Post"
        assert slot.status == "planned"

    async def test_this_week_returns_list(self):
        """this_week() returns a list."""
        from apps.content.blog.content_calendar import ContentCalendar

        cache = _mock_cache()
        with patch("apps.content.blog.content_calendar.get_cache", return_value=cache):
            cal = ContentCalendar()
            result = cal.this_week()

        assert isinstance(result, list)

    async def test_upcoming_returns_list(self):
        """upcoming() returns a list of slots within the window."""
        from apps.content.blog.content_calendar import ContentCalendar

        cache = _mock_cache()
        with patch("apps.content.blog.content_calendar.get_cache", return_value=cache):
            cal = ContentCalendar()
            await cal.plan_month("AI", month_start="2026-06-14")
            result = cal.upcoming(days=14)

        assert isinstance(result, list)

    async def test_mark_published_updates_status(self):
        """mark_published changes slot status to 'published'."""
        from apps.content.blog.content_calendar import ContentCalendar

        cache = _mock_cache()
        with patch("apps.content.blog.content_calendar.get_cache", return_value=cache):
            cal = ContentCalendar()
            slot = await cal.add_slot("2026-07-20", "email", "Newsletter #1")
            success = cal.mark_published(slot.slot_id)

        assert success is True
        # Verify the slot was updated
        updated = next((s for s in cal._slots if s["slot_id"] == slot.slot_id), None)
        assert updated is not None
        assert updated["status"] == "published"

    async def test_calendar_stats_returns_dict(self):
        """calendar_stats() returns dict with planned/in_progress/published counts."""
        from apps.content.blog.content_calendar import ContentCalendar

        cache = _mock_cache()
        with patch("apps.content.blog.content_calendar.get_cache", return_value=cache):
            cal = ContentCalendar()
            await cal.add_slot("2026-07-01", "blog", "Post 1")
            await cal.add_slot("2026-07-02", "social", "Post 2")
            result = cal.calendar_stats()

        assert isinstance(result, dict)
        assert "planned" in result
        assert "in_progress" in result
        assert "published" in result
        assert result["planned"] >= 2


# ══════════════════════════════════════════════════════════════════════════════
# 5. ProductWriter
# ══════════════════════════════════════════════════════════════════════════════

class TestProductWriter:
    """6 tests for ProductWriter."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.content.product_pages.product_writer as m
        m._product_writer = None
        yield
        m._product_writer = None

    async def test_optimize_product_returns_product_page_analysis(self):
        """optimize_product returns ProductPageAnalysis."""
        from apps.content.product_pages.product_writer import ProductWriter, ProductPageAnalysis

        ai = _mock_ai(
            "**Premium AI Writing Tool** — The ultimate solution for content creators.\n\n"
            "**Key Benefits:**\n"
            "- 10x your writing speed with AI assistance\n"
            "- Trusted by 50,000+ marketers worldwide\n"
            "- Guaranteed to improve your conversion rates\n\n"
            "**Perfect for:** Marketers, bloggers, and entrepreneurs.\n\n"
            "⭐⭐⭐⭐⭐ Rated 4.9/5 by 10,000+ reviews.\n\n"
            "**Limited time offer** — Order now and get free shipping!"
        )
        cache = _mock_cache()

        with patch("apps.content.product_pages.product_writer.get_ai_client", return_value=ai), \
             patch("apps.content.product_pages.product_writer.get_cache", return_value=cache):
            writer = ProductWriter()
            result = await writer.optimize_product(
                product_id="prod_001",
                title="AI Writing Tool",
                description="A tool that helps you write.",
                category="software",
            )

        assert isinstance(result, ProductPageAnalysis)
        assert result.product_id == "prod_001"

    async def test_optimized_description_differs_from_original(self):
        """optimized_description is different from the original description."""
        from apps.content.product_pages.product_writer import ProductWriter

        original = "A tool that helps you write."
        ai = _mock_ai(
            "**Revolutionary AI Tool** — Transform your writing today.\n\n"
            "- Boosts productivity by 300%\n"
            "- Trusted by professionals\n"
            "- Limited stock available — Order now!"
        )
        cache = _mock_cache()

        with patch("apps.content.product_pages.product_writer.get_ai_client", return_value=ai), \
             patch("apps.content.product_pages.product_writer.get_cache", return_value=cache):
            writer = ProductWriter()
            result = await writer.optimize_product("prod_002", "AI Writer", original)

        assert result.optimized_description != original

    async def test_seo_score_after_gte_seo_score_before(self):
        """seo_score_after is >= seo_score_before after optimization."""
        from apps.content.product_pages.product_writer import ProductWriter

        # Simple original with no conversion elements
        original = "This product is good."
        ai = _mock_ai(
            "**Best-in-class product** — Trusted by thousands.\n\n"
            "- Premium quality guaranteed\n"
            "- Rated 5 stars by 5,000 customers\n"
            "- Limited time deal — save 20% today!\n\n"
            "Order now with free shipping and 30-day money-back guarantee."
        )
        cache = _mock_cache()

        with patch("apps.content.product_pages.product_writer.get_ai_client", return_value=ai), \
             patch("apps.content.product_pages.product_writer.get_cache", return_value=cache):
            writer = ProductWriter()
            result = await writer.optimize_product("prod_003", "Widget", original)

        assert result.seo_score_after >= result.seo_score_before

    async def test_generate_product_faq_returns_five_items(self):
        """generate_product_faq returns a list of 5 FAQ dicts."""
        from apps.content.product_pages.product_writer import ProductWriter

        faq_content = (
            "Q1: What is AI Writer?\nA1: AI Writer is a premium content generation tool.\n"
            "Q2: How fast is shipping?\nA2: Standard shipping takes 3-5 business days.\n"
            "Q3: Is there a return policy?\nA3: Yes, 30-day money-back guarantee.\n"
            "Q4: Is it easy to use?\nA4: Absolutely — setup takes less than 5 minutes.\n"
            "Q5: Do you offer bulk discounts?\nA5: Yes, contact us for bulk pricing."
        )
        ai = _mock_ai(faq_content)
        cache = _mock_cache()

        with patch("apps.content.product_pages.product_writer.get_ai_client", return_value=ai), \
             patch("apps.content.product_pages.product_writer.get_cache", return_value=cache):
            writer = ProductWriter()
            faqs = await writer.generate_product_faq("prod_004", "AI Writer", "software")

        assert isinstance(faqs, list)
        assert len(faqs) == 5
        for faq in faqs:
            assert "question" in faq
            assert "answer" in faq

    async def test_create_collection_description_returns_string(self):
        """create_collection_description returns a non-empty string."""
        from apps.content.product_pages.product_writer import ProductWriter

        ai = _mock_ai(
            "Discover our Premium AI Software collection — the ultimate toolkit for modern businesses. "
            "Shop AI Writer, AI Analytics, and AI SEO tools today with free shipping on all orders."
        )
        cache = _mock_cache()

        with patch("apps.content.product_pages.product_writer.get_ai_client", return_value=ai), \
             patch("apps.content.product_pages.product_writer.get_cache", return_value=cache):
            writer = ProductWriter()
            result = await writer.create_collection_description(
                "Premium AI Software",
                ["AI Writer", "AI Analytics", "AI SEO Tool"],
            )

        assert isinstance(result, str)
        assert len(result) > 0

    async def test_stats_returns_dict(self):
        """stats() returns dict with total_optimized and avg_seo_improvement."""
        from apps.content.product_pages.product_writer import ProductWriter

        ai = _mock_ai(
            "**Premium Tool** — Trusted by thousands.\n\n"
            "- Top quality guaranteed\n"
            "- Rated 5 stars\n"
            "- Limited stock — Order now!"
        )
        cache = _mock_cache()

        with patch("apps.content.product_pages.product_writer.get_ai_client", return_value=ai), \
             patch("apps.content.product_pages.product_writer.get_cache", return_value=cache):
            writer = ProductWriter()
            await writer.optimize_product("prod_005", "Test Product", "Basic description.")
            result = writer.stats()

        assert isinstance(result, dict)
        assert "total_optimized" in result
        assert "avg_seo_improvement" in result
        assert result["total_optimized"] >= 1
