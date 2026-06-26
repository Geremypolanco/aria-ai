"""Phase 13 tests — Conversion Extensions (LandingPageEngine, EmailNurtureEngine)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Stop Struggling — Get AI Results in 7 Days or Your Money Back\nThe fastest system for entrepreneurs who want to scale without hiring\nMost people try to do everything manually. Not anymore."):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── Landing Page Engine ───────────────────────────────────────────────────────

class TestLandingPageEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.conversion.landing_pages.landing_page_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.conversion.landing_pages.landing_page_engine.get_ai_client",
                       return_value=_mock_ai()):
                from apps.conversion.landing_pages.landing_page_engine import LandingPageEngine
                return LandingPageEngine()

    @pytest.mark.asyncio
    async def test_create_page_returns_landing_page(self, engine):
        from apps.conversion.landing_pages.landing_page_engine import LandingPage
        page = await engine.create_page("AI Tool", "10x your output", "entrepreneurs", 97.0)
        assert isinstance(page, LandingPage)
        assert page.page_id

    @pytest.mark.asyncio
    async def test_create_page_has_headline(self, engine):
        page = await engine.create_page("Course", "Learn fast", "beginners", 197.0)
        assert len(page.headline) > 0

    @pytest.mark.asyncio
    async def test_create_page_has_subheadline(self, engine):
        page = await engine.create_page("Membership", "Join today", "creators")
        assert len(page.subheadline) > 0

    @pytest.mark.asyncio
    async def test_create_page_has_bullet_points(self, engine):
        page = await engine.create_page("Software", "Free trial", "developers")
        assert isinstance(page.bullet_points, list)
        assert len(page.bullet_points) >= 3

    @pytest.mark.asyncio
    async def test_create_page_has_cta_primary(self, engine):
        page = await engine.create_page("Product", "Best deal", "buyers")
        assert len(page.cta_primary) > 0

    @pytest.mark.asyncio
    async def test_create_page_has_social_proof(self, engine):
        page = await engine.create_page("Service", "Results guaranteed", "business owners")
        assert len(page.social_proof) > 0

    @pytest.mark.asyncio
    async def test_create_page_has_urgency(self, engine):
        page = await engine.create_page("Bundle", "Save 50%", "shoppers")
        assert len(page.urgency_trigger) > 0

    @pytest.mark.asyncio
    async def test_create_page_has_faq(self, engine):
        page = await engine.create_page("Tool", "Automate everything", "freelancers")
        assert isinstance(page.faq, list)
        assert len(page.faq) >= 1

    @pytest.mark.asyncio
    async def test_create_page_estimated_cvr_positive(self, engine):
        page = await engine.create_page("SaaS", "14-day trial", "startups", 49.0)
        assert page.estimated_cvr_pct > 0.0

    @pytest.mark.asyncio
    async def test_create_page_default_variant_is_a(self, engine):
        page = await engine.create_page("Product", "Offer", "audience")
        assert page.ab_variant == "A"

    @pytest.mark.asyncio
    async def test_create_page_stored_in_memory(self, engine):
        await engine.create_page("X", "Y", "Z")
        assert len(engine._pages) == 1

    @pytest.mark.asyncio
    async def test_generate_headline_variants_returns_list(self, engine):
        variants = await engine.generate_headline_variants("AI Tool", "entrepreneurs", count=3)
        assert isinstance(variants, list)
        assert len(variants) >= 1

    @pytest.mark.asyncio
    async def test_create_ab_variant_returns_page(self, engine):
        from apps.conversion.landing_pages.landing_page_engine import LandingPage
        original = await engine.create_page("Product", "Offer", "Audience")
        variant = await engine.create_ab_variant(original)
        assert isinstance(variant, LandingPage)
        assert variant.ab_variant == "B"

    @pytest.mark.asyncio
    async def test_ab_variant_different_cta(self, engine):
        original = await engine.create_page("Course", "Learn AI", "beginners")
        variant = await engine.create_ab_variant(original)
        assert variant.cta_primary != original.cta_primary or variant.headline != original.headline

    def test_page_stats_has_required_keys(self, engine):
        stats = engine.page_stats()
        assert "total_pages" in stats
        assert "by_variant" in stats
        assert "avg_estimated_cvr_pct" in stats

    @pytest.mark.asyncio
    async def test_pages_accumulate(self, engine):
        await engine.create_page("A", "Offer A", "audience")
        await engine.create_page("B", "Offer B", "audience")
        assert len(engine._pages) == 2

    def test_recent_pages_returns_list(self, engine):
        result = engine.recent_pages(limit=5)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_low_price_has_higher_cvr(self, engine):
        cheap = await engine.create_page("Ebook", "Learn now", "readers", 9.0)
        expensive = await engine.create_page("Coaching", "Transform", "exec", 5000.0)
        assert cheap.estimated_cvr_pct >= expensive.estimated_cvr_pct


# ── Email Nurture Engine ──────────────────────────────────────────────────────

class TestEmailNurtureEngine:
    @pytest.fixture
    def engine(self):
        ai_content = (
            "Welcome to your AI journey!\n"
            "Quick tip inside — 2 minute read\n"
            "Here's the first thing you need to know about AI for business...\n"
            "CTA: Read the full guide →\n"
            "---\n"
            "The #1 mistake most people make\n"
            "Don't make this costly error\n"
            "Most people approach AI the wrong way...\n"
            "CTA: Learn the right approach →\n"
            "---\n"
            "How Jane got 3x revenue in 90 days\n"
            "Real results from a real customer\n"
            "Jane was exactly where you are...\n"
            "CTA: See full case study →"
        )
        with patch("apps.conversion.email_sequences.email_nurture.get_cache", return_value=_mock_cache()):
            with patch("apps.conversion.email_sequences.email_nurture.get_ai_client",
                       return_value=_mock_ai(ai_content)):
                from apps.conversion.email_sequences.email_nurture import EmailNurtureEngine
                return EmailNurtureEngine()

    @pytest.mark.asyncio
    async def test_create_sequence_returns_sequence(self, engine):
        from apps.conversion.email_sequences.email_nurture import NurtureSequence
        seq = await engine.create_sequence("fitness", "convert_to_customer", "gym owners", num_emails=3)
        assert isinstance(seq, NurtureSequence)
        assert seq.sequence_id

    @pytest.mark.asyncio
    async def test_sequence_has_emails(self, engine):
        seq = await engine.create_sequence("ecommerce", "convert_to_customer", "store owners", num_emails=5)
        assert isinstance(seq.emails, list)
        assert len(seq.emails) >= 1

    @pytest.mark.asyncio
    async def test_sequence_has_name(self, engine):
        seq = await engine.create_sequence("saas", "onboard", "new users", num_emails=3)
        assert len(seq.name) > 0

    @pytest.mark.asyncio
    async def test_sequence_has_total_emails(self, engine):
        seq = await engine.create_sequence("fitness", "upsell", "customers", num_emails=4)
        assert seq.total_emails >= 1

    @pytest.mark.asyncio
    async def test_sequence_has_duration_days(self, engine):
        seq = await engine.create_sequence("health", "convert_to_customer", "leads", num_emails=5)
        assert seq.sequence_duration_days >= 0

    @pytest.mark.asyncio
    async def test_sequence_emails_have_subject(self, engine):
        seq = await engine.create_sequence("tech", "onboard", "users", num_emails=3)
        for email in seq.emails:
            assert len(email.get("subject", "")) > 0

    @pytest.mark.asyncio
    async def test_sequence_emails_have_goal(self, engine):
        seq = await engine.create_sequence("coaching", "convert_to_customer", "leads", num_emails=3)
        for email in seq.emails:
            assert len(email.get("goal", "")) > 0

    @pytest.mark.asyncio
    async def test_sequence_emails_have_day_offset(self, engine):
        seq = await engine.create_sequence("fitness", "convert_to_customer", "leads", num_emails=3)
        for email in seq.emails:
            assert isinstance(email.get("day_offset"), int)

    @pytest.mark.asyncio
    async def test_sequence_has_expected_cvr(self, engine):
        seq = await engine.create_sequence("nutrition", "convert_to_customer", "prospects", num_emails=5)
        assert seq.expected_conversion_rate_pct >= 0.0

    @pytest.mark.asyncio
    async def test_sequence_stored_in_memory(self, engine):
        await engine.create_sequence("fitness", "upsell", "customers", num_emails=3)
        assert len(engine._sequences) == 1

    @pytest.mark.asyncio
    async def test_personalize_email_returns_email(self, engine):
        from apps.conversion.email_sequences.email_nurture import NurtureEmail
        email = NurtureEmail(
            subject="Welcome to {{first_name}}'s journey",
            body="Hi {{first_name}}, we're excited to have you.",
            goal="build_trust",
        )
        personalized = await engine.personalize_email(email, "Alice", {"niche": "fitness"})
        assert isinstance(personalized, NurtureEmail)

    @pytest.mark.asyncio
    async def test_personalize_email_replaces_name(self, engine):
        from apps.conversion.email_sequences.email_nurture import NurtureEmail
        email = NurtureEmail(
            subject="Hello there",
            body="Hi {{name}}, welcome aboard.",
            goal="build_trust",
        )
        personalized = await engine.personalize_email(email, "Bob", {})
        assert "Bob" in personalized.body

    @pytest.mark.asyncio
    async def test_create_reactivation_sequence_returns_sequence(self, engine):
        from apps.conversion.email_sequences.email_nurture import NurtureSequence
        seq = await engine.create_reactivation_sequence("fitness", inactive_days=45)
        assert isinstance(seq, NurtureSequence)

    @pytest.mark.asyncio
    async def test_reactivation_goal_is_reactivate(self, engine):
        seq = await engine.create_reactivation_sequence("ecommerce")
        assert seq.goal == "reactivate"

    def test_sequence_analytics_has_required_keys(self, engine):
        analytics = engine.sequence_analytics()
        assert "total_sequences" in analytics
        assert "avg_emails_per_sequence" in analytics
        assert "avg_expected_cvr_pct" in analytics
        assert "by_goal" in analytics

    @pytest.mark.asyncio
    async def test_multiple_sequences_accumulate(self, engine):
        await engine.create_sequence("a", "onboard", "users", num_emails=3)
        await engine.create_sequence("b", "convert_to_customer", "leads", num_emails=3)
        assert len(engine._sequences) == 2

    def test_recent_sequences_returns_list(self, engine):
        result = engine.recent_sequences(limit=5)
        assert isinstance(result, list)
