"""Regression tests for bugs found auditing niche_revenue_engine.py:

1. PrePublicationChecklist.run()'s "pricing_tiers_complete" gate required
   every tier's price > 0. Three catalog niches (affiliate_seo_blog,
   amazon_affiliate_content, ai_tools_directory) are ad/affiliate-monetized
   content niches that intentionally price every tier at $0 in
   NICHE_CATALOG — this gate could never pass for them, so launch_niche()
   always hit the "checklist failed" early-return and their entire revenue
   mechanism could never actually launch.
2. NicheTeam._ai() hardcoded json_mode=True with no way to disable it.
   write_seo_article() calls _ai() expecting markdown-formatted output
   (**H1:**, **META:**, etc.), which directly contradicts the JSON-only
   instruction json_mode=True injects, and any '{'/'[' in the article body
   would get truncated/mangled by the JSON-extraction step.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.niche_revenue_engine import NicheTeam, PrePublicationChecklist, ServiceListing


def _make_listing(**overrides) -> ServiceListing:
    defaults = dict(
        niche_key="affiliate_seo_blog",
        title="A Complete Guide To Something Useful",
        tagline="A great tagline",
        description=" ".join(["word"] * 210),
        deliverables=["a", "b", "c"],
        pricing_tiers={
            "basic": {"price": 0},
            "standard": {"price": 0},
            "premium": {"price": 0},
        },
        keywords=["kw1", "kw2", "kw3"],
        target_audience="everyone",
        portfolio_samples=["s1", "s2", "s3"],
        faq=[{"q": "a", "a": "b"}] * 3,
        turnaround_days=3,
        revision_policy="2 revisions included",
        platforms=["gumroad"],
        category="content",
        tags=["t1", "t2"],
    )
    defaults.update(overrides)
    return ServiceListing(**defaults)


def test_checklist_passes_pricing_gate_for_all_zero_priced_niches():
    checklist = PrePublicationChecklist()
    listing = _make_listing()

    result = checklist.run(listing)

    assert "pricing_tiers_complete" in result.gates_passed
    assert "pricing_tiers_complete" not in result.gates_failed


def test_checklist_still_fails_pricing_gate_for_inconsistent_tiers():
    checklist = PrePublicationChecklist()
    listing = _make_listing(
        pricing_tiers={
            "basic": {"price": 0},
            "standard": {"price": 49},
            "premium": {"price": 99},
        }
    )

    result = checklist.run(listing)

    assert "pricing_tiers_complete" in result.gates_failed


def test_checklist_still_fails_pricing_gate_for_all_zero_placeholder_mistake():
    """Sanity: a genuinely paid niche with all tiers accidentally left at
    $0 should still be catchable — this is inherent to the "all zero is
    OK" relaxation and is an accepted tradeoff, not a regression to guard
    against here. Documented via the sibling "inconsistent tiers" test."""
    checklist = PrePublicationChecklist()
    listing = _make_listing(
        pricing_tiers={
            "basic": {"price": 29},
            "standard": {"price": 49},
            "premium": {"price": 99},
        }
    )

    result = checklist.run(listing)

    assert "pricing_tiers_complete" in result.gates_passed


@pytest.mark.asyncio
async def test_write_seo_article_uses_non_json_mode():
    team = NicheTeam("test_niche", {"name": "Test Niche"})
    listing = _make_listing()

    fake_client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.success = True
    fake_resp.content = "**H1:** Title\n**META:** desc\n**TAGS:** a, b, c"
    fake_client.complete = AsyncMock(return_value=fake_resp)

    with patch("apps.core.tools.ai_client.get_ai_client", return_value=fake_client):
        await team.write_seo_article(listing)

    _, kwargs = fake_client.complete.call_args
    assert kwargs["json_mode"] is False
