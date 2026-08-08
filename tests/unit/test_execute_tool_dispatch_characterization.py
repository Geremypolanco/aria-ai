"""Characterization test for AriaMind._execute_tool()'s dispatch surface.

Purpose: apps/core/cognition/aria_mind.py's _execute_tool() (~3,264 lines) is
being converted, in small batches, from an if/elif chain over `tool` into a
handler registry (see ARIA_ADM/AAS: "Tool Router" extraction, Stage 1 — a
mechanical, behavior-preserving conversion; no branch logic changes).

This test is the safety net for that conversion: it snapshots the exact set
of tool names the dispatcher recognizes *before* any branch has moved, so an
accidental drop during the mechanical transcription (a missed `elif`, a
typo'd string) fails CI instead of silently vanishing. The oracle list below
must only change via an explicit, reviewed tool-inventory change — never as
a side effect of a refactor commit.

Extraction note: while _execute_tool is still one if/elif chain, "recognized"
is determined by statically parsing its source for `tool == "..."` and
`tool in (...)` literals (calling all ~173 branches for real would mean
firing real network requests / real side effects for tools like send_email,
post_to_social, execute_code — not safe or fast for a unit test). Once the
registry lands, update `_recognized_tool_names()` below to read
`_TOOL_HANDLERS.keys()` directly instead of parsing source — the oracle
frozenset stays the same either way, which is the point.
"""

from __future__ import annotations

import re
from pathlib import Path

_ARIA_MIND_PATH = (
    Path(__file__).resolve().parents[2] / "apps" / "core" / "cognition" / "aria_mind.py"
)

# Snapshotted 2026-08-07 by statically parsing `_execute_tool`'s if/elif
# chain (apps/core/cognition/aria_mind.py:1518-4782). 173 distinct tool
# names. Do not hand-edit without re-deriving from source and reviewing the
# diff — this set is the ground truth the extraction must preserve exactly.
EXPECTED_TOOL_NAMES = frozenset(
    {
        "add_goal",
        "add_linkedin_prospect",
        "add_priority_action",
        "add_research_finding",
        "ai_performance_report",
        "allocate_resources",
        "analyze_content_originality",
        "analyze_decision",
        "analyze_image",
        "analyze_pricing",
        "analyze_user_behavior",
        "analyze_video",
        "analyze_virality",
        "audit_internal_links",
        "audit_seo_keywords",
        "audit_style_consistency",
        "auto_income",
        "blog_publishing_stats",
        "browse_page",
        "build_game",
        "build_pricing_strategy",
        "build_software",
        "cart_abandonment_sequence",
        "cashflow_summary",
        "check_audience_fatigue",
        "check_brand_consistency",
        "check_content_novelty",
        "check_social_session",
        "classify_image",
        "client_memory_dashboard",
        "computer_use",
        "create_ad_audience",
        "create_brand",
        "create_fiverr_gig",
        "create_flash_sale",
        "create_landing_page",
        "create_linkedin_post",
        "create_pitch_deck",
        "create_post_purchase_flow",
        "create_presentation",
        "create_product_bundle",
        "create_product_pack",
        "create_research_project",
        "create_retargeting_campaign",
        "create_social_content",
        "create_style_profile",
        "create_twitter_thread",
        "create_upsell_offer",
        "create_website",
        "create_workflow",
        "deep_search",
        "deep_think",
        "deliver_purchase",
        "describe_image",
        "discover_leads",
        "document_qa",
        "edit_image",
        "estimate_ad_cac",
        "evaluate_ai_response",
        "evaluate_upwork_job",
        "evolve_style",
        "execute_code",
        "extract_text",
        "fetch_url",
        "find_growth_bottleneck",
        "fiverr_gig_analytics",
        "forecast_cashflow",
        "forecast_revenue",
        "forget_source",
        "forget_user_fact",
        "generate_audience_personas",
        "generate_blog_outline",
        "generate_blog_topic_cluster",
        "generate_image",
        "generate_landing_headlines",
        "generate_linkedin_carousel_outline",
        "generate_linkedin_connection_request",
        "generate_linkedin_hooks",
        "generate_linkedin_outreach_sequence",
        "generate_music",
        "generate_pdf",
        "generate_pillar_strategy",
        "generate_sales_proposal",
        "generate_tweet",
        "generate_unique_angles",
        "generate_video",
        "get_status",
        "get_trends",
        "github_issues",
        "github_pr",
        "github_search",
        "github_self",
        "github_view",
        "github_write",
        "growth_removal_plan",
        "income_dashboard",
        "income_loop_status",
        "interact_browser",
        "internal_linking_stats",
        "landing_page_stats",
        "launch_niche",
        "learn",
        "linkedin_outreach_pipeline",
        "linkedin_post_analytics",
        "list_brands",
        "list_niches",
        "list_research_projects",
        "list_social_sessions",
        "list_user_facts",
        "list_workflows",
        "match_content_to_persona",
        "optimize_cta",
        "optimize_fiverr_title",
        "optimize_product_seo",
        "optimize_shopify_checkout",
        "optimize_upwork_profile",
        "optimize_viral_title",
        "personalize_client_offer",
        "post_to_social",
        "predict_customer_churn",
        "predict_engagement",
        "pricing_dashboard",
        "publish_article",
        "purge_generic_phrases",
        "recommend_persuasion_tactics",
        "recommend_products",
        "record_action_outcome",
        "record_cashflow_entry",
        "record_client_interaction",
        "record_retargeting_metrics",
        "recover_abandoned_cart",
        "register_deliverable",
        "reinforcement_report",
        "remember_user_fact",
        "remove_background",
        "repurpose_to_twitter_thread",
        "retargeting_performance",
        "roi_summary",
        "run_background",
        "run_business_agent",
        "run_crew",
        "run_income",
        "run_income_cycle",
        "run_workflow",
        "score_copy_persuasion",
        "score_linkedin_prospect",
        "search_knowledge",
        "segment_client",
        "select_growth_action",
        "send_email",
        "shopify_live_analytics",
        "shopify_revenue_dashboard",
        "shopify_store_status",
        "simulate_growth_lever",
        "speak",
        "square_sell",
        "start_income_loop",
        "suggest_ad_targeting",
        "suggest_dynamic_price",
        "suggest_internal_links",
        "task_status",
        "think_verified",
        "top_priorities",
        "track_roi",
        "translate",
        "twitter_thread_analytics",
        "update_goal",
        "update_roi_returns",
        "upsert_client_profile",
        "upwork_bidding_analytics",
        "web_search",
        "write_blog_post",
        "write_upwork_proposal",
    }
)


