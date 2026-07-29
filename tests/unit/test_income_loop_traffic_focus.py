"""Regression/feature test: STRATEGIES had ~100 entries covering nearly every
growth/marketing channel imaginable (SEO, social, backlinks, PR, podcasts...),
but the overwhelming majority sat at the same weight-1 floor as pure
niche-product-creation strategies — so despite already having "todos los
recursos disponibles" (every resource available) to drive traffic to ARIA's
own site, the loop had no consistent focus on actually doing so. Roughly two
dozen strategies whose primary effect is real traffic to aria-ai.fly.dev
(not creating/selling a one-off niche product) are now weighted so they make
up the majority of the loop's cycles, without removing or breaking any of
the other ~80 strategies, which keep running too — same "todos los recursos"
principle in the other direction (this doesn't stop being a diversified
income loop, it's just no longer traffic-blind).

Separately, _exec_content_pipeline()'s hardcoded fallback articles (used
when the AI content pipeline itself produces nothing) described generic,
unverifiable 2026 "AI business trend" statistics with no connection to
ARIA's actual current feature set — "que se adapte a lo que hace aria
actualmente" (CLAUDE.md convention). They now describe ARIA's real, current,
checkable capabilities (autonomous execution, the 4-layer safety pipeline,
HITL checkpoints, the sandboxed code runner, voice mode, this very income
loop) and reference the loop's real interval via INTERVAL_SECONDS instead of
a hardcoded number that had already drifted (the file used to say "30
minutes" while INTERVAL_SECONDS was actually 1200s/20min).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.income_loop import INTERVAL_SECONDS, STRATEGIES, IncomeLoop

# Strategies whose primary effect is real traffic to ARIA's own site (SEO,
# backlinks, cross-channel distribution, brand/credibility building) rather
# than creating or selling a one-off niche product. Matches the module
# docstring's own list — kept in sync deliberately, not derived, since which
# strategies count as "traffic-focused" is a judgment call, not something
# inferable purely from the strategy name.
TRAFFIC_STRATEGIES = {
    "content_pipeline",
    "github_publish",
    "content_repurposer",
    "content_amplifier",
    "seo_optimizer",
    "seo_tracking",
    "seo_backlink_builder",
    "seo_content_cluster",
    "social_blitz",
    "landing_page_deploy",
    "media_pitch",
    "product_hunt_launch",
    "self_monetize",
    "viral_detector",
    "growth_hacker",
    "growth_experiment",
    "conversion_optimizer",
    "brand_storyteller",
    "thought_leadership",
    "case_study_publisher",
    "podcast_pitch",
    "influencer_outreach",
    "multilingual_content",
}

# Explicit expected acceptable range for the rebalance — tight enough that an
# accidental swing (e.g. one edit multiplying every traffic weight by 10x,
# or a later PR quietly deleting a chunk of the niche side so the fraction
# balloons without any weight actually changing) fails a test instead of
# silently drifting.
_MIN_TRAFFIC_FRACTION = 0.45
_MAX_TRAFFIC_FRACTION = 0.65


def test_every_traffic_strategy_is_still_in_the_roster():
    """Nothing was accidentally removed while reweighting."""
    names = {name for name, _weight in STRATEGIES}
    missing = TRAFFIC_STRATEGIES - names
    assert not missing, f"traffic strategies missing from STRATEGIES: {missing}"


def test_traffic_strategies_carry_the_intended_share_of_selection_weight():
    total_weight = sum(weight for _name, weight in STRATEGIES)
    traffic_weight = sum(weight for name, weight in STRATEGIES if name in TRAFFIC_STRATEGIES)
    fraction = traffic_weight / total_weight

    assert _MIN_TRAFFIC_FRACTION < fraction < _MAX_TRAFFIC_FRACTION, (
        f"traffic strategies account for {traffic_weight}/{total_weight} "
        f"({fraction:.0%}) of total selection weight — expected roughly "
        f"{_MIN_TRAFFIC_FRACTION:.0%}-{_MAX_TRAFFIC_FRACTION:.0%}; either the "
        "rebalance regressed or something else moved unexpectedly"
    )


def test_no_traffic_strategy_regressed_to_the_weight_one_floor():
    """Every one of these was deliberately boosted above the generic
    weight-1 default any new/unreviewed strategy gets — catches a future
    edit accidentally reverting one back to baseline."""
    weights = dict(STRATEGIES)
    for name in TRAFFIC_STRATEGIES:
        assert weights[name] > 1, f"{name} is back at the weight-1 floor"


# A hardcoded, independent snapshot of the niche/product-diversification
# side of the roster as it existed right before this rebalance — NOT
# derived from STRATEGIES, specifically so this test can't become a
# tautology that compares the roster to itself. Only 4 of these were
# checked before (CodeRabbit, PR #154); a regression deleting or zeroing
# any of the other ~70+ would previously have passed silently.
NICHE_STRATEGY_NAMES = {
    "niche_rotator", "product_factory", "course_builder", "affiliate_network",
    "opportunity_scan", "micro_saas", "shopify_listing", "email_campaign",
    "affiliate_content", "ebook_factory", "lead_magnet", "hf_spaces_demo",
    "gist_blitz", "product_bundle", "waitlist_builder", "challenge_campaign",
    "partner_outreach", "newsletter_issue", "job_board_listing",
    "github_sponsors_setup", "premium_offer", "viral_thread", "twitter_thread",
    "linkedin_post", "reddit_organic", "stripe_checkout", "tiktok_script",
    "linkedin_outreach", "youtube_strategy", "cold_email_outreach",
    "pinterest_pins", "substack_publish", "freelance_gig", "ab_content_test",
    "smart_pricing", "voice_of_aria", "referral_engine", "digital_agency",
    "crowdfunding_kit", "newsletter_monetize", "community_launch",
    "testimonial_collector", "lead_closer", "retargeting_campaign",
    "marketplace_lister", "daily_goal_tracker", "knowledge_synthesizer",
    "competitor_copy", "price_ladder", "auto_responder", "affiliate_injector",
    "social_dm_outreach", "upsell_engine", "podcast_producer",
    "saas_waitlist_blitz", "vc_pitch_deck", "job_posting_scout",
    "micro_grant_hunter", "notion_template_seller", "chrome_extension_builder",
    "api_marketplace_lister", "white_label_kit", "data_product_seller",
    "b2b_saas_pitch", "email_list_builder", "joint_venture_pitch",
    "product_review_outreach", "price_anchoring", "social_proof_automation",
    "influencer_collab", "content_licensing", "micro_consulting",
    "saas_upsell_sequence", "community_monetize", "token_economy",
    "api_product_launch", "app_store_listing", "catalog_repromoter",
    "stripe_subscription",
}  # fmt: skip


def test_every_niche_strategy_in_the_hardcoded_snapshot_is_still_present():
    """Catches a future edit that deletes or zeroes a niche strategy while
    only intending to touch the traffic side — checked against the
    independent snapshot above, not against STRATEGIES itself."""
    weights = dict(STRATEGIES)
    missing = NICHE_STRATEGY_NAMES - set(weights)
    assert not missing, f"niche strategies missing from STRATEGIES: {missing}"
    for name in NICHE_STRATEGY_NAMES:
        assert weights[name] >= 1, f"{name} was zeroed out"


def test_roster_names_are_exactly_traffic_plus_niche_snapshot():
    """The two hardcoded sets above must partition the full roster with no
    gaps — if this fails, a strategy exists that this test file doesn't
    know how to classify (likely a new one added without updating either
    set), which would otherwise silently escape both coverage checks."""
    all_names = {name for name, _weight in STRATEGIES}
    assert all_names == TRAFFIC_STRATEGIES | NICHE_STRATEGY_NAMES


@pytest.mark.asyncio
async def test_content_pipeline_fallback_articles_behaviorally_use_the_real_interval():
    """Behavior-level, not source-inspection: force the "AI generated no
    articles" path and capture the actual fallback payload passed onward,
    so a bug in the f-string itself (not just its presence in the source)
    would fail this test."""
    loop = IncomeLoop.__new__(IncomeLoop)
    captured = {}

    async def fake_github_blog(articles, cp=None):
        captured["articles"] = articles
        return {"success": True, "summary": "published", "revenue_potential": 1.0, "urls": []}

    fake_cp = AsyncMock()
    fake_cp.run_pipeline = AsyncMock(return_value={"success": False, "articles": []})

    with (
        patch("apps.core.tools.content_pipeline.ContentPipeline", return_value=fake_cp),
        patch("apps.core.tools.income_loop.settings") as mock_settings,
        patch.object(loop, "_exec_github_blog", fake_github_blog),
    ):
        mock_settings.GITHUB_TOKEN = "fake-token"
        await loop._exec_content_pipeline()

    assert "articles" in captured, "fallback path never ran — test setup didn't reach it"
    bodies = " ".join(a["body"] for a in captured["articles"])
    titles = " ".join(a["title"] for a in captured["articles"])

    expected_minutes = INTERVAL_SECONDS // 60
    assert f"Every {expected_minutes} Minutes" in titles
    assert "Every 30 Minutes" not in titles
    assert "Every 30 Minutes" not in bodies


@pytest.mark.asyncio
async def test_content_pipeline_fallback_articles_behaviorally_exclude_fabricated_stats():
    loop = IncomeLoop.__new__(IncomeLoop)
    captured = {}

    async def fake_github_blog(articles, cp=None):
        captured["articles"] = articles
        return {"success": True, "summary": "published", "revenue_potential": 1.0, "urls": []}

    fake_cp = AsyncMock()
    fake_cp.run_pipeline = AsyncMock(return_value={"success": False, "articles": []})

    with (
        patch("apps.core.tools.content_pipeline.ContentPipeline", return_value=fake_cp),
        patch("apps.core.tools.income_loop.settings") as mock_settings,
        patch.object(loop, "_exec_github_blog", fake_github_blog),
    ):
        mock_settings.GITHUB_TOKEN = "fake-token"
        await loop._exec_content_pipeline()

    bodies = " ".join(a["body"] for a in captured["articles"])
    for fabricated in (
        "70% of customer inquiries",
        "1,000+ AI-powered businesses",
        "average 3x improvement",
    ):
        assert fabricated not in bodies, f"stale fabricated stat still present: {fabricated!r}"


@pytest.mark.asyncio
async def test_content_pipeline_fallback_articles_behaviorally_describe_real_features():
    loop = IncomeLoop.__new__(IncomeLoop)
    captured = {}

    async def fake_github_blog(articles, cp=None):
        captured["articles"] = articles
        return {"success": True, "summary": "published", "revenue_potential": 1.0, "urls": []}

    fake_cp = AsyncMock()
    fake_cp.run_pipeline = AsyncMock(return_value={"success": False, "articles": []})

    with (
        patch("apps.core.tools.content_pipeline.ContentPipeline", return_value=fake_cp),
        patch("apps.core.tools.income_loop.settings") as mock_settings,
        patch.object(loop, "_exec_github_blog", fake_github_blog),
    ):
        mock_settings.GITHUB_TOKEN = "fake-token"
        await loop._exec_content_pipeline()

    bodies = " ".join(a["body"] for a in captured["articles"])
    for marker in ("four independent safety layers", "sandbox", "clarifying question"):
        assert marker in bodies, f"expected real-feature copy missing: {marker!r}"


def test_module_docstring_does_not_hardcode_a_stale_cycle_interval():
    import apps.core.tools.income_loop as income_loop_module

    docstring = income_loop_module.__doc__ or ""
    assert docstring, "module docstring is missing entirely"
    assert (
        "30-min" not in docstring and "30 min" not in docstring
    ), "docstring still hardcodes the old 30-min interval"
    assert "48 cycles" not in docstring, "docstring still hardcodes the old 48-cycles/day figure"
