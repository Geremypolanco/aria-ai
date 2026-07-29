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

import inspect
import re

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


def test_every_traffic_strategy_is_still_in_the_roster():
    """Nothing was accidentally removed while reweighting."""
    names = {name for name, _weight in STRATEGIES}
    missing = TRAFFIC_STRATEGIES - names
    assert not missing, f"traffic strategies missing from STRATEGIES: {missing}"


def test_traffic_strategies_now_carry_the_majority_of_selection_weight():
    total_weight = sum(weight for _name, weight in STRATEGIES)
    traffic_weight = sum(weight for name, weight in STRATEGIES if name in TRAFFIC_STRATEGIES)

    assert traffic_weight / total_weight > 0.5, (
        f"traffic strategies only account for {traffic_weight}/{total_weight} "
        "of total selection weight — the rebalance regressed"
    )


def test_no_traffic_strategy_regressed_to_the_weight_one_floor():
    """Every one of these was deliberately boosted above the generic
    weight-1 default any new/unreviewed strategy gets — catches a future
    edit accidentally reverting one back to baseline."""
    weights = dict(STRATEGIES)
    for name in TRAFFIC_STRATEGIES:
        assert weights[name] > 1, f"{name} is back at the weight-1 floor"


def test_niche_product_strategies_are_untouched_and_still_present():
    """The rebalance must not have deleted or zeroed out the
    revenue-diversification strategies — they still run, just don't
    dominate selection anymore."""
    weights = dict(STRATEGIES)
    for name in ("niche_rotator", "product_factory", "ebook_factory", "shopify_listing"):
        assert name in weights
        assert weights[name] >= 1


def test_content_pipeline_fallback_articles_use_the_real_interval_dynamically():
    """Regression: the fallback article text used to hardcode "30 Minutes"
    while INTERVAL_SECONDS was already 1200s (20 min) — a published article
    describing ARIA's own product inaccurately. Must now reference the
    constant, not a literal number, so it can never drift again."""
    source = inspect.getsource(IncomeLoop._exec_content_pipeline)
    assert "INTERVAL_SECONDS // 60" in source
    assert "30 Minutes" not in source
    assert f"Every {INTERVAL_SECONDS // 60} Minutes" not in source  # only via f-string, not literal


def test_content_pipeline_fallback_articles_no_longer_contain_fabricated_stats():
    """The old fallback copy invented specific, unverifiable percentages
    ("70% of customer inquiries", "85% accuracy", "$5K-$50K/month") framed
    as real industry findings. None of that belongs in content ARIA
    publishes under its own name."""
    source = inspect.getsource(IncomeLoop._exec_content_pipeline)
    fabricated_markers = [
        "70% of customer inquiries",
        "1,000+ AI-powered businesses",
        "average 3x improvement",
    ]
    for marker in fabricated_markers:
        assert marker not in source, f"stale fabricated stat still present: {marker!r}"


def test_content_pipeline_fallback_articles_describe_real_current_features():
    """The replacement copy must actually reference verifiable, current ARIA
    capabilities — not just swap one set of generic filler for another."""
    source = inspect.getsource(IncomeLoop._exec_content_pipeline)
    for marker in ("four independent safety layers", "sandbox", "clarifying question"):
        assert marker in source, f"expected real-feature copy missing: {marker!r}"


def test_module_docstring_does_not_hardcode_a_stale_cycle_interval():
    module_source = inspect.getsource(__import__("apps.core.tools.income_loop", fromlist=["x"]))
    docstring_end = module_source.index('"""', module_source.index('"""') + 3)
    docstring = module_source[: docstring_end + 3]
    assert not re.search(
        r"\b30[- ]min", docstring
    ), "docstring still hardcodes the old 30-min interval"
    assert not re.search(
        r"\b48 cycles", docstring
    ), "docstring still hardcodes the old 48-cycles/day figure"