def _execute_tool_source() -> str:
    """Isolates _execute_tool's body from the rest of aria_mind.py so we
    never accidentally pick up tool-name-shaped strings from unrelated
    methods (e.g. _adapt_args_generic's own `tool == "generate_image"`
    checks, which are a different, smaller dispatch used only for retry
    argument adaptation, not the main dispatcher under test here)."""
    text = _ARIA_MIND_PATH.read_text(encoding="utf-8")
    start = text.index("async def _execute_tool(")
    # Next top-level (4-space-indented) `async def` after _execute_tool
    # closes the method; _synthesize is the one that currently follows it.
    end = text.index("\n    async def _synthesize(", start)
    return text[start:end]


def _recognized_tool_names() -> set[str]:
    """Union of both dispatch paths that coexist during the batch-by-batch
    Tool Router migration: names already moved into the _TOOL_HANDLERS
    registry, plus names still recognized by the shrinking if/elif chain.
    Once the chain is empty (last batch), the regex half of this always
    contributes nothing and could be deleted — left in until then so this
    test keeps passing, unmodified in its assertions, through every batch."""
    names: set[str] = set()

    from apps.core.cognition.aria_mind import _TOOL_HANDLERS

    names.update(_TOOL_HANDLERS.keys())

    body = _execute_tool_source()
    for m in re.finditer(r'tool == "([a-zA-Z_]+)"', body):
        names.add(m.group(1))
    for m in re.finditer(r"tool in \(([^)]*)\)", body, re.S):
        names.update(re.findall(r'"([a-zA-Z_]+)"', m.group(1)))
    return names


def test_execute_tool_recognizes_exactly_the_expected_tool_set():
    actual = _recognized_tool_names()
    missing = EXPECTED_TOOL_NAMES - actual
    unexpected = actual - EXPECTED_TOOL_NAMES
    assert not missing, f"Tool(s) dropped from _execute_tool's dispatch: {sorted(missing)}"
    assert not unexpected, (
        f"New tool(s) added to _execute_tool without updating this test's oracle "
        f"list (EXPECTED_TOOL_NAMES): {sorted(unexpected)}"
    )


def test_expected_tool_count_is_173():
    # A second, independent assertion so a bug in the set-difference logic
    # above can't silently mask a dropped/added name.
    assert len(EXPECTED_TOOL_NAMES) == 173
